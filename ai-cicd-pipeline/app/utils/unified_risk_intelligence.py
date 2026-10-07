"""ORION Unified Risk intelligence — final pre-deploy risk rollup and gate."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.utils.unified_risk_engine import compute_unified_risk
from app.utils.unified_risk_registry import resolve_unified_risk_policy


def evaluate_unified_risk_gates(
    *,
    policy: dict[str, Any],
    risk: dict[str, Any],
) -> dict[str, Any]:
    violations: list[str] = []
    warnings: list[str] = []

    if not policy.get("enabled"):
        warnings.append("Unified risk engine disabled — score is advisory only")

    score = int(risk.get("unified_score") or 0)
    level = str(risk.get("risk_level") or "low").lower()
    max_score = float(policy.get("max_unified_score") or 60)

    if score > max_score:
        violations.append(f"Unified risk {score}/100 exceeds policy max {max_score:.0f}")
    elif score >= max_score * 0.85:
        warnings.append(f"Unified risk {score}/100 near policy limit {max_score:.0f}")

    if policy.get("block_on_critical") and level == "critical":
        violations.append(f"Unified risk level is critical ({score}/100)")
    elif policy.get("block_on_high") and level == "high":
        violations.append(f"Unified risk level is high ({score}/100)")

    fusion = risk.get("gate_fusion") or {}
    if policy.get("require_gate_fusion_pass") and fusion.get("verdict") == "fail":
        violations.append("Gate fusion verdict is fail")

    prediction = risk.get("release_prediction") or {}
    if prediction.get("recommendation") == "block":
        violations.append(
            f"Release failure probability {prediction.get('failure_probability_percent')}% exceeds threshold"
        )

    if violations and settings.unified_risk_gate_enabled:
        gate = "fail"
    elif violations or warnings:
        gate = "warn"
    else:
        gate = "pass"

    return {"gate_verdict": gate, "violations": violations, "warnings": warnings}


def build_unified_risk_intelligence_report(
    *,
    run_id: str = "",
    repo: str = "",
    branch: str = "",
    commit: str = "",
    run_status: str = "",
    environment: str = "",
    artifacts: dict[str, dict[str, Any]] | None = None,
    diff_text: str = "",
    changed_files: list[str] | None = None,
) -> dict[str, Any]:
    artifacts = artifacts or {}
    policy = resolve_unified_risk_policy(repo, environment or settings.deploy_environment)

    risk = compute_unified_risk(
        artifacts=artifacts,
        repo=repo,
        environment=environment or settings.deploy_environment,
        diff_text=diff_text,
        changed_files=changed_files,
    )
    gates = evaluate_unified_risk_gates(policy=policy, risk=risk)

    score = risk["unified_score"]
    level = risk["risk_level"]
    top = risk.get("top_contributors") or []
    primary = top[0]["dimension"] if top else "change_risk"

    report: dict[str, Any] = {
        "run_id": run_id or None,
        "repository": repo or None,
        "branch": branch or None,
        "commit": commit or None,
        "run_status": run_status or None,
        "environment": environment or settings.deploy_environment,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": policy,
        "unified_score": score,
        "risk_level": level,
        "dimensions": risk["dimensions"],
        "dimension_weights": risk["dimension_weights"],
        "top_contributors": risk["top_contributors"],
        "operational_contributors": risk["operational_contributors"],
        "change_risk": risk["change_risk_report"],
        "gate_fusion": risk["gate_fusion"],
        "release_prediction": risk["release_prediction"],
        "recommendations": risk["recommendations"],
        "gates": gates,
        "gate_verdict": gates["gate_verdict"],
        "primary_driver": primary,
    }
    report["summary"] = (
        f"Unified risk {score}/100 ({level}); primary driver {primary}. Gate {gates['gate_verdict']}."
    )
    return report
