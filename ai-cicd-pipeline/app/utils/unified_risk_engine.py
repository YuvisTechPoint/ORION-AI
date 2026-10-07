"""ORION Unified Risk Engine — fuse change risk, gates, and intelligence signals."""

from __future__ import annotations

from typing import Any

from app.utils.change_risk import compute_change_risk
from app.utils.gate_fusion import fuse_stage_results
from app.utils.release_intelligence import predict_release_failure
from app.utils.release_intelligence_registry import resolve_release_policy
from app.utils.unified_risk_registry import resolve_unified_risk_policy


def _clamp(value: float | int, lo: int = 0, hi: int = 100) -> int:
    return int(max(lo, min(hi, round(float(value)))))


def _gate_verdict_score(verdict: str | None) -> int:
    level = str(verdict or "pass").lower()
    if level == "fail":
        return 90
    if level == "warn":
        return 48
    return 12


def _readiness_score(artifact: dict[str, Any] | None, *, gate_key: str = "gate_verdict") -> int:
    if not artifact:
        return 0
    for key in ("readiness_score", "resilience_score", "governance_score", "coverage_percent"):
        nested = artifact.get("coverage") if key == "coverage_percent" else None
        raw = nested.get(key) if isinstance(nested, dict) else artifact.get(key)
        if isinstance(raw, (int, float)):
            return _clamp(raw)
    return _gate_verdict_score(artifact.get(gate_key))


def _supply_chain_score(artifacts: dict[str, dict[str, Any]]) -> int:
    score = 0
    secrets = artifacts.get("secrets_scan") or {}
    if secrets.get("blocked") or secrets.get("critical_count", 0):
        score = max(score, 95)
    elif secrets.get("finding_count", 0):
        score = max(score, _clamp(int(secrets.get("finding_count", 0)) * 8))

    container = artifacts.get("container_security_scan") or {}
    if str(container.get("highest_severity", "")).lower() in {"critical", "high"}:
        score = max(score, 80)
    elif container.get("finding_count"):
        score = max(score, 45)

    iac = artifacts.get("iac_security_scan") or {}
    if str(iac.get("highest_severity", "")).lower() in {"critical", "high"}:
        score = max(score, 75)
    elif iac.get("finding_count"):
        score = max(score, 40)

    policy_eval = artifacts.get("policy_evaluation") or {}
    if policy_eval.get("verdict") == "fail":
        score = max(score, 88)
    return score


def _operational_readiness_score(artifacts: dict[str, dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    sources = [
        ("iam", "iam_intelligence"),
        ("reliability", "reliability_intelligence"),
        ("dr", "dr_intelligence"),
        ("finops", "finops_intelligence"),
        ("release", "release_intelligence"),
    ]
    contributors: list[dict[str, Any]] = []
    scores: list[int] = []
    for label, key in sources:
        art = artifacts.get(key) or {}
        if not art:
            continue
        value = _readiness_score(art)
        scores.append(value)
        contributors.append({"source": label, "artifact": key, "score": value, "gate_verdict": art.get("gate_verdict")})
    if not scores:
        return 0, contributors
    return _clamp(sum(scores) / len(scores)), contributors


def _governance_score(artifacts: dict[str, dict[str, Any]]) -> int:
    parts: list[int] = []
    for key in ("ai_governance_intelligence", "policy_intelligence", "policy_evaluation"):
        art = artifacts.get(key) or {}
        if not art:
            continue
        parts.append(_readiness_score(art, gate_key="gate_verdict" if key != "policy_evaluation" else "verdict"))
    if not parts:
        return 0
    return _clamp(max(parts))


def _risk_level(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def compute_unified_risk(
    *,
    artifacts: dict[str, dict[str, Any]] | None = None,
    repo: str = "",
    environment: str = "",
    diff_text: str = "",
    changed_files: list[str] | None = None,
) -> dict[str, Any]:
    """Fuse pipeline artifacts into a single ORION unified risk score (0–100)."""
    artifacts = artifacts or {}
    policy = resolve_unified_risk_policy(repo, environment)
    weights = policy["dimension_weights"]

    code = artifacts.get("code_analysis") or {}
    security = artifacts.get("security_scan") or {}
    qa = artifacts.get("qa_report") or {}
    stress = artifacts.get("stress_report") or {}

    fusion = fuse_stage_results(code=code, security=security, qa=qa, stress=stress)
    gate_score = _clamp(fusion.get("risk_score") or 0)

    change_report = artifacts.get("change_risk_report")
    if not change_report:
        metadata = artifacts.get("metadata") or {}
        files = changed_files or metadata.get("changed_files") or []
        change_report = compute_change_risk(
            diff_text=diff_text,
            changed_files=list(files) if files else None,
            code=code,
            security=security,
            qa=qa,
            stress=stress,
            gate_fusion=fusion,
        )
    change_score = _clamp(change_report.get("final_risk") or 0)

    release_policy = resolve_release_policy(repo)
    prediction = predict_release_failure(artifacts={**artifacts, "change_risk_report": change_report}, policy=release_policy)
    release_score = _clamp(prediction.get("failure_probability_percent") or 0)

    operational_score, operational_contributors = _operational_readiness_score(artifacts)
    knowledge_art = artifacts.get("knowledge_graph_intelligence") or {}
    knowledge_score = _readiness_score(knowledge_art)
    if knowledge_score == 0 and knowledge_art:
        graph = knowledge_art.get("graph") or {}
        if graph.get("node_count"):
            knowledge_score = _clamp(min(100, int(graph.get("node_count", 0)) * 3))

    governance_score = _governance_score(artifacts)
    supply_score = _supply_chain_score(artifacts)

    dimensions = {
        "change_risk": change_score,
        "quality_gates": gate_score,
        "release_prediction": release_score,
        "operational_readiness": operational_score,
        "governance_compliance": governance_score,
        "supply_chain": supply_score,
        "knowledge_coverage": knowledge_score,
    }

    weighted = sum(dimensions[k] * weights.get(k, 0) for k in dimensions)
    intelligence_gates = [
        ("autopilot", artifacts.get("autopilot_intelligence")),
        ("knowledge", knowledge_art),
        ("release", artifacts.get("release_intelligence")),
    ]
    gate_penalty = 0
    for label, art in intelligence_gates:
        if art and str(art.get("gate_verdict", "")).lower() == "fail":
            gate_penalty += 8
            operational_contributors.append(
                {"source": label, "artifact": f"{label}_gate", "score": 90, "gate_verdict": "fail"}
            )

    unified_score = _clamp(weighted + gate_penalty)
    unified_score = max(unified_score, gate_score // 2, change_score // 3)

    contributors = sorted(
        [
            {"dimension": key, "score": value, "weight": weights.get(key, 0), "weighted": round(value * weights.get(key, 0), 1)}
            for key, value in dimensions.items()
            if value > 0
        ],
        key=lambda item: item["weighted"],
        reverse=True,
    )

    level = _risk_level(unified_score)
    recommendations: list[str] = []
    if fusion.get("verdict") == "fail":
        recommendations.append("quality gate fusion failed — block deployment")
    if level in {"high", "critical"}:
        recommendations.append("staged rollout or manual approval required")
    if release_score >= 70:
        recommendations.append("release failure probability elevated — prefer canary")
    if supply_score >= 70:
        recommendations.append("remediate supply-chain findings before promote")
    if prediction.get("recommendation") == "block":
        recommendations.append("release intelligence recommends blocking promotion")

    return {
        "unified_score": unified_score,
        "risk_level": level,
        "dimensions": dimensions,
        "dimension_weights": weights,
        "top_contributors": contributors[:6],
        "operational_contributors": operational_contributors[:8],
        "change_risk_report": {
            "final_risk": change_score,
            "risk_level": change_report.get("risk_level"),
            "dimensions": change_report.get("dimensions"),
        },
        "gate_fusion": {
            "verdict": fusion.get("verdict"),
            "risk_score": gate_score,
            "violations": (fusion.get("violations") or [])[:6],
            "warnings": (fusion.get("warnings") or [])[:6],
        },
        "release_prediction": prediction,
        "recommendations": list(dict.fromkeys(recommendations))[:8],
        "policy": {
            "max_unified_score": policy["max_unified_score"],
            "block_on_high": policy["block_on_high"],
            "require_gate_fusion_pass": policy["require_gate_fusion_pass"],
        },
    }
