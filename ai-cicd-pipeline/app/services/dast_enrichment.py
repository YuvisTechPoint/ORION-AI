"""Persist DAST report after stress testing (staging target)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.events import publish_event
from app.utils.artifact_summaries import summarize_artifact
from app.utils.dast_scan import build_dast_report, evaluate_dast_gates


async def persist_dast_report(
    db: AsyncSession,
    run: PipelineRun,
    *,
    target_url: str | None = None,
    skip_if_present: bool = False,
    existing: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if skip_if_present and (existing or {}).get("dast_report"):
        return existing["dast_report"]  # type: ignore[index]

    report = build_dast_report(target_url)
    report["gates"] = evaluate_dast_gates(report)
    report["gate_verdict"] = report["gates"]["gate_verdict"]
    report["summary"] = summarize_artifact("dast_report", report)

    db.add(
        PipelineArtifact(
            pipeline_run_id=run.id,
            artifact_type="dast_report",
            content=report,
        )
    )
    await db.commit()
    publish_event(
        run.id,
        {
            "kind": "artifact",
            "artifact_type": "dast_report",
            "agent": "dast_scan",
            "summary": report["summary"],
        },
    )
    return report
