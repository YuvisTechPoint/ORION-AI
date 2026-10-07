"""Persist multi-layer code review intelligence after scan + change-risk stages."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.events import publish_event
from app.utils.artifact_summaries import summarize_artifact
from app.utils.code_review_intelligence import build_code_review_intelligence_report


async def persist_code_review_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("code_review_intelligence"):
        return artifacts["code_review_intelligence"]

    metadata = artifacts.get("metadata") or {}
    changed_files = metadata.get("changed_files") if isinstance(metadata.get("changed_files"), list) else []

    report = build_code_review_intelligence_report(
        code_analysis=artifacts.get("code_analysis"),
        security_scan=artifacts.get("security_scan"),
        qa_report=artifacts.get("qa_report"),
        service_graph=artifacts.get("service_graph"),
        repository_intelligence=artifacts.get("repository_intelligence"),
        change_risk_report=artifacts.get("change_risk_report"),
        stress_report=artifacts.get("stress_report"),
        performance_intelligence=artifacts.get("performance_intelligence"),
        changed_files=changed_files,
    )
    report["summary"] = summarize_artifact("code_review_intelligence", report)

    db.add(
        PipelineArtifact(
            pipeline_run_id=run.id,
            artifact_type="code_review_intelligence",
            content=report,
        )
    )
    await db.commit()
    publish_event(
        run.id,
        {
            "kind": "artifact",
            "artifact_type": "code_review_intelligence",
            "agent": "code_review_intelligence",
            "summary": report["summary"],
        },
    )
    return report
