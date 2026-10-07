"""ORION run diagnostics — evidence, remediation steps, and operator actions for blocked/failed runs."""

from __future__ import annotations

import re
from typing import Any

from app.config import settings

_STAGE_FROM_ERROR = re.compile(r"Stage\s+(\w+)\s+failed", re.I)

_BLOCKED_PLAYBOOKS: dict[str, dict[str, Any]] = {
    "blocked_injection": {
        "category": "ai_safety",
        "headline": "Prompt injection firewall blocked untrusted content before LLM agents ran.",
        "artifact_types": ["prompt_injection_scan", "metadata", "diff"],
        "config_keys": [
            {
                "key": "PROMPT_INJECTION_GATE_ENABLED",
                "default": "true",
                "note": "Set false only for local/dev sandboxes — never in production.",
            },
            {
                "key": "PROMPT_INJECTION_EXCLUDE_GLOBS",
                "note": "Comma-separated paths to skip (tests, docs, security fixtures).",
            },
        ],
        "operator_actions": ["retry", "inspect_artifact", "fix_repo", "adjust_config"],
        "codebase": [
            {"path": "app/utils/prompt_injection_firewall.py", "topic": "Detection rules and severity"},
            {"path": "app/agents/orchestrator.py", "topic": "Ingest gate wiring"},
        ],
    },
    "blocked_secrets": {
        "category": "security",
        "headline": "SecretGuardian detected credentials in repository content.",
        "artifact_types": ["secrets_scan", "metadata"],
        "config_keys": [],
        "operator_actions": ["rotate_credentials", "fix_repo", "retry"],
        "codebase": [{"path": "app/utils/secrets_guardian.py", "topic": "Secret patterns and remediation"}],
    },
    "blocked_code": {
        "category": "quality",
        "headline": "Code analysis gate failed on pylint/AST findings or LLM review.",
        "artifact_types": ["code_analysis", "full_scan_combined"],
        "config_keys": [{"key": "CODE_ANALYSIS_MODEL", "note": "Model used when ANTHROPIC_API_KEY is set."}],
        "operator_actions": ["inspect_artifact", "fix_repo", "retry", "auto_pr"],
        "codebase": [{"path": "app/agents/code_analysis_agent.py", "topic": "Code gate thresholds"}],
    },
    "blocked_security": {
        "category": "security",
        "headline": "Security scan reported severity above MAX_SECURITY_SEVERITY.",
        "artifact_types": ["security_scan", "full_scan_combined"],
        "config_keys": [{"key": "MAX_SECURITY_SEVERITY", "default": settings.max_security_severity}],
        "operator_actions": ["inspect_artifact", "fix_repo", "retry", "auto_pr"],
        "codebase": [{"path": "app/agents/security_agent.py", "topic": "Bandit/pip-audit + LLM merge"}],
    },
    "blocked_tests": {
        "category": "quality",
        "headline": "QA agent reported test failures.",
        "artifact_types": ["qa_report", "full_scan_combined", "test_intelligence"],
        "config_keys": [],
        "operator_actions": ["run_tests_locally", "fix_repo", "retry"],
        "codebase": [{"path": "app/agents/qa_agent.py", "topic": "Pytest gate"}],
    },
    "blocked_stress": {
        "category": "performance",
        "headline": "Stress test exceeded error-rate or p95 latency thresholds.",
        "artifact_types": ["stress_report"],
        "config_keys": [
            {"key": "STAGING_URL", "note": "Target for Locust load test"},
            {"key": "STRESS_TEST_USERS", "note": "Virtual users"},
        ],
        "operator_actions": ["inspect_artifact", "fix_performance", "retry"],
        "codebase": [{"path": "app/agents/stress_test_agent.py", "topic": "Locust thresholds"}],
    },
    "blocked_policy": {
        "category": "governance",
        "headline": "Enterprise policy evaluation did not pass.",
        "artifact_types": ["policy_evaluation", "compliance_report"],
        "config_keys": [
            {"key": "POLICY_ENFORCEMENT_ENABLED"},
            {"key": "POLICY_STRICT_REQUIREMENTS"},
            {"key": "COMPLIANCE_PACKS"},
        ],
        "operator_actions": ["inspect_artifact", "fix_repo", "retry"],
        "codebase": [{"path": "app/utils/policy_engine.py", "topic": "Policy packs"}],
    },
    "blocked_agent_eval": {
        "category": "ai_quality",
        "headline": "Agent evaluation score fell below AGENT_EVAL_MIN_SCORE.",
        "artifact_types": ["agent_eval_report"],
        "config_keys": [
            {"key": "AGENT_EVAL_GATE_ENABLED"},
            {"key": "AGENT_EVAL_MIN_SCORE"},
        ],
        "operator_actions": ["inspect_artifact", "tune_agents", "retry"],
        "codebase": [{"path": "app/utils/agent_eval.py", "topic": "Eval scoring"}],
    },
    "rejected": {
        "category": "approval",
        "headline": "Approval agent rejected deployment risk.",
        "artifact_types": ["approval", "full_scan_combined"],
        "config_keys": [],
        "operator_actions": ["inspect_artifact", "fix_repo", "retry"],
        "codebase": [{"path": "app/agents/approval_agent.py", "topic": "Hard rules + LLM decision"}],
    },
    "failed": {
        "category": "infrastructure",
        "headline": "Pipeline failed due to an infrastructure or orchestration error.",
        "artifact_types": ["metadata", "audit_trail"],
        "config_keys": [
            {"key": "PIPELINE_WORKDIR", "note": "Clone workspace root"},
            {"key": "PIPELINE_WORKDIR_CLEANUP_RETRIES"},
        ],
        "operator_actions": ["read_logs", "retry", "inspect_artifact"],
        "codebase": [
            {"path": "app/services/workdir_manager.py", "topic": "Windows-safe workspace cleanup"},
            {"path": "app/services/git_service.py", "topic": "Clone and diff"},
        ],
    },
}


def _artifact_map(artifacts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for art in artifacts:
        t = str(art.get("artifact_type") or "")
        if t and t not in out:
            out[t] = art
    return out


def _evidence_from_artifacts(status: str, by_type: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    playbook = _BLOCKED_PLAYBOOKS.get(status, {})
    for art_type in playbook.get("artifact_types") or []:
        art = by_type.get(art_type)
        if not art:
            continue
        content = art.get("content") or {}
        item: dict[str, Any] = {"artifact_type": art_type, "summary": art.get("summary") or content.get("summary")}
        if art_type == "prompt_injection_scan":
            for finding in (content.get("findings") or [])[:5]:
                evidence.append(
                    {
                        "kind": "injection_finding",
                        "rule_id": finding.get("rule_id"),
                        "severity": finding.get("severity"),
                        "source": finding.get("source"),
                        "line": finding.get("line"),
                        "snippet": finding.get("snippet"),
                        "action": finding.get("recommended_action"),
                    }
                )
        elif art_type == "secrets_scan":
            for finding in (content.get("findings") or [])[:5]:
                evidence.append(
                    {
                        "kind": "secret_finding",
                        "type": finding.get("type"),
                        "file": finding.get("file"),
                        "line_hint": finding.get("line_hint"),
                        "action": finding.get("recommended_action"),
                    }
                )
        elif art_type in {"code_analysis", "security_scan", "qa_report", "stress_report"}:
            issues = content.get("issues") or content.get("findings") or []
            if isinstance(issues, list):
                for issue in issues[:5]:
                    if isinstance(issue, dict):
                        evidence.append({"kind": f"{art_type}_issue", **issue})
            if not evidence and item.get("summary"):
                evidence.append({"kind": "artifact_summary", **item})
        elif item.get("summary"):
            evidence.append({"kind": "artifact_summary", **item})
    return evidence


def _remediation_steps(status: str, error_message: str | None, by_type: dict[str, dict[str, Any]]) -> list[str]:
    steps: list[str] = []
    if status == "blocked_injection":
        inj = (by_type.get("prompt_injection_scan") or {}).get("content") or {}
        steps.extend(inj.get("remediation_steps") or [])
        if not steps:
            steps.append("Open the prompt_injection_scan artifact and review matched snippets.")
        steps.append("Edit the commit message or changed files, push a new commit, then Retry.")
        steps.append("For local-only testing: PROMPT_INJECTION_GATE_ENABLED=false in .env (not for production).")
        return steps

    if status == "blocked_secrets":
        sec = (by_type.get("secrets_scan") or {}).get("content") or {}
        for finding in (sec.get("findings") or [])[:3]:
            steps.extend(finding.get("remediation_steps") or [finding.get("recommended_action", "")])
        if not steps:
            steps.append("Rotate exposed credentials and remove secrets from the repository.")
        steps.append("Re-run the pipeline after git history is cleaned if secrets were committed.")
        return steps

    if status == "failed":
        msg = (error_message or "").lower()
        if "git clone" in msg or "workdir" in msg or "workspace" in msg or "winerror 32" in msg:
            steps.extend(
                [
                    "Confirm the repository URL and branch are valid and accessible.",
                    "Retry the run — ORION allocates a fresh checkout under {run_id}/checkouts/ (no delete required).",
                    "If the API restarted mid-run, startup recovery removes orphan workspaces.",
                    "Check PIPELINE_WORKDIR and PIPELINE_WORKDIR_CLEANUP_RETRIES in .env.",
                    "Inspect .local/logs/orion.out.log for git_service / workdir_manager entries.",
                ]
            )
        elif "ingest" in msg:
            steps.extend(
                [
                    "Verify clone URL, branch, and GitHub token (if private).",
                    "Retry after confirming network access to the git remote.",
                ]
            )
        else:
            steps.append("Read error_message, Agent Logs, and audit trail for the failing stage.")
            steps.append("Fix the underlying issue in the repo or ORION config, then Retry.")
        return steps

    playbook = _BLOCKED_PLAYBOOKS.get(status, {})
    if playbook.get("headline"):
        steps.append(f"Understand the gate: {playbook['headline']}")
    for art_type in playbook.get("artifact_types") or []:
        art = by_type.get(art_type)
        if art and art.get("summary"):
            steps.append(f"Review artifact `{art_type}`: {art['summary']}")
    steps.append("Apply fixes in the repository or adjust ORION configuration.")
    steps.append("Click Retry on the dashboard or POST /api/v1/pipeline/runs/{id}/retry.")
    return steps


def build_run_diagnostics(
    run: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Produce operator-facing diagnostics for a terminal or blocked pipeline run."""
    status = str(run.get("status") or "")
    error_message = run.get("error_message")
    by_type = _artifact_map(artifacts)
    playbook = _BLOCKED_PLAYBOOKS.get(status, _BLOCKED_PLAYBOOKS.get("failed", {}))

    stage_failed: str | None = None
    if status == "failed" and error_message:
        m = _STAGE_FROM_ERROR.search(str(error_message))
        if m:
            stage_failed = m.group(1)

    evidence = _evidence_from_artifacts(status, by_type)
    remediation = _remediation_steps(status, str(error_message) if error_message else None, by_type)

    analysis_workflow = [
        "Read the status pill and error_message in Pipeline Control.",
        "Open Agent Logs — stats header + event stream mirror orchestrator stages.",
        "Expand Agent Artifacts — each gate writes structured JSON you can inspect.",
        "Use GET /api/v1/pipeline/runs/{id}/diagnostics for machine-readable remediation.",
        "Apply fixes in the repo or .env, then Retry (full re-run from ingest).",
        "For code improvements to ORION itself, follow codebase pointers and add tests.",
    ]

    return {
        "pipeline_run_id": str(run.get("id") or ""),
        "status": status,
        "category": playbook.get("category", "unknown"),
        "headline": playbook.get("headline") or (error_message or f"Run ended with status {status}"),
        "error_message": error_message,
        "failed_stage": stage_failed,
        "evidence": evidence,
        "remediation_steps": remediation,
        "analysis_workflow": analysis_workflow,
        "operator_actions": playbook.get("operator_actions") or ["inspect_artifact", "retry"],
        "artifacts_to_review": [
            t for t in (playbook.get("artifact_types") or []) if t in by_type
        ] or list(by_type.keys())[:6],
        "config_keys": playbook.get("config_keys") or [],
        "codebase": playbook.get("codebase") or [],
        "api": {
            "artifacts": f"/api/v1/pipeline/runs/{run.get('id')}/artifacts",
            "audit": f"/api/v1/pipeline/runs/{run.get('id')}/audit",
            "retry": f"/api/v1/pipeline/runs/{run.get('id')}/retry",
            "text_analyze": "/api/v1/tools/text-analyze",
        },
        "logs_path": "ai-cicd-pipeline/.local/logs/orion.out.log",
    }
