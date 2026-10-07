import logging
import random
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from agents.full_scan_orchestrator import FullScanOrchestrator
from agents.code_analysis import CodeAnalysisAgent
from agents.deployment import DeploymentAgent
from agents.monitoring import MonitoringAgent
from agents.pipeline import PipelineAgent
from agents.security import SecurityAgent
from agents.stress import StressAgent
from core.config import Settings
from core.llm_client import LLMClient
from core.queue import EventBus, build_event_bus
from models.schemas import (
    AnalyzeLogsRequest,
    CodeAnalysisResult,
    DeploymentResult,
    MonitoringResult,
    PipelineDecision,
    PipelineState,
    SecurityResult,
    SubmitCodeRequest,
)
from services.memory_store import InMemoryAgentMemoryStore, build_memory_store
from services.auto_pr_service import AutoPRService
from services.github_service import GitHubService
from services.slack_service import SlackService
from services.qa_runner import QARunner
from services.retriever import build_retriever
from services.pipeline_terminal_hooks import publish_pipeline_started, run_terminal_hooks
from services.state_store import BaseStateStore, build_state_store

LOGGER = logging.getLogger(__name__)


class PipelineCancelled(Exception):
    def __init__(self, state: PipelineState) -> None:
        super().__init__("pipeline cancelled")
        self.state = state


class Orchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        llm_client = LLMClient(settings)
        self.llm_client = llm_client

        self.memory_store = build_memory_store(settings)
        self.retriever = build_retriever(settings.retriever_backend)
        self.full_scan_orchestrator = FullScanOrchestrator(
            llm_client,
            qa_timeout_seconds=settings.qa_timeout_seconds,
            qa_mode=settings.qa_mode,
            security_scanners_enabled=settings.security_scanners_enabled,
        )

        self.code_agent = CodeAnalysisAgent(llm_client)
        self.security_agent = SecurityAgent(llm_client)
        self.pipeline_agent = PipelineAgent(llm_client)
        self.deployment_agent = DeploymentAgent(llm_client)
        self.monitoring_agent = MonitoringAgent(llm_client)
        self.stress_agent = StressAgent(llm_client)

        for agent in [
            self.code_agent,
            self.security_agent,
            self.pipeline_agent,
            self.deployment_agent,
            self.monitoring_agent,
        ]:
            agent.memory_enabled = settings.agent_memory_enabled
            agent.memory_store = self.memory_store
            agent.retriever = self.retriever

        self.state_store: BaseStateStore = build_state_store(settings.database_url)
        queue_backend = settings.queue_backend
        executor_mode = (settings.pipeline_executor or "auto").strip().lower()
        if executor_mode in {"inline", "memory"}:
            queue_backend = "memory"
        elif executor_mode == "redis":
            queue_backend = "redis"
        self.event_bus: EventBus = build_event_bus(queue_backend, settings.redis_url)
        self.qa_runner = QARunner(timeout_seconds=settings.qa_timeout_seconds)

    async def submit_code(
        self,
        request: SubmitCodeRequest,
        github_token: str | None = None,
        existing_state: PipelineState | None = None,
        *,
        resume: bool = False,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> PipelineState:
        state = existing_state or PipelineState(repo_name=request.repo_name)
        if correlation_id and not state.correlation_id:
            state.correlation_id = correlation_id
        if trace_id and not state.trace_id:
            state.trace_id = trace_id
        state.artifacts["submit_request"] = request.model_dump()
        blocker_reasons: list[str] = []
        opened_pr_bundles: list[Any] = []
        skip_scan = resume and isinstance(state.artifacts.get("full_scan_combined"), dict)
        skip_auto_pr = resume and isinstance(state.artifacts.get("auto_pr_registry"), dict)
        skip_stress = resume and isinstance(state.artifacts.get("stress"), dict)
        slack = SlackService()
        github = GitHubService(github_token)
        repo_full = request.repo_full_name or GitHubService.parse_repo_full_name(request.clone_url or "")
        await slack.pipeline_started(state.pipeline_id, request.repo_name)
        publish_pipeline_started(state, repo_full_name=repo_full or request.repo_name)
        await github.safe_commit_status(repo_full, None, "pending", "ORION canonical pipeline running")
        index_files = getattr(self.retriever, "index_files", None)
        if callable(index_files):
            index_files(request.repo_files)
        self.full_scan_orchestrator.qa_mode = self.settings.qa_mode
        self.full_scan_orchestrator.security_scanners_enabled = self.settings.security_scanners_enabled

        state.artifacts["multimodal"] = {
            "inputs": [item.model_dump() for item in (request.multimodal_inputs or [])],
            "results": request.multimodal_results or [],
        }

        self._record(state, "dev", "Code submitted")
        self.state_store.upsert(state)
        await self._publish_pipeline_event(state, "Code submitted")

        agent_payload = {
            "code": request.code,
            "diff": request.diff or "",
            "config_text": request.config_text or "",
            "repo_files": request.repo_files or {},
            "multimodal_inputs": [item.model_dump() for item in (request.multimodal_inputs or [])],
            "repo_name": request.repo_name,
        }

        if skip_scan:
            combined_issues = state.artifacts["full_scan_combined"]
            self._record(state, "dev", "Resuming from full-scan checkpoint")
            await self._publish_pipeline_event(state, "Resuming from full-scan checkpoint")
        else:
            scan_repo_path = ""
            if request.repo_files or request.code:
                scan_repo_path = self._materialize_repo_snapshot(request)
            try:
                combined_issues = await self.full_scan_orchestrator.execute(
                    repo_path=scan_repo_path,
                    diff_text=request.diff or "",
                    pipeline_run_id=state.pipeline_id,
                    payload=agent_payload,
                )
            finally:
                if scan_repo_path:
                    shutil.rmtree(scan_repo_path, ignore_errors=True)
            combined_issues = self._inject_multimodal_findings(combined_issues, request.multimodal_results or [])
            state.artifacts["full_scan_combined"] = combined_issues
            self._record(state, "dev", "Full scan completed")
            await self._publish_pipeline_event(state, "Full scan completed")
        if not await self._continue(state):
            return state

        if not skip_auto_pr and request.enable_auto_pr and (
            self._has_non_passing_findings(combined_issues)
            or self._has_multimodal_findings(request.multimodal_results or [])
        ):
            repo_path = self._materialize_repo_snapshot(request)
            token_candidates = [github_token, self._resolve_github_token()]
            seen_tokens: set[str] = set()
            effective_tokens: list[str] = []
            for token in token_candidates:
                t = (token or "").strip()
                if not t or t in seen_tokens:
                    continue
                seen_tokens.add(t)
                effective_tokens.append(t)

            gh_cli_available = AutoPRService.is_gh_cli_available()
            auth_candidates: list[str | None] = effective_tokens[:] if effective_tokens else []
            if not auth_candidates and gh_cli_available:
                auth_candidates = [None]

            if not auth_candidates:
                message = "Auto PR skipped: no GitHub token available and gh CLI is not configured"
                blocker_reasons.append(message)
                state.artifacts["auto_pr_registry"] = {
                    "branches": [],
                    "reason": "github-token-and-gh-not-configured",
                }
                self._record(state, "dev", message)
                await self._publish_pipeline_event(state, message)
            else:
                anthropic_key = self.settings.anthropic_api_key
                anthropic_client = Anthropic(api_key=anthropic_key) if anthropic_key else None
                token_errors: list[str] = []

                for token in auth_candidates:
                    try:
                        auto_pr_service = AutoPRService(
                            github_token=token,
                            repo_full_name=request.repo_full_name or request.repo_name,
                            clone_url=request.clone_url or "",
                            base_branch=request.branch,
                        )
                    except ValueError as exc:
                        token_errors.append(str(exc))
                        continue

                    try:
                        if request.enable_auto_pr and self._has_non_passing_findings(combined_issues):
                            if not self.settings.auto_pr_enabled:
                                message = "Auto PR skipped: disabled by configuration (AUTO_PR_ENABLED=false)"
                                blocker_reasons.append(message)
                                state.artifacts["auto_pr_registry"] = {"branches": [], "reason": "auto-pr-disabled"}
                                self._record(state, "dev", message)
                                await self._publish_pipeline_event(state, message)
                            else:
                                opened_pr_bundles = await auto_pr_service.open_all_prs(
                                    combined_issues=combined_issues,
                                    repo_path=repo_path,
                                    run_id=state.pipeline_id,
                                    anthropic_client=anthropic_client,
                                )
                                if opened_pr_bundles:
                                    break
                    except Exception as exc:  # noqa: BLE001
                        token_errors.append(str(exc))
                    finally:
                        await auto_pr_service.close()

                state.artifacts["auto_pr_registry"] = {
                    "branches": [
                        {
                            "issue_id": getattr(bundle, "issue_id", None),
                            "error_label": getattr(bundle, "error_label", None),
                            "branch_name": bundle.branch_name,
                            "pr_number": bundle.pr_number,
                            "pr_url": getattr(bundle, "pr_url", None),
                            "category": bundle.category,
                            "severity": getattr(bundle, "severity", "unknown"),
                            "merged": False,
                            "deleted": False,
                        }
                        for bundle in opened_pr_bundles
                    ],
                    "reason": "prs-opened" if opened_pr_bundles else "no-prs-opened",
                }

                if opened_pr_bundles:
                    pr_urls = self._build_pr_urls(request.repo_full_name or request.repo_name, opened_pr_bundles)
                    pr_message = f"Opened {len(opened_pr_bundles)} fix PRs: {pr_urls}"
                    blocker_reasons.append(f"Pipeline waiting on {len(opened_pr_bundles)} auto-fix PRs")
                    self._record(state, "dev", pr_message)
                    await self._publish_pipeline_event(state, pr_message)
                else:
                    detail = token_errors[0] if token_errors else "No fix PRs were created from detected issues"
                    message = f"Auto PR processing error: {detail}"
                    blocker_reasons.append(message)
                    self._record(state, "dev", message)
                    await self._publish_pipeline_event(state, message)

        code_raw = combined_issues.get("code_issues", {}) if isinstance(combined_issues, dict) else {}
        code_result = self._safe_validate(CodeAnalysisResult, code_raw, fallback={"summary": "analysis unavailable"})
        state.artifacts["code_analysis"] = code_result.model_dump()
        self._record(state, "dev", "Code analysis completed")
        await self._publish_pipeline_event(state, "Code analysis completed")

        security_raw = combined_issues.get("security_issues", {}) if isinstance(combined_issues, dict) else {}
        security_result = self._safe_validate(SecurityResult, security_raw, fallback={"summary": "security scan unavailable"})
        state.artifacts["security"] = security_result.model_dump()
        self._record(state, "dev", "Security scan completed")
        await self._publish_pipeline_event(state, "Security scan completed")

        high_security = any(issue.severity == "high" for issue in security_result.issues)
        if high_security or security_result.blocked:
            blocked_message = "Pipeline blocked by security findings"
            blocker_reasons.append(blocked_message)
            self._record(state, "dev", blocked_message)
            await self._publish_pipeline_event(state, blocked_message)

        security_gate = self._pipeline_decision_for_gate(
            current_stage="dev",
            default_next="qa",
            default_approved=True,
            context={
                "code_analysis": code_result.model_dump(),
                "security": security_result.model_dump(),
                "gate": "security",
            },
        )
        self._store_pipeline_decision(state, "security_gate", security_gate)
        if security_gate.next_stage == "blocked" or not security_gate.approved:
            blocked_message = f"Pipeline control blocked after security gate: {security_gate.reason}"
            blocker_reasons.append(blocked_message)
            self._record(state, "qa", blocked_message)
            await self._publish_pipeline_event(state, blocked_message)

        state.current_stage = "qa"
        qa_details = combined_issues.get("qa_issues", {}) if isinstance(combined_issues, dict) else {}
        if not isinstance(qa_details, dict):
            qa_details = {"passed": False, "summary": "QA result unavailable"}
        qa_passed = bool(qa_details.get("passed", True))
        state.artifacts["qa"] = qa_details
        self._record(state, "qa", f"QA result: {'pass' if qa_passed else 'fail'}")
        await self._publish_pipeline_event(state, f"QA result: {'pass' if qa_passed else 'fail'}")
        if not qa_passed:
            blocker_reasons.append("QA checks failed")
            self._record(state, "qa", "QA checks failed")
            await self._publish_pipeline_event(state, "QA checks failed")

        qa_gate = self._pipeline_decision_for_gate(
            current_stage="qa",
            default_next="stress",
            default_approved=True,
            context={
                "qa_passed": qa_passed,
                "code_analysis": code_result.model_dump(),
                "security": security_result.model_dump(),
                "gate": "qa",
            },
        )
        self._store_pipeline_decision(state, "qa_gate", qa_gate)
        if qa_gate.next_stage == "blocked" or not qa_gate.approved:
            blocked_message = f"Pipeline control blocked after QA gate: {qa_gate.reason}"
            blocker_reasons.append(blocked_message)
            self._record(state, "stress", blocked_message)
            await self._publish_pipeline_event(state, blocked_message)

        state.current_stage = "stress"
        if skip_stress:
            stress_result = state.artifacts["stress"]
            stress_passed = bool(stress_result.get("passed"))
            self._record(
                state,
                "stress",
                f"Resuming stress checkpoint: {'pass' if stress_passed else 'fail'}",
            )
            await self._publish_pipeline_event(
                state,
                f"Resuming stress checkpoint: {'pass' if stress_passed else 'fail'}",
            )
        else:
            stress_result = self.stress_agent.evaluate(code_result, security_result)
            state.artifacts["stress"] = stress_result
            stress_passed = bool(stress_result.get("passed"))
            self._record(state, "stress", f"Stress test result: {'pass' if stress_passed else 'fail'} ({stress_result.get('summary', '')})")
            await self._publish_pipeline_event(state, f"Stress test result: {'pass' if stress_passed else 'fail'}")
        if not await self._continue(state):
            return state
        if not stress_passed:
            blocker_reasons.append("Stress checks failed")
            self._record(state, "stress", "Stress checks failed")
            await self._publish_pipeline_event(state, "Stress checks failed")

        stress_gate = self._pipeline_decision_for_gate(
            current_stage="stress",
            default_next="approval",
            default_approved=True,
            context={
                "stress_passed": stress_passed,
                "code_analysis": code_result.model_dump(),
                "security": security_result.model_dump(),
                "gate": "stress",
            },
        )
        self._store_pipeline_decision(state, "stress_gate", stress_gate)
        if stress_gate.next_stage == "blocked" or not stress_gate.approved:
            blocked_message = f"Pipeline control blocked after stress gate: {stress_gate.reason}"
            blocker_reasons.append(blocked_message)
            self._record(state, "approval", blocked_message)
            await self._publish_pipeline_event(state, blocked_message)

        from core.change_risk import compute_change_risk
        from core.gate_fusion import fuse_stage_results

        repo_files = state.artifacts.get("repo_files") if isinstance(state.artifacts.get("repo_files"), dict) else {}
        changed_files = list(repo_files.keys()) if isinstance(repo_files, dict) else []
        fused = fuse_stage_results(
            code=state.artifacts.get("code_analysis"),
            security=state.artifacts.get("security"),
            qa=state.artifacts.get("qa"),
            stress=state.artifacts.get("stress"),
        )
        state.artifacts["change_risk_report"] = compute_change_risk(
            changed_files=changed_files,
            code=state.artifacts.get("code_analysis"),
            security=state.artifacts.get("security"),
            qa=state.artifacts.get("qa"),
            stress=state.artifacts.get("stress"),
            gate_fusion=fused,
            analysis_mode=str(state.artifacts.get("code_analysis", {}).get("analysis_mode", "heuristic")),
        )

        state.current_stage = "approval"
        decision = self._pipeline_decision_for_gate(
            current_stage="approval",
            default_next="deployment",
            default_approved=True,
            context={
                "code_analysis": code_result.model_dump(),
                "security": security_result.model_dump(),
                "gate": "approval",
            },
        )
        state.artifacts["approval"] = decision.model_dump()
        self._record(state, "approval", decision.reason)
        await self._publish_pipeline_event(state, decision.reason)

        if (not decision.approved and decision.next_stage != "deployment") or "Approval fallback" in decision.reason:
            denied_message = f"Approval gate denied: {decision.reason}"
            blocker_reasons.append(denied_message)
            self._record(state, "approval", denied_message)
            await self._publish_pipeline_event(state, denied_message)

        if blocker_reasons:
            state.current_stage = "deployment"
            deployment = DeploymentResult(
                status="failed",
                reason="Deployment skipped due to unresolved blockers in earlier stages.",
                environment="staging",
            )
            self._record(state, "deployment", deployment.reason)
            await self._publish_pipeline_event(state, deployment.reason)
            if not opened_pr_bundles:
                await self._attempt_auto_redeployment(state, "; ".join(blocker_reasons))
                if state.status == "completed":
                    self.state_store.upsert(state)
                    return state
        else:
            deployment = self._execute_deployment(state)

        state.artifacts["deployment"] = deployment.model_dump()

        state.current_stage = "monitoring"
        monitoring_input = self._build_monitoring_input(state)
        monitoring_result = self.analyze_logs(
            AnalyzeLogsRequest(
                pipeline_id=state.pipeline_id,
                logs=monitoring_input,
            )
        )
        state.artifacts["monitoring"] = monitoring_result.model_dump()
        self._record(state, "monitoring", monitoring_result.summary)
        await self._publish_pipeline_event(state, monitoring_result.summary)

        state.artifacts["pipeline_summary"] = {
            "blockers": blocker_reasons,
            "auto_pr_count": len(opened_pr_bundles),
            "deployment_status": deployment.status,
            "monitoring_summary": monitoring_result.summary,
        }

        if blocker_reasons:
            if opened_pr_bundles:
                state.current_stage = "blocked_with_prs_sent"
                state.status = "blocked_with_prs_sent"
                message = "Pipeline finished with blockers; auto-fix PRs were generated."
            else:
                state.current_stage = "blocked"
                state.status = "blocked"
                message = "Pipeline finished with blockers and needs manual remediation."
            self._record(state, state.current_stage, message)
            await self._publish_pipeline_event(state, message)
        elif deployment.status == "deployed":
            state.current_stage = "completed"
            state.status = "completed"
            self._record(state, "completed", deployment.reason)
            await self._publish_pipeline_event(state, deployment.reason)
        elif deployment.status == "rolled_back":
            state.current_stage = "rolled_back"
            state.status = "failed"
            self._record(state, "rolled_back", deployment.reason)
            await self._publish_pipeline_event(state, deployment.reason)
        else:
            state.current_stage = "failed"
            state.status = "failed"
            self._record(state, "failed", deployment.reason)
            await self._publish_pipeline_event(state, deployment.reason)

        slack = SlackService()
        github = GitHubService(github_token)
        repo_full = request.repo_full_name or GitHubService.parse_repo_full_name(request.clone_url or "")
        if state.status in {"blocked", "blocked_with_prs_sent"}:
            await slack.pipeline_blocked(state.pipeline_id, "; ".join(blocker_reasons) or state.status)
            await github.safe_commit_status(repo_full, None, "failure", "Pipeline blocked")
        elif state.status == "completed":
            await slack.pipeline_completed(state.pipeline_id, request.repo_name)
            await github.safe_commit_status(repo_full, None, "success", "Pipeline completed")
        elif state.status == "failed":
            await slack.pipeline_failed(state.pipeline_id, deployment.reason if blocker_reasons else state.status)
            await github.safe_commit_status(repo_full, None, "failure", "Pipeline failed")

        run_terminal_hooks(state, repo_full_name=repo_full or request.repo_name)
        self.state_store.upsert(state)
        return state

    async def _continue(self, state: PipelineState) -> bool:
        latest = self.state_store.get(state.pipeline_id)
        if latest is not None and latest.cancelled:
            state.cancelled = True
            state.status = "cancelled"
            state.current_stage = "cancelled"
            self._record(state, "cancelled", "Pipeline cancelled by operator")
            run_terminal_hooks(state)
            self.state_store.upsert(state)
            await self._publish_pipeline_event(state, "Pipeline cancelled by operator")
            return False
        self.state_store.upsert(state)
        return True

    def request_cancel(self, pipeline_id: str) -> PipelineState | None:
        state = self.get_status(pipeline_id)
        if state is None:
            return None
        if state.status in {"completed", "blocked", "blocked_with_prs_sent", "failed", "cancelled"}:
            return state
        state.cancelled = True
        state.status = "cancelling"
        self.state_store.upsert(state)
        return state

    async def retry_pipeline(self, pipeline_id: str, github_token: str | None = None) -> PipelineState:
        state = self.state_store.get(pipeline_id)
        if state is None:
            raise ValueError(f"Pipeline not found: {pipeline_id}")
        snapshot = state.artifacts.get("submit_request")
        if not isinstance(snapshot, dict):
            raise ValueError("No submit snapshot stored for this pipeline")
        request = SubmitCodeRequest.model_validate(snapshot)
        state.cancelled = False
        state.status = "running"
        state.current_stage = "dev"
        self._record(state, "dev", "Pipeline retry started")
        self.state_store.upsert(state)
        await self._publish_pipeline_event(state, "Pipeline retry started")
        return await self.submit_code(request, github_token=github_token, existing_state=state)

    async def resume_pipeline(self, pipeline_id: str, github_token: str | None = None) -> PipelineState:
        state = self.state_store.get(pipeline_id)
        if state is None:
            raise ValueError(f"Pipeline not found: {pipeline_id}")
        if not isinstance(state.artifacts.get("full_scan_combined"), dict):
            raise ValueError("No checkpoint available for this pipeline; use retry for a full restart")
        snapshot = state.artifacts.get("submit_request")
        if not isinstance(snapshot, dict):
            raise ValueError("No submit snapshot stored for this pipeline")
        request = SubmitCodeRequest.model_validate(snapshot)
        state.cancelled = False
        state.status = "running"
        self._record(state, state.current_stage or "dev", "Pipeline resume started")
        self.state_store.upsert(state)
        await self._publish_pipeline_event(state, "Pipeline resume started")
        return await self.submit_code(request, github_token=github_token, existing_state=state, resume=True)

    def list_pipelines(self, limit: int = 20) -> list[PipelineState]:
        return self.state_store.list_recent(limit=limit)

    def _build_monitoring_input(self, state: PipelineState) -> str:
        security = state.artifacts.get("security", {})
        code = state.artifacts.get("code_analysis", {})
        summary_lines = [
            f"pipeline_id={state.pipeline_id}",
            f"repo_name={state.repo_name}",
            f"current_stage={state.current_stage}",
            f"status={state.status}",
            f"security_summary={security.get('summary', '') if isinstance(security, dict) else ''}",
            f"code_summary={code.get('summary', '') if isinstance(code, dict) else ''}",
        ]
        return "\n".join(summary_lines)

    def _resolve_github_token(self) -> str:
        token = (self.settings.github_token or "").strip()
        if token:
            return token

        # Fallback for local dev cases where long-lived singletons hold stale settings.
        env_path = Path(__file__).resolve().parents[1] / ".env"
        if not env_path.exists():
            return ""

        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if not line or line.lstrip().startswith("#"):
                    continue
                if not line.startswith("GITHUB_TOKEN="):
                    continue
                _, value = line.split("=", 1)
                value = value.strip().strip('"').strip("'")
                if value:
                    return value
        except OSError:
            return ""

        return ""

    def _has_non_passing_findings(self, combined_issues: dict[str, Any]) -> bool:
        code_issues = combined_issues.get("code_issues", {})
        security_issues = combined_issues.get("security_issues", {})
        qa_issues = combined_issues.get("qa_issues", {})

        code_non_passing = isinstance(code_issues, dict) and bool(code_issues.get("issues"))
        security_non_passing = isinstance(security_issues, dict) and (
            bool(security_issues.get("issues")) or bool(security_issues.get("blocked"))
        )
        qa_non_passing = isinstance(qa_issues, dict) and (not bool(qa_issues.get("passed", True)))
        return code_non_passing or security_non_passing or qa_non_passing

    def _has_multimodal_findings(self, multimodal_results: list[dict[str, Any]]) -> bool:
        for result in multimodal_results:
            if not isinstance(result, dict):
                continue
            if int(result.get("issues_found", 0) or 0) > 0:
                return True
            if str(result.get("severity", "")).lower() in {"high", "critical"}:
                return True
        return False

    def _inject_multimodal_findings(self, combined_issues: dict[str, Any], multimodal_results: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(combined_issues, dict):
            combined_issues = {}

        code_issues = combined_issues.get("code_issues")
        if not isinstance(code_issues, dict):
            code_issues = {"summary": "", "issues": []}
            combined_issues["code_issues"] = code_issues

        issue_list = code_issues.get("issues")
        if not isinstance(issue_list, list):
            issue_list = []
            code_issues["issues"] = issue_list

        for result in multimodal_results:
            if not isinstance(result, dict):
                continue
            mode = str(result.get("mode", "multimodal"))
            issues = result.get("issues", [])
            if not isinstance(issues, list) or not issues:
                continue

            for line in issues[:20]:
                issue_list.append(
                    {
                        "type": f"multimodal_{mode}_issue",
                        "severity": "high",
                        "line": "n/a",
                        "fix": f"Review {mode} analyzer output and apply remediation",
                        "snippet": str(line),
                        "file_path": "orion_reports",
                    }
                )

        return combined_issues

    def _build_pr_urls(self, repo_full_name: str, bundles: list[Any]) -> str:
        urls = [
            f"https://github.com/{repo_full_name}/pull/{bundle.pr_number}"
            for bundle in bundles
            if getattr(bundle, "pr_number", None) is not None
        ]
        return ", ".join(urls)

    def _materialize_repo_snapshot(self, request: SubmitCodeRequest) -> str:
        tmp_dir = tempfile.mkdtemp(prefix="orion_repo_")
        root = Path(tmp_dir)
        repo_files = request.repo_files or {}

        if not repo_files and request.code:
            (root / "main.py").write_text(request.code, encoding="utf-8")
            return tmp_dir

        for rel_path, content in repo_files.items():
            path = Path(rel_path)
            if path.is_absolute() or ".." in path.parts:
                continue
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return tmp_dir

    def get_status(self, pipeline_id: str) -> PipelineState | None:
        return self.state_store.get(pipeline_id)

    async def trigger_deployment(
        self,
        pipeline_id: str,
        approved_by: str | None = None,
        actor: str | None = None,
        actor_roles: list[str] | None = None,
    ) -> PipelineState | None:
        state = self.state_store.get(pipeline_id)
        if state is None:
            return None

        if state.current_stage not in {"approval", "blocked"}:
            return state

        state.current_stage = "deployment"
        self._record(state, "deployment", f"Manual deployment trigger by {approved_by or 'system'}")
        await self._publish_pipeline_event(state, f"Manual deployment trigger by {approved_by or 'system'}")
        deployment = self._execute_deployment(state)
        state.artifacts["deployment_manual"] = deployment.model_dump()
        if deployment.status == "deployed":
            state.current_stage = "completed"
            state.status = "completed"
        elif deployment.status == "rolled_back":
            state.current_stage = "rolled_back"
            state.status = "failed"
        else:
            state.current_stage = "failed"
            state.status = "failed"
        self._record(state, state.current_stage, deployment.reason)
        await self._publish_pipeline_event(state, deployment.reason)
        self._append_audit_event(
            state,
            action="trigger_deployment",
            actor=actor or approved_by or "system",
            roles=actor_roles or [],
            outcome=state.status,
            details={"reason": deployment.reason, "pipeline_id": pipeline_id},
        )
        run_terminal_hooks(state)
        self.state_store.upsert(state)
        return state

    async def _attempt_auto_redeployment(self, state: PipelineState, blocked_message: str) -> None:
        if not self.settings.auto_redeploy_on_blocked:
            return

        if not self._is_auto_resolvable_block(state, blocked_message):
            skip_message = f"Auto-remediation skipped: {self._auto_skip_reason(state, blocked_message)}"
            self._record(state, "blocked", skip_message)
            await self._publish_pipeline_event(state, skip_message)
            return

        start_message = "Auto-remediation started for blocked pipeline"
        self._record(state, "blocked", start_message)
        await self._publish_pipeline_event(state, start_message)

        deployment = self._execute_deployment(state)
        state.artifacts["deployment_auto"] = deployment.model_dump()
        if deployment.status == "deployed":
            state.current_stage = "completed"
            state.status = "completed"
        elif deployment.status == "rolled_back":
            state.current_stage = "rolled_back"
            state.status = "failed"
        else:
            state.current_stage = "failed"
            state.status = "failed"
        self._record(state, state.current_stage, f"Auto-remediation result: {deployment.reason}")
        await self._publish_pipeline_event(state, f"Auto-remediation result: {deployment.reason}")
        self._append_audit_event(
            state,
            action="auto_redeploy",
            actor="system-auto-remediator",
            roles=["system"],
            outcome=state.status,
            details={
                "reason": deployment.reason,
                "pipeline_id": state.pipeline_id,
                "blocked_message": blocked_message,
            },
        )

    def _is_auto_resolvable_block(self, state: PipelineState, blocked_message: str) -> bool:
        if "approval" not in blocked_message.lower():
            return False

        security = state.artifacts.get("security", {})
        security_issues = security.get("issues", []) if isinstance(security, dict) else []
        has_high_security = any(
            isinstance(issue, dict) and issue.get("severity") == "high"
            for issue in security_issues
        )
        return not has_high_security

    def _auto_skip_reason(self, state: PipelineState, blocked_message: str) -> str:
        if "approval" not in blocked_message.lower():
            return "blocked reason is not auto-resolvable by policy"

        security = state.artifacts.get("security", {})
        security_issues = security.get("issues", []) if isinstance(security, dict) else []
        has_high_security = any(
            isinstance(issue, dict) and issue.get("severity") == "high"
            for issue in security_issues
        )
        if has_high_security:
            return "high-severity security findings require manual fix"
        return "auto-remediation policy not satisfied"

    async def wait_pipeline_event(self, pipeline_id: str, timeout: float = 1.0) -> dict[str, Any]:
        topic = self._pipeline_topic(pipeline_id)
        try:
            event = await self.event_bus.consume(topic, timeout=timeout)
            return event
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Pipeline event consume failed topic=%s error=%s", topic, exc)
            return {}

    def analyze_logs(self, request: AnalyzeLogsRequest) -> MonitoringResult:
        from core.gate_fusion import correlate_logs_with_gates, fuse_stage_results
        from core.text_analysis import sanitize_for_agent

        sanitized = sanitize_for_agent(request.logs)
        gate: dict[str, Any] = {}
        correlation: dict[str, Any] = {}
        if request.pipeline_id:
            state = self.get_status(request.pipeline_id)
            if state is not None:
                gate = fuse_stage_results(
                    code=state.artifacts.get("code_analysis"),
                    security=state.artifacts.get("security"),
                    qa=state.artifacts.get("qa"),
                    stress=state.artifacts.get("stress"),
                )
                correlation = correlate_logs_with_gates(sanitized, gate)

        response = self.monitoring_agent.run(
            {
                "logs": sanitized,
                "pipeline_id": request.pipeline_id,
                "multimodal_inputs": [item.model_dump() for item in (request.multimodal_inputs or [])],
                "gate_fusion": gate,
                "gate_correlation": correlation,
            }
        )
        result = self._safe_validate(
            MonitoringResult,
            response,
            fallback={"summary": "monitoring unavailable", "anomalies": [], "suggestions": []},
        )
        if correlation.get("correlation_hints"):
            merged = list(dict.fromkeys([*result.suggestions, *correlation["correlation_hints"]]))
            result = result.model_copy(update={"suggestions": merged, "gate_correlation": correlation or None})
        elif correlation:
            result = result.model_copy(update={"gate_correlation": correlation})
        return result

    def _execute_deployment(self, state: PipelineState) -> DeploymentResult:
        state.current_stage = "deployment"
        deployment_raw = self.deployment_agent.run(
            {
                "pipeline_id": state.pipeline_id,
                "security": state.artifacts.get("security", {}),
                "code_analysis": state.artifacts.get("code_analysis", {}),
                "history": state.history,
            }
        )
        validated = self._safe_validate(
            DeploymentResult,
            deployment_raw,
            fallback={"status": "failed", "reason": "deployment decision unavailable", "environment": "staging"},
        )
        if validated.reason == "deployment decision unavailable":
            return self._fallback_deployment_result(state)
        return validated

    def _simulate_qa(self, analysis: CodeAnalysisResult) -> bool:
        if analysis.quality_score < 60:
            return False
        seed = analysis.quality_score + len(analysis.issues)
        random.seed(seed)
        return random.random() > 0.1

    def _run_qa_stage(self, code_result: CodeAnalysisResult, repo_files: dict[str, str]) -> tuple[bool, dict[str, Any]]:
        if self.settings.qa_mode.lower() == "real":
            qa_result = self.qa_runner.run_pytest(repo_files=repo_files)
            return bool(qa_result.get("passed", False)), qa_result

        simulated = self._simulate_qa(code_result)
        return simulated, {"mode": "simulated", "passed": simulated}

    def _simulate_stress(self, analysis: CodeAnalysisResult, security: SecurityResult) -> bool:
        if security.blocked:
            return False

        high_security = any(issue.severity == "high" for issue in security.issues)
        if high_security:
            return False

        if analysis.quality_score < 60:
            return False

        risk = len([issue for issue in analysis.issues if issue.severity in {"high", "medium"}]) + len(security.issues)
        seed = analysis.quality_score + risk
        random.seed(seed)
        return random.random() > min(0.4, risk * 0.05)

    def _record(self, state: PipelineState, stage: str, message: str) -> None:
        state.updated_at = datetime.utcnow()
        state.history.append(
            {
                "ts": state.updated_at.isoformat(),
                "stage": stage,
                "message": message,
            }
        )
        LOGGER.info("pipeline=%s stage=%s message=%s", state.pipeline_id, stage, message)

    def _safe_validate(self, model_cls: Any, payload: dict[str, Any], fallback: dict[str, Any]) -> Any:
        try:
            return model_cls.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Model validation failed for %s: %s", model_cls.__name__, exc)
            return model_cls.model_validate(fallback)

    async def _publish_event(self, topic: str, payload: dict[str, Any]) -> None:
        try:
            await self.event_bus.publish(topic, payload)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Event publish failed topic=%s error=%s", topic, exc)

    async def _publish_pipeline_event(self, state: PipelineState, message: str) -> None:
        event = {
            "type": "pipeline_stage",
            "pipeline_id": state.pipeline_id,
            "stage": state.current_stage,
            "status": state.status,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._publish_event(self._pipeline_topic(state.pipeline_id), event)

    def _pipeline_topic(self, pipeline_id: str) -> str:
        return f"pipeline:{pipeline_id}"

    def _pipeline_decision_for_gate(
        self,
        current_stage: str,
        default_next: str,
        default_approved: bool,
        context: dict[str, Any],
    ) -> PipelineDecision:
        decision_raw = self.pipeline_agent.run(
            {
                "current_stage": current_stage,
                "context": context,
            }
        )
        fallback_reason = self._fallback_gate_reason(current_stage)
        decision = self._safe_validate(
            PipelineDecision,
            decision_raw,
            fallback={
                "next_stage": default_next,
                "reason": fallback_reason,
                "approved": default_approved,
            },
        )
        return self._enforce_transition(current_stage, decision, default_next, default_approved)

    def _fallback_gate_reason(self, current_stage: str) -> str:
        llm_mode = "live" if self.settings.llm_api_key else "mock"
        if current_stage == "approval":
            return (
                "Approval fallback applied: pipeline control did not return a valid approval decision "
                f"(llm_mode={llm_mode})."
            )
        return f"Fallback decision at {current_stage} gate because pipeline control output was invalid (llm_mode={llm_mode})."

    def _fallback_deployment_result(self, state: PipelineState) -> DeploymentResult:
        security = state.artifacts.get("security", {})
        security_issues = security.get("issues", []) if isinstance(security, dict) else []
        has_high_security = any(
            isinstance(issue, dict) and issue.get("severity") == "high"
            for issue in security_issues
        )
        if has_high_security:
            return DeploymentResult(
                status="failed",
                reason="Deployment denied by fallback policy: high-severity security findings remain unresolved.",
                environment="staging",
            )
        return DeploymentResult(
            status="deployed",
            reason="Deployment approved by deterministic fallback policy (no high-severity security findings).",
            environment="staging",
        )

    def _enforce_transition(
        self,
        current_stage: str,
        decision: PipelineDecision,
        default_next: str,
        default_approved: bool,
    ) -> PipelineDecision:
        allowed: dict[str, set[str]] = {
            "dev": {"qa", "blocked"},
            "qa": {"stress", "blocked", "failed"},
            "stress": {"approval", "blocked", "failed"},
            "approval": {"deployment", "blocked"},
        }
        allowed_next = allowed.get(current_stage, {default_next})
        if decision.next_stage in allowed_next:
            return decision
        return PipelineDecision(
            next_stage=default_next,
            reason=f"Invalid transition from {current_stage} to {decision.next_stage}; defaulted to {default_next}",
            approved=default_approved,
        )

    def _store_pipeline_decision(self, state: PipelineState, gate: str, decision: PipelineDecision) -> None:
        existing = state.artifacts.get("pipeline_decisions", [])
        if not isinstance(existing, list):
            existing = []
        existing.append({"gate": gate, **decision.model_dump()})
        state.artifacts["pipeline_decisions"] = existing

    def _append_audit_event(
        self,
        state: PipelineState,
        action: str,
        actor: str,
        roles: list[str],
        outcome: str,
        details: dict[str, Any],
    ) -> None:
        trail = state.artifacts.get("audit_trail", [])
        if not isinstance(trail, list):
            trail = []
        trail.append(
            {
                "ts": datetime.utcnow().isoformat(),
                "action": action,
                "actor": actor,
                "roles": roles,
                "outcome": outcome,
                "details": details,
            }
        )
        state.artifacts["audit_trail"] = trail
