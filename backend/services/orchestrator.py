import logging
import random
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
from services.memory_store import InMemoryAgentMemoryStore
from services.auto_pr_service import AutoPRService
from services.qa_runner import QARunner
from services.retriever import build_retriever
from services.state_store import BaseStateStore, build_state_store

LOGGER = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        llm_client = LLMClient(settings)
        self.llm_client = llm_client

        self.memory_store = InMemoryAgentMemoryStore()
        self.retriever = build_retriever(settings.retriever_backend)
        self.full_scan_orchestrator = FullScanOrchestrator(llm_client, qa_timeout_seconds=settings.qa_timeout_seconds)

        self.code_agent = CodeAnalysisAgent(llm_client)
        self.security_agent = SecurityAgent(llm_client)
        self.pipeline_agent = PipelineAgent(llm_client)
        self.deployment_agent = DeploymentAgent(llm_client)
        self.monitoring_agent = MonitoringAgent(llm_client)

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
        self.event_bus: EventBus = build_event_bus(settings.queue_backend, settings.redis_url)
        self.qa_runner = QARunner(timeout_seconds=settings.qa_timeout_seconds)

    async def submit_code(self, request: SubmitCodeRequest, github_token: str | None = None) -> PipelineState:
        state = PipelineState(repo_name=request.repo_name)
        blocker_reasons: list[str] = []
        opened_pr_bundles: list[Any] = []

        self._record(state, "dev", "Code submitted")
        await self._publish_pipeline_event(state, "Code submitted")

        agent_payload = {
            "code": request.code,
            "diff": request.diff or "",
            "config_text": request.config_text or "",
            "repo_files": request.repo_files or {},
            "multimodal_inputs": [item.model_dump() for item in (request.multimodal_inputs or [])],
            "repo_name": request.repo_name,
        }

        combined_issues = await self.full_scan_orchestrator.execute(
            repo_path="",
            diff_text=request.diff or "",
            pipeline_run_id=state.pipeline_id,
            payload=agent_payload,
        )
        state.artifacts["full_scan_combined"] = combined_issues
        self._record(state, "dev", "Full scan completed")
        await self._publish_pipeline_event(state, "Full scan completed")

        if request.enable_auto_pr and self._has_non_passing_findings(combined_issues):
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
                anthropic_key = self.settings.llm_api_key
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
        stress_passed = self._simulate_stress(code_result, security_result)
        self._record(state, "stress", f"Stress test result: {'pass' if stress_passed else 'fail'}")
        await self._publish_pipeline_event(state, f"Stress test result: {'pass' if stress_passed else 'fail'}")
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

        if not decision.approved and decision.next_stage != "deployment":
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

        self.state_store.upsert(state)
        return state

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
        response = self.monitoring_agent.run(
            {
                "logs": request.logs,
                "pipeline_id": request.pipeline_id,
                "multimodal_inputs": [item.model_dump() for item in (request.multimodal_inputs or [])],
            }
        )
        return self._safe_validate(
            MonitoringResult,
            response,
            fallback={"summary": "monitoring unavailable", "anomalies": [], "suggestions": []},
        )

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
