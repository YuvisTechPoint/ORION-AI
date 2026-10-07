"""Decision ledger — immutable-style record of gate and agent decisions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def build_decision_ledger(
    *,
    run_id: str,
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []

    def add(source: str, decision: str, confidence: float | None = None, evidence: str = "") -> None:
        decisions.append(
            {
                "id": str(uuid4())[:8],
                "source": source,
                "decision": decision,
                "confidence": confidence,
                "evidence": evidence,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )

    code = artifacts.get("code_analysis") or {}
    if code:
        add("CodeAnalysisAgent", str(code.get("severity", "unknown")), evidence=code.get("summary", ""))

    sec = artifacts.get("security_scan") or {}
    if sec:
        add(
            "SecurityAgent",
            "pass" if sec.get("passed", True) else "fail",
            evidence=str(sec.get("highest_severity")),
        )

    qa = artifacts.get("qa_report") or {}
    if qa:
        add("QAAgent", str(qa.get("verdict", "unknown")), evidence=qa.get("summary", ""))

    stress = artifacts.get("stress_report") or {}
    if stress:
        add("StressTestAgent", str(stress.get("performance_verdict", "unknown")))

    approval = artifacts.get("approval") or {}
    if approval:
        add(
            "ApprovalAgent",
            str(approval.get("decision", "unknown")),
            confidence=approval.get("confidence"),
        )

    policy = artifacts.get("policy_evaluation") or {}
    if policy:
        add("PolicyEngine", "pass" if policy.get("passed") else "blocked", evidence=policy.get("summary", ""))

    agent_eval = artifacts.get("agent_eval_report") or {}
    if agent_eval.get("aggregate_score") is not None:
        add(
            "AgentEval",
            "review" if agent_eval.get("human_review_required") else "accept",
            confidence=agent_eval.get("aggregate_score"),
        )

    return {
        "ledger_id": f"LED-{run_id[:8]}",
        "run_id": run_id,
        "decisions": decisions,
        "decision_count": len(decisions),
        "summary": f"Decision ledger: {len(decisions)} recorded decision(s).",
    }
