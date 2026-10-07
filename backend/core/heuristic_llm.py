"""Deterministic agent responses when live LLM providers are unavailable."""

from __future__ import annotations

import json
import re
from typing import Any

from core.rule_engine import run_quality_rules, run_security_rules

_ERROR_LINE = re.compile(r"(error|fail|exception|timeout|denied|fatal|panic)", re.IGNORECASE)
_LOG_SECTION = re.compile(r"Logs:\s*\n(.*?)(?:\n\nMetrics:|\nMulti-modal|\Z)", re.DOTALL | re.IGNORECASE)
_CODE_SECTION = re.compile(r"Input code:\s*\n(.*?)(?:\n\nInput diff:|\Z)", re.DOTALL)


def _section(pattern: re.Pattern[str], prompt: str) -> str:
    match = pattern.search(prompt)
    return (match.group(1) if match else "").strip()


def _collect_repo_files(prompt: str) -> dict[str, str]:
    marker = "Repository files (path -> content):"
    if marker not in prompt:
        return {}
    tail = prompt.split(marker, 1)[1].strip()
    if not tail or tail.startswith("{"):
        try:
            parsed = json.loads(tail.split("\n\n", 1)[0])
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _monitoring_from_logs(logs: str) -> dict[str, Any]:
    anomalies: list[str] = []
    suggestions: list[str] = []
    for line in logs.splitlines():
        stripped = line.strip()
        if not stripped or not _ERROR_LINE.search(stripped):
            continue
        anomalies.append(stripped[:240])
        lower = stripped.lower()
        if "timeout" in lower or "connection" in lower:
            suggestions.append("Check database pool size, network latency, and upstream dependency health.")
        if "payment" in lower or "webhook" in lower:
            suggestions.append("Verify webhook signatures and payment provider credentials.")
        if "signature" in lower:
            suggestions.append("Validate HMAC/signature secrets and clock skew.")

    if not suggestions and anomalies:
        suggestions.append("Inspect the highlighted error lines and correlate with recent deploys.")

    return {
        "summary": (
            f"Detected {len(anomalies)} log anomaly signal(s)"
            if anomalies
            else "No critical anomalies detected in supplied logs"
        ),
        "anomalies": anomalies[:12],
        "suggestions": list(dict.fromkeys(suggestions))[:6] or ["Continue monitoring; no urgent remediation required"],
    }


def _code_analysis(prompt: str) -> dict[str, Any]:
    code = _section(_CODE_SECTION, prompt)
    repo_files = _collect_repo_files(prompt)
    issues = run_quality_rules(code, "", "", repo_files)
    high = sum(1 for item in issues if item.get("severity") == "high")
    medium = sum(1 for item in issues if item.get("severity") == "medium")
    score = max(55, 96 - high * 18 - medium * 6 - min(len(issues), 8))
    return {
        "summary": "Heuristic code review completed",
        "issues": issues,
        "quality_score": score,
        "suggestions": ["Address medium+ findings before production deploy"] if issues else ["Code quality looks acceptable"],
        "mode": "heuristic",
    }


def _security(prompt: str) -> dict[str, Any]:
    code = _section(_CODE_SECTION, prompt)
    repo_files = _collect_repo_files(prompt)
    issues = run_security_rules(code, "", "", repo_files)
    blocked = any(item.get("severity") == "high" for item in issues)
    return {
        "summary": "Heuristic security scan completed",
        "issues": issues,
        "blocked": blocked,
        "mode": "heuristic",
    }


def _pipeline(prompt: str) -> dict[str, Any]:
    blocked = "blocked" in prompt.lower() and "llm_call_error" not in prompt.lower()
    if blocked or "severity': 'high'" in prompt or '"severity": "high"' in prompt:
        return {
            "next_stage": "blocked",
            "reason": "Heuristic gate: high-severity findings require remediation",
            "approved": False,
            "mode": "heuristic",
        }
    return {
        "next_stage": "deployment",
        "reason": "Heuristic approval: no blocking gate signals detected",
        "approved": True,
        "mode": "heuristic",
    }


def _deployment() -> dict[str, Any]:
    return {
        "status": "deployed",
        "reason": "Heuristic deploy simulation succeeded",
        "environment": "staging",
        "mode": "heuristic",
    }


def _git_log(prompt: str) -> dict[str, Any]:
    logs = _section(_LOG_SECTION, prompt) or prompt
    issues: list[dict[str, Any]] = []
    issue_id = 1
    for line in logs.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) > 240:
            continue
        if stripped.startswith("You are") or stripped.startswith("Analyze all"):
            continue
        if "Return ONLY valid JSON" in stripped or "Schema:" in stripped:
            continue
        if not _ERROR_LINE.search(stripped):
            continue
        issues.append(
            {
                "id": issue_id,
                "category": "build_error" if "test" in stripped.lower() else "other",
                "title": stripped[:120],
                "description": stripped,
                "affected_file_or_service": "ci",
                "line_number": None,
                "error_code": None,
                "root_cause": "CI or runtime failure detected in supplied logs",
                "exact_fix": "Review failing step output and rerun the pipeline after fixing the root cause",
                "fix_commands": [],
                "prevention": "Add pre-merge checks for the failing suite",
                "severity": "high" if "fatal" in stripped.lower() or "error" in stripped.lower() else "medium",
            }
        )
        issue_id += 1

    return {
        "analysis_type": "git_log",
        "severity": "high" if issues else "low",
        "total_issues_found": len(issues),
        "issues": issues[:10],
        "server_timeout_analysis": {"detected": False, "endpoints_affected": [], "average_timeout_ms": None, "likely_cause": None, "fix": None},
        "build_error_analysis": {
            "detected": bool(issues),
            "failed_step": issues[0]["title"] if issues else None,
            "missing_dependencies": [],
            "incompatible_versions": [],
            "exact_fix_command": None,
        },
        "git_error_analysis": {"detected": False, "error_type": None, "affected_branch": None, "resolution_commands": []},
        "performance_issues": [],
        "immediate_actions": ["Inspect the first failing log line"] if issues else [],
        "estimated_resolution_minutes": 30 if issues else 5,
        "summary": f"Parsed {len(issues)} issue(s) from logs" if issues else "No actionable git/CI errors detected",
        "can_auto_fix": False,
        "auto_fix_commands": [],
        "mode": "heuristic",
    }


def _payment(prompt: str) -> dict[str, Any]:
    text = _section(_LOG_SECTION, prompt) or prompt
    findings: list[str] = []
    if re.search(r"signature", text, re.IGNORECASE):
        findings.append("Webhook signature mismatch detected")
    if re.search(r"declin|chargeback|refund", text, re.IGNORECASE):
        findings.append("Payment decline or dispute language present")
    if re.search(r"timeout|5\d\d", text):
        findings.append("Upstream payment provider timeout or 5xx response")

    return {
        "summary": "Heuristic payment log/screenshot analysis",
        "integration_detected": bool(re.search(r"stripe|paypal|razorpay|checkout", text, re.IGNORECASE)),
        "risk_level": "high" if findings else "low",
        "findings": findings,
        "recommended_actions": [
            "Validate webhook signing secret and replay protection",
            "Inspect failed charge events in the provider dashboard",
        ]
        if findings
        else ["No payment failure signatures detected in supplied context"],
        "mode": "heuristic",
    }


def heuristic_for_agent(agent_name: str | None, prompt: str) -> dict[str, Any]:
    name = (agent_name or "").lower()
    if "monitoring" in name:
        logs = _section(_LOG_SECTION, prompt) or prompt
        return _monitoring_from_logs(logs)
    if "security" in name:
        return _security(prompt)
    if "code" in name or name == "code_analysis":
        return _code_analysis(prompt)
    if "pipeline" in name:
        return _pipeline(prompt)
    if "deployment" in name:
        return _deployment()
    if "git" in name and "log" in name:
        return _git_log(prompt)
    if "payment" in name:
        return _payment(prompt)
    if "docker" in name:
        return {"security_score": 82, "auto_pr_triggered": False, "summary": "Heuristic Dockerfile review", "mode": "heuristic"}
    if "triage" in name or "production" in name:
        return {
            "incident_severity": "P3",
            "summary": "Heuristic production triage completed",
            "escalate_to_human": False,
            "mode": "heuristic",
        }
    return {"summary": "Heuristic response", "issues": [], "mode": "heuristic"}
