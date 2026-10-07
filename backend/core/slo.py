"""Pipeline SLO rollups — shared with ORION intelligence dashboards."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SUCCESS_STATUSES = frozenset({"deployed", "approved", "monitoring", "completed", "COMPLETED"})
BLOCKED_STATUSES = frozenset(
    {
        "blocked_code",
        "blocked_security",
        "blocked_tests",
        "blocked_stress",
        "blocked_with_prs_sent",
        "rejected",
        "BLOCKED",
        "blocked",
    }
)


def _run_field(run: Any, name: str) -> Any:
    if isinstance(run, dict):
        return run.get(name)
    return getattr(run, name, None)


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
        status = str(_run_field(run, "status") or "")
        if status in SUCCESS_STATUSES:
            success += 1
        elif status in BLOCKED_STATUSES or status.startswith("blocked"):
            blocked += 1
        elif status in {"failed", "rolled_back", "auto_rolled_back", "cancelled", "FAILED"}:
            failed += 1

        created = _run_field(run, "created_at")
        completed = _run_field(run, "completed_at")
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
