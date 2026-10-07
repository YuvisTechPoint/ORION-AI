"""Multi-repo fleet risk aggregation."""

from __future__ import annotations

from typing import Any


def build_fleet_view(
    runs: list[Any],
    artifacts_by_run: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    repos: dict[str, dict[str, Any]] = {}

    for run in runs:
        repo = str(getattr(run, "repo_full_name", "") or "unknown/unknown")
        run_id = str(getattr(run, "id", ""))
        status = str(getattr(run, "status", ""))
        arts = artifacts_by_run.get(run_id) or {}

        change_risk = arts.get("change_risk_report") or {}
        risk_score = int(change_risk.get("final_risk") or 0)
        error_budget = arts.get("error_budget_report") or {}
        compliance = arts.get("compliance_report") or {}
        incident = arts.get("incident_commander_report") or {}

        entry = repos.setdefault(
            repo,
            {
                "repository": repo,
                "run_count": 0,
                "deployed": 0,
                "blocked": 0,
                "failed": 0,
                "max_risk": 0,
                "active_incidents": 0,
                "compliance_score": None,
                "latest_status": status,
            },
        )
        entry["run_count"] += 1
        entry["max_risk"] = max(entry["max_risk"], risk_score)
        entry["latest_status"] = status
        if status in {"deployed", "monitoring"}:
            entry["deployed"] += 1
        elif status.startswith("blocked") or status == "rejected":
            entry["blocked"] += 1
        elif status in {"failed", "rolled_back", "auto_rolled_back"}:
            entry["failed"] += 1
        if incident.get("severity") in {"P1", "P2"}:
            entry["active_incidents"] += 1
        if compliance.get("overall_score_percent") is not None:
            entry["compliance_score"] = compliance.get("overall_score_percent")

    ranked = sorted(
        repos.values(),
        key=lambda r: (r["max_risk"], r["failed"], r["blocked"]),
        reverse=True,
    )
    highest = ranked[0] if ranked else None

    return {
        "repositories": ranked,
        "repository_count": len(ranked),
        "highest_risk_repo": highest["repository"] if highest else None,
        "highest_risk_score": highest["max_risk"] if highest else 0,
        "summary": (
            f"Fleet: {len(ranked)} repo(s); highest risk {highest['repository']} ({highest['max_risk']}/100)."
            if highest
            else "Fleet: no recent pipeline runs."
        ),
    }
