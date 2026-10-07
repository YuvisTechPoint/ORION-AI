"""Runbook matching and approved remediation suggestions."""

from __future__ import annotations

import re
from typing import Any

_RUNBOOKS: list[dict[str, Any]] = [
    {
        "id": "REDIS-004",
        "signature": re.compile(r"redis|connection pool|6379", re.I),
        "title": "Redis connection exhaustion",
        "steps": [
            "Increase connection pool size in service config",
            "Restart affected service pods/containers",
            "Verify Redis latency and error rate metrics",
        ],
        "approval_required": True,
    },
    {
        "id": "DEPLOY-001",
        "signature": re.compile(r"health check failed|503|502|deployment", re.I),
        "title": "Failed deployment rollback",
        "steps": [
            "Rollback to last_known_good_image",
            "Verify /health on staging",
            "Compare error rate vs baseline",
        ],
        "approval_required": False,
    },
    {
        "id": "LATENCY-010",
        "signature": re.compile(r"latency|p95|timeout|slow", re.I),
        "title": "Latency spike investigation",
        "steps": [
            "Check recent deployment correlation",
            "Inspect slow database queries",
            "Scale replicas if CPU saturated",
        ],
        "approval_required": True,
    },
]


def match_runbooks(text: str, rca: dict[str, Any] | None = None) -> dict[str, Any]:
    haystack = text
    if rca:
        haystack += " " + str(rca.get("summary", "")) + " " + str((rca.get("primary_hypothesis") or {}).get("cause", ""))

    matched: list[dict[str, Any]] = []
    for book in _RUNBOOKS:
        if book["signature"].search(haystack):
            matched.append(
                {
                    "runbook_id": book["id"],
                    "title": book["title"],
                    "steps": book["steps"],
                    "approval_required": book["approval_required"],
                    "status": "recommended",
                }
            )

    return {
        "matched_count": len(matched),
        "runbooks": matched[:5],
        "autonomous_execution": False,
        "summary": f"Matched {len(matched)} runbook(s)." if matched else "No runbook signature matched.",
    }
