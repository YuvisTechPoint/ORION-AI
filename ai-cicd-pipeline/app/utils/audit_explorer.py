"""Cross-run audit trail search and aggregation."""

from __future__ import annotations

from typing import Any


def explore_audit_events(
    runs: list[Any],
    audit_by_run: dict[str, list[dict[str, Any]]],
    *,
    repo_filter: str | None = None,
    action_filter: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for run in runs:
        repo = str(getattr(run, "repo_full_name", "") or "")
        if repo_filter and repo_filter.lower() not in repo.lower():
            continue
        run_id = str(getattr(run, "id", ""))
        for event in audit_by_run.get(run_id, []):
            if action_filter and action_filter not in str(event.get("action", "")):
                continue
            events.append(
                {
                    **event,
                    "pipeline_run_id": run_id,
                    "repository": repo,
                    "run_status": str(getattr(run, "status", "")),
                }
            )

    events.sort(key=lambda e: str(e.get("ts") or ""), reverse=True)
    events = events[:limit]

    actors: dict[str, int] = {}
    actions: dict[str, int] = {}
    for event in events:
        actor = str(event.get("actor") or "unknown")
        action = str(event.get("action") or "unknown")
        actors[actor] = actors.get(actor, 0) + 1
        actions[action] = actions.get(action, 0) + 1

    return {
        "events": events,
        "total": len(events),
        "top_actors": sorted(actors.items(), key=lambda x: x[1], reverse=True)[:5],
        "top_actions": sorted(actions.items(), key=lambda x: x[1], reverse=True)[:8],
        "filters": {"repo": repo_filter, "action": action_filter},
        "summary": f"Audit explorer: {len(events)} event(s) across {len({e.get('repository') for e in events})} repo(s).",
    }
