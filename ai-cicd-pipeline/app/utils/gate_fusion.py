"""Unified gate evaluation — shared logic across ORION stacks."""

from __future__ import annotations

from typing import Any


def fuse_stage_results(
    *,
    code: dict[str, Any] | None = None,
    security: dict[str, Any] | None = None,
    qa: dict[str, Any] | None = None,
    stress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    violations: list[str] = []
    warnings: list[str] = []
    risk = 0
    code = code or {}
    security = security or {}
    qa = qa or {}
    stress = stress or {}

    severity = str(code.get("severity", code.get("overall_severity", ""))).lower()
    if severity == "fail":
        violations.append("code analysis failed")
        risk += 35
    elif severity == "warn":
        warnings.append("code analysis warnings")
        risk += 10

    sec_risk = str(security.get("overall_risk", security.get("highest_severity", ""))).lower()
    if sec_risk in {"critical", "high"}:
        violations.append(f"security risk {sec_risk}")
        risk += 40 if sec_risk == "critical" else 25
    elif sec_risk == "medium":
        warnings.append("medium security findings")
        risk += 12
    if security.get("passed") is False:
        violations.append("security gate failed")
        risk += 30

    qa_passed = qa.get("passed")
    qa_verdict = str(qa.get("verdict", "")).lower()
    if qa_passed is False or qa_verdict == "fail":
        violations.append("QA failed")
        risk += 30
    elif qa.get("skipped"):
        warnings.append("QA skipped")

    stress_passed = stress.get("passed")
    perf = str(stress.get("performance_verdict", "")).lower()
    if stress_passed is False or perf == "fail":
        violations.append("stress test failed")
        risk += 25
    elif perf == "warn":
        warnings.append("stress test warnings")
        risk += 8

    p95 = stress.get("p95_ms") or stress.get("p95")
    if isinstance(p95, (int, float)) and p95 > 2000:
        violations.append(f"p95 latency {p95}ms exceeds 2000ms")
        risk += 15

    risk = min(100, risk)
    if violations:
        verdict, action = "fail", "Block deployment and open remediation workflow"
    elif warnings or risk >= 20:
        verdict, action = "warn", "Proceed with monitoring and staged rollout"
    else:
        verdict, action = "pass", "Approve for deployment"

    return {
        "verdict": verdict,
        "violations": violations,
        "warnings": warnings,
        "risk_score": risk,
        "recommended_action": action,
        "components": {"code": code, "security": security, "qa": qa, "stress": stress},
    }


def correlate_logs_with_gates(log_text: str, gate: dict[str, Any]) -> dict[str, Any]:
    from app.utils.text_analysis import classify_log_type, extract_error_signatures, string_metrics

    sanitized = log_text[:200_000]
    metrics = string_metrics(sanitized)
    errors = extract_error_signatures(sanitized, limit=12)
    log_type = classify_log_type(sanitized)
    gate_verdict = gate.get("verdict", "unknown")
    hints: list[str] = []
    if gate_verdict == "fail" and gate.get("violations"):
        hints.append(f"Pipeline blocked: {'; '.join(gate['violations'][:3])}")
    if log_type == "deployment_crash" and gate_verdict != "pass":
        hints.append("Log pattern matches deployment crash while gates did not pass — prioritize rollback")
    if metrics.get("error_lines", 0) > 5 and gate_verdict == "pass":
        hints.append("High error line count despite passing gates — recommend extended monitoring window")
    return {
        "log_type": log_type,
        "metrics": metrics,
        "error_signatures": errors,
        "gate_verdict": gate_verdict,
        "gate_risk_score": gate.get("risk_score", 0),
        "correlation_hints": hints,
    }
