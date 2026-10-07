"""AI governance intelligence — unified eval, routing, ledger, cost, and escalation rollup."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.utils.ai_cost_optimizer import optimize_ai_cost
from app.utils.ai_governance_registry import build_governance_policy_catalog
from app.utils.agent_eval import evaluate_agents
from app.utils.decision_ledger import build_decision_ledger
from app.utils.model_router import build_model_routing_plan
from app.utils.prompt_registry import build_prompt_registry_snapshot


def _confidence_signals(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    approval = artifacts.get("approval") or {}
    if approval.get("confidence") is not None:
        signals.append(
            {
                "source": "approval",
                "confidence": float(approval["confidence"]),
                "decision": approval.get("decision"),
            }
        )
    patch = artifacts.get("patch_confidence_report") or {}
    if patch.get("confidence") is not None:
        signals.append(
            {
                "source": "patch_confidence",
                "confidence": float(patch["confidence"]),
                "decision": patch.get("recommendation"),
            }
        )
    eval_report = artifacts.get("agent_eval_report") or {}
    if eval_report.get("aggregate_score") is not None:
        signals.append(
            {
                "source": "agent_eval",
                "confidence": float(eval_report["aggregate_score"]),
                "decision": "review" if eval_report.get("human_review_required") else "accept",
            }
        )
    return signals


def _fallback_stats(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    modes: dict[str, int] = {}
    llm_errors = 0
    for key, content in artifacts.items():
        if not isinstance(content, dict):
            continue
        mode = str(content.get("analysis_mode") or "")
        if mode:
            modes[mode] = modes.get(mode, 0) + 1
        if content.get("_llm_error"):
            llm_errors += 1
    heuristic = modes.get("heuristic", 0)
    llm = modes.get("llm", 0)
    total = heuristic + llm + modes.get("simulated", 0)
    return {
        "analysis_modes": modes,
        "llm_error_count": llm_errors,
        "heuristic_fallback_count": heuristic,
        "llm_count": llm,
        "fallback_rate": round(heuristic / total, 2) if total else 0.0,
    }


def _token_rollup(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_artifact: list[dict[str, Any]] = []
    total = 0
    for key, content in artifacts.items():
        if not isinstance(content, dict):
            continue
        tokens = int(content.get("tokens_used") or 0)
        if tokens:
            by_artifact.append({"artifact": key, "tokens": tokens})
            total += tokens
    cost_report = artifacts.get("cost_report") or {}
    llm_usd = float((cost_report.get("breakdown") or {}).get("llm_usd") or 0)
    if not llm_usd and total:
        llm_usd = round(total / 1000 * settings.finops_llm_cost_per_1k_tokens, 4)
    return {
        "total_tokens": total,
        "by_artifact": sorted(by_artifact, key=lambda x: x["tokens"], reverse=True)[:8],
        "estimated_llm_usd": llm_usd,
    }


def build_escalation_queue(
    artifacts: dict[str, dict[str, Any]],
    *,
    policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    policy = policy or build_governance_policy_catalog()
    threshold = float(policy.get("escalation_threshold", settings.ai_governance_escalation_threshold))
    min_conf = float(policy.get("min_confidence", settings.ai_governance_min_confidence))
    queue: list[dict[str, Any]] = []

    eval_report = artifacts.get("agent_eval_report") or evaluate_agents(
        artifacts, min_score=settings.agent_eval_min_score
    )
    if eval_report.get("human_review_required"):
        queue.append(
            {
                "code": "agent_eval_low",
                "severity": "high",
                "reason": eval_report.get("summary"),
                "artifacts": eval_report.get("low_scoring_artifacts", []),
                "action": "human_review",
            }
        )

    approval = artifacts.get("approval") or {}
    conf = approval.get("confidence")
    if conf is not None and float(conf) < threshold:
        queue.append(
            {
                "code": "approval_low_confidence",
                "severity": "high",
                "reason": f"Approval confidence {conf} below {threshold}",
                "action": "human_review",
            }
        )

    risk = artifacts.get("change_risk_report") or {}
    final_risk = int(risk.get("final_risk") or 0)
    if final_risk >= settings.approval_high_risk_threshold:
        queue.append(
            {
                "code": "high_change_risk",
                "severity": "high",
                "reason": f"Change risk {final_risk} exceeds threshold",
                "action": "approver_required",
            }
        )

    injection = artifacts.get("prompt_injection_scan") or {}
    if injection.get("blocked"):
        queue.append(
            {
                "code": "prompt_injection",
                "severity": "critical",
                "reason": injection.get("summary", "Prompt injection detected"),
                "action": "block_pipeline",
            }
        )

    fallback = _fallback_stats(artifacts)
    if fallback["llm_error_count"] >= 2:
        queue.append(
            {
                "code": "llm_errors",
                "severity": "medium",
                "reason": f"{fallback['llm_error_count']} LLM error(s) in artifacts",
                "action": "monitor",
            }
        )

    signals = _confidence_signals(artifacts)
    min_signal = min((s["confidence"] for s in signals), default=1.0)
    if signals and min_signal < min_conf:
        queue.append(
            {
                "code": "aggregate_low_confidence",
                "severity": "medium",
                "reason": f"Minimum confidence signal {min_signal} below {min_conf}",
                "action": "human_review",
            }
        )

    return queue


def evaluate_governance_gates(
    *,
    escalations: list[dict[str, Any]],
    governance_score: float,
) -> dict[str, Any]:
    violations: list[str] = []
    critical = [e for e in escalations if e.get("severity") == "critical"]
    high = [e for e in escalations if e.get("severity") == "high"]
    if critical:
        violations.extend(e.get("reason", e.get("code", "")) for e in critical)
    if high:
        violations.extend(e.get("reason", e.get("code", "")) for e in high[:2])
    if governance_score < settings.ai_governance_min_score:
        violations.append(f"governance score {governance_score} below {settings.ai_governance_min_score}")

    if violations and settings.ai_governance_gate_enabled:
        gate = "fail"
    elif violations:
        gate = "warn"
    else:
        gate = "pass"
    return {"gate_verdict": gate, "violations": violations[:10]}


def _governance_score(
    *,
    agent_eval: dict[str, Any],
    fallback: dict[str, Any],
    escalations: list[dict[str, Any]],
    controls_present: int,
) -> float:
    base = float(agent_eval.get("aggregate_score") or 0.75)
    penalty = 0.08 * len(escalations) + 0.05 * fallback.get("llm_error_count", 0)
    bonus = 0.02 * controls_present
    return round(max(0.0, min(1.0, base - penalty + bonus)), 2)


def build_ai_governance_intelligence_report(
    *,
    artifacts: dict[str, dict[str, Any]],
    run_id: str = "",
    agent_names: list[str] | None = None,
) -> dict[str, Any]:
    policy = build_governance_policy_catalog()
    agent_eval = artifacts.get("agent_eval_report") or evaluate_agents(
        artifacts, min_score=settings.agent_eval_min_score
    )
    routing = artifacts.get("model_routing_plan") or build_model_routing_plan(artifacts)
    prompts = artifacts.get("prompt_registry_snapshot") or build_prompt_registry_snapshot(agents=agent_names)
    ledger = artifacts.get("decision_ledger") or build_decision_ledger(run_id=run_id or "local", artifacts=artifacts)
    cost_opt = artifacts.get("ai_cost_optimization") or optimize_ai_cost(
        cost_report=artifacts.get("cost_report"),
        model_plan=routing,
        artifacts=artifacts,
    )
    fallback = _fallback_stats(artifacts)
    tokens = _token_rollup(artifacts)
    escalations = build_escalation_queue(artifacts, policy=policy)
    controls_present = sum(1 for c in policy["controls"] if artifacts.get(c["artifact"]))
    governance_score = _governance_score(
        agent_eval=agent_eval,
        fallback=fallback,
        escalations=escalations,
        controls_present=controls_present,
    )
    gates = evaluate_governance_gates(escalations=escalations, governance_score=governance_score)

    human_review_required = bool(escalations) or agent_eval.get("human_review_required", False)

    report: dict[str, Any] = {
        "policy": policy,
        "agent_eval": agent_eval,
        "model_routing": routing,
        "prompt_registry": prompts,
        "decision_ledger": ledger,
        "cost_optimization": cost_opt,
        "fallback_stats": fallback,
        "token_rollup": tokens,
        "confidence_signals": _confidence_signals(artifacts),
        "escalations": escalations,
        "escalation_count": len(escalations),
        "human_review_required": human_review_required,
        "governance_score": governance_score,
        "gates": gates,
        "gate_verdict": gates["gate_verdict"],
        "controls_present": controls_present,
        "controls_total": len(policy["controls"]),
        "analysis_mode": "heuristic",
    }
    report["summary"] = (
        f"AI governance {gates['gate_verdict']}: score {governance_score}, "
        f"{len(escalations)} escalation(s), human_review={human_review_required}."
    )
    return report
