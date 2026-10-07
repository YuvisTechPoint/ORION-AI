"""Pipeline SLO rollups for devops-platform."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SUCCESS_STATUSES = frozenset({"COMPLETED", "completed", "deployed"})
BLOCKED_STATUSES = frozenset({"BLOCKED", "blocked"})


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

    success = blocked = failed = 0
    durations: list[float] = []

    for run in runs:
        status = str(getattr(run, "status", None) or run.get("status", ""))
        if hasattr(status, "value"):
            status = str(status.value)
        if status in SUCCESS_STATUSES:
            success += 1
        elif status in BLOCKED_STATUSES:
            blocked += 1
        elif status in {"FAILED", "failed", "cancelled"}:
            failed += 1

        created = getattr(run, "created_at", None)
        updated = getattr(run, "updated_at", None)
        if created and updated:
            try:
                durations.append(max(0.0, (updated - created).total_seconds()))
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
