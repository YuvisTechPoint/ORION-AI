"""Release intelligence — DORA metrics, release prediction, and promotion readiness."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.services.slo import compute_pipeline_slo
from app.utils.error_budget import compute_error_budget
from app.utils.gate_fusion import fuse_stage_results
from app.utils.release_intelligence_registry import DORA_BANDS, resolve_release_policy
from app.utils.release_passport import build_release_passport


SUCCESS_STATUSES = frozenset({"deployed", "approved", "monitoring"})
FAILURE_STATUSES = frozenset({"failed", "rolled_back", "auto_rolled_back"})
BLOCKED_PREFIX = "blocked_"


def _duration_hours(run: Any) -> float | None:
    created = getattr(run, "created_at", None)
    completed = getattr(run, "completed_at", None) or created
    if created is None or completed is None:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=timezone.utc)
    return max(0.0, (completed - created).total_seconds()) / 3600.0


def _dora_band(metric: str, value: float, *, lower_is_better: bool = False) -> str:
    bands = DORA_BANDS.get(metric) or {}
    elite = float(bands.get("elite", 0))
    high = float(bands.get("high", 0))
    medium = float(bands.get("medium", 0))
    if lower_is_better:
        if value <= elite:
            return "elite"
        if value <= high:
            return "high"
        if value <= medium:
            return "medium"
        return "low"
    if value >= elite:
        return "elite"
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low"


def compute_dora_metrics(runs: list[Any], *, window_days: float = 30.0) -> dict[str, Any]:
    if not runs:
        return {
            "window_runs": 0,
            "deploy_frequency_per_day": 0.0,
            "change_failure_rate": 0.0,
            "lead_time_hours": None,
            "mttr_hours": None,
            "bands": {},
            "summary": "DORA: insufficient run history.",
        }

    deploys = [r for r in runs if str(getattr(r, "status", "")) in SUCCESS_STATUSES]
    failures = [r for r in runs if str(getattr(r, "status", "")) in FAILURE_STATUSES]
    deploy_freq = len(deploys) / max(window_days, 1.0)
    cfr = len(failures) / len(runs) if runs else 0.0

    lead_times = [_duration_hours(r) for r in deploys]
    lead_times = [t for t in lead_times if t is not None]
    lead_time = round(sum(lead_times) / len(lead_times), 2) if lead_times else None

    recovery = [_duration_hours(r) for r in failures]
    recovery = [t for t in recovery if t is not None]
    mttr = round(sum(recovery) / len(recovery), 2) if recovery else None

    bands = {
        "deploy_frequency": _dora_band("deploy_frequency_per_day", deploy_freq),
        "change_failure_rate": _dora_band("change_failure_rate", cfr, lower_is_better=True)
        if cfr > 0
        else "elite",
        "lead_time": _dora_band("lead_time_hours", lead_time or 9999.0, lower_is_better=True)
        if lead_time is not None
        else "unknown",
        "mttr": _dora_band("mttr_hours", mttr or 9999.0, lower_is_better=True) if mttr is not None else "unknown",
    }

    return {
        "window_runs": len(runs),
        "deploy_frequency_per_day": round(deploy_freq, 3),
        "change_failure_rate": round(cfr, 3),
        "lead_time_hours": lead_time,
        "mttr_hours": mttr,
        "bands": bands,
        "summary": (
            f"DORA: deploy {deploy_freq:.2f}/day ({bands['deploy_frequency']}), "
            f"CFR {cfr:.1%} ({bands['change_failure_rate']}), "
            f"lead {lead_time or '—'}h."
        ),
    }


def predict_release_failure(
    *,
    artifacts: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    dora: dict[str, Any] | None = None,
) -> dict[str, Any]:
    change_risk = artifacts.get("change_risk_report") or {}
    fusion = fuse_stage_results(
        code=artifacts.get("code_analysis"),
        security=artifacts.get("security_scan"),
        qa=artifacts.get("qa_report"),
        stress=artifacts.get("stress_report"),
    )
    error_budget = artifacts.get("error_budget_report") or {}

    base = float(change_risk.get("final_risk") or fusion.get("risk_score") or 0)
    probability = min(100.0, base * 0.55 + float(fusion.get("risk_score") or 0) * 0.35)

    if fusion.get("verdict") == "fail":
        probability = min(100.0, probability + 20)
    elif fusion.get("verdict") == "warn":
        probability = min(100.0, probability + 8)

    if error_budget.get("freeze_risky_releases"):
        probability = min(100.0, probability + 15)

    dora = dora or {}
    cfr = float(dora.get("change_failure_rate") or 0)
    if cfr > 0.15:
        probability = min(100.0, probability + 10)

    threshold = float(policy.get("prediction_block_threshold") or 70)
    recommendation = "proceed"
    if probability >= threshold:
        recommendation = "block"
    elif probability >= threshold * 0.7:
        recommendation = "canary_only"

    return {
        "failure_probability_percent": round(probability, 1),
        "threshold_percent": threshold,
        "recommendation": recommendation,
        "signals": {
            "change_risk": change_risk.get("final_risk"),
            "gate_fusion_risk": fusion.get("risk_score"),
            "gate_verdict": fusion.get("verdict"),
            "error_budget_frozen": bool(error_budget.get("freeze_risky_releases")),
            "historical_cfr": cfr,
        },
        "summary": f"Release failure probability {probability:.0f}% — {recommendation}.",
    }


def evaluate_promotion_readiness(
    *,
    passport: dict[str, Any],
    policy: dict[str, Any],
    prediction: dict[str, Any],
    environment: str,
) -> dict[str, Any]:
    path = policy.get("promotion_path") or []
    env = (environment or "staging").lower()
    stages: dict[str, dict[str, Any]] = {}
    risk = float((passport.get("risk") or {}).get("final_score") or 0)
    max_risk = float(policy.get("max_risk_score") or 60)

    for stage in path:
        ready = passport.get("all_checks_passed", False) and risk <= max_risk
        if stage in {"canary", "production"}:
            ready = ready and prediction.get("recommendation") != "block"
        if stage == "production":
            ready = ready and prediction.get("recommendation") == "proceed"
        stages[stage] = {
            "ready": ready,
            "current": stage == env,
            "blockers": [] if ready else _promotion_blockers(passport, policy, prediction, stage),
        }

    next_stage = None
    for stage in path:
        if not stages[stage]["ready"]:
            next_stage = stage
            break
    if next_stage is None and path:
        next_stage = path[-1]

    return {
        "environment": env,
        "promotion_path": path,
        "stages": stages,
        "next_recommended_stage": next_stage,
        "summary": f"Promotion readiness: next target '{next_stage}' for {env}.",
    }


def _promotion_blockers(
    passport: dict[str, Any],
    policy: dict[str, Any],
    prediction: dict[str, Any],
    stage: str,
) -> list[str]:
    blockers: list[str] = []
    if policy.get("require_passport_pass") and not passport.get("all_checks_passed"):
        blockers.append("release passport incomplete")
    risk = float((passport.get("risk") or {}).get("final_score") or 0)
    max_risk = float(policy.get("max_risk_score") or 60)
    if risk > max_risk:
        blockers.append(f"risk {risk:.0f} exceeds max {max_risk:.0f}")
    if prediction.get("recommendation") == "block":
        blockers.append("release prediction recommends block")
    if stage == "production" and prediction.get("recommendation") != "proceed":
        blockers.append("production requires proceed recommendation")
    return blockers


def evaluate_release_gates(
    *,
    passport: dict[str, Any],
    policy: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, Any]:
    violations: list[str] = []
    if policy.get("require_passport_pass") and not passport.get("all_checks_passed"):
        violations.append("release passport checks not all passed")
    risk = float((passport.get("risk") or {}).get("final_score") or 0)
    max_risk = float(policy.get("max_risk_score") or 60)
    if risk > max_risk:
        violations.append(f"change risk {risk:.0f} exceeds policy max {max_risk:.0f}")
    if prediction.get("recommendation") == "block":
        violations.append(
            f"failure probability {prediction.get('failure_probability_percent')}% "
            f"≥ threshold {prediction.get('threshold_percent')}%"
        )

    if violations and settings.release_intelligence_gate_enabled:
        gate = "fail"
    elif violations:
        gate = "warn"
    else:
        gate = "pass"
    return {"gate_verdict": gate, "violations": violations}


def build_release_intelligence_report(
    *,
    run_id: str = "",
    repo: str = "",
    branch: str = "",
    commit: str = "",
    environment: str = "staging",
    deploy_mode: str = "auto",
    artifacts: dict[str, dict[str, Any]] | None = None,
    fleet_runs: list[Any] | None = None,
) -> dict[str, Any]:
    artifacts = artifacts or {}
    policy = resolve_release_policy(repo)

    passport = artifacts.get("release_passport")
    if not passport:
        passport = build_release_passport(
            run_id=run_id,
            repo=repo,
            branch=branch,
            commit=commit,
            artifacts=artifacts,
            deploy_mode=deploy_mode,
            environment=environment,
        )

    repo_runs = fleet_runs or []
    if repo and fleet_runs:
        repo_runs = [r for r in fleet_runs if getattr(r, "repo_full_name", None) == repo] or fleet_runs

    dora = compute_dora_metrics(repo_runs)
    slo = compute_pipeline_slo(repo_runs)
    error_budget = artifacts.get("error_budget_report") or compute_error_budget(slo)
    prediction = predict_release_failure(artifacts={**artifacts, "error_budget_report": error_budget}, policy=policy, dora=dora)
    promotion = evaluate_promotion_readiness(
        passport=passport,
        policy=policy,
        prediction=prediction,
        environment=environment,
    )
    gates = evaluate_release_gates(passport=passport, policy=policy, prediction=prediction)

    fusion = fuse_stage_results(
        code=artifacts.get("code_analysis"),
        security=artifacts.get("security_scan"),
        qa=artifacts.get("qa_report"),
        stress=artifacts.get("stress_report"),
    )

    report: dict[str, Any] = {
        "run_id": run_id,
        "repository": repo,
        "branch": branch,
        "commit": commit,
        "environment": environment,
        "deploy_mode": deploy_mode,
        "release_passport": passport,
        "policy": policy,
        "dora": dora,
        "slo": slo,
        "error_budget": error_budget,
        "gate_fusion": fusion,
        "release_prediction": prediction,
        "promotion": promotion,
        "gates": gates,
        "gate_verdict": gates["gate_verdict"],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "analysis_mode": "heuristic",
    }
    report["summary"] = (
        f"Release intel {gates['gate_verdict']}: passport "
        f"{'PASS' if passport.get('all_checks_passed') else 'WARN'}, "
        f"prediction {prediction.get('failure_probability_percent')}%, "
        f"DORA CFR {dora.get('change_failure_rate', 0):.1%}."
    )
    return report
