"""AgentEval — heuristic quality scoring for pipeline agent outputs."""

from __future__ import annotations

from typing import Any


def _score_artifact(name: str, content: dict[str, Any]) -> dict[str, Any]:
    mode = str(content.get("analysis_mode") or "unknown")
    has_summary = bool(content.get("summary") or content.get("reasoning"))
    llm_error = content.get("_llm_error")

    groundedness = 0.85 if has_summary and not llm_error else 0.55
    consistency = 0.9 if mode in {"heuristic", "llm"} and not llm_error else 0.5
    safety = 0.95 if name != "code_analysis" or content.get("severity") != "fail" else 0.7

    if llm_error:
        groundedness = 0.4
        consistency = 0.45

    overall = round((groundedness + consistency + safety) / 3, 2)
    return {
        "artifact": name,
        "groundedness": groundedness,
        "consistency": consistency,
        "safety": safety,
        "overall": overall,
        "analysis_mode": mode,
    }


def evaluate_agents(artifacts: dict[str, dict[str, Any]], *, min_score: float = 0.6) -> dict[str, Any]:
    targets = [
        "code_analysis",
        "security_scan",
        "qa_report",
        "approval",
        "stress_report",
        "change_risk_report",
    ]
    scores = [_score_artifact(k, artifacts[k]) for k in targets if k in artifacts]
    if not scores:
        return {
            "scores": [],
            "aggregate_score": None,
            "human_review_required": False,
            "summary": "AgentEval: no agent artifacts to score.",
        }

    aggregate = round(sum(s["overall"] for s in scores) / len(scores), 2)
    low = [s for s in scores if s["overall"] < min_score]
    return {
        "scores": scores,
        "aggregate_score": aggregate,
        "human_review_required": aggregate < min_score or len(low) > 0,
        "low_scoring_artifacts": [s["artifact"] for s in low],
        "min_score_threshold": min_score,
        "summary": f"AgentEval aggregate {aggregate} — {'review required' if aggregate < min_score else 'acceptable'}.",
    }
