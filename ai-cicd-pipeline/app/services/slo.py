"""Pipeline SLO rollups from recent runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SUCCESS_STATUSES = frozenset({"deployed", "approved", "monitoring"})
BLOCKED_STATUSES = frozenset(
    {
        "blocked_code",
        "blocked_security",
        "blocked_tests",
        "blocked_stress",
        "blocked_secrets",
        "blocked_policy",
        "blocked_injection",
        "blocked_agent_eval",
        "blocked_with_prs_sent",
        "rejected",
    }
)


def compute_pipeline_slo(runs: list[Any]) -> dict[str, Any]:
    total = len(runs)
    if total == 0:
        return {
            "window_runs": 0,
            "success_rate": 0.0,
            "blocked_rate": 0.0,
            "failure_rate": 0.0,
            "mean_duration_seconds": None,
        }

    success = 0
    blocked = 0
    failed = 0
    durations: list[float] = []

    for run in runs:
        status = str(getattr(run, "status", None) or (run.get("status") if isinstance(run, dict) else ""))
        if status in SUCCESS_STATUSES:
            success += 1
        elif status in BLOCKED_STATUSES:
            blocked += 1
        elif status in {"failed", "rolled_back", "auto_rolled_back", "cancelled"}:
            failed += 1

        created = getattr(run, "created_at", None)
        if created is None and isinstance(run, dict):
            created = run.get("created_at")
        completed = getattr(run, "completed_at", None)
        if completed is None and isinstance(run, dict):
            completed = run.get("completed_at")
        if created and completed:
            try:
                if isinstance(created, str):
                    created = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if isinstance(completed, str):
                    completed = datetime.fromisoformat(completed.replace("Z", "+00:00"))
                durations.append(max(0.0, (completed - created).total_seconds()))
            except (TypeError, ValueError):
                pass

    mean_duration = round(sum(durations) / len(durations), 1) if durations else None
    return {
        "window_runs": total,
        "success_rate": round(success / total, 3),
        "blocked_rate": round(blocked / total, 3),
        "failure_rate": round(failed / total, 3),
        "mean_duration_seconds": mean_duration,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
