"""Persist ORION Unified Risk intelligence artifacts."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.artifact_summaries import summarize_artifact
from app.utils.unified_risk_intelligence import build_unified_risk_intelligence_report


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def persist_unified_risk_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    environment: str = "",
    diff_text: str = "",
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("unified_risk_intelligence"):
        return artifacts["unified_risk_intelligence"]

    metadata = artifacts.get("metadata") or {}
    report = build_unified_risk_intelligence_report(
        run_id=str(run.id),
        repo=run.repo_full_name,
        branch=run.branch,
        commit=run.commit_id,
        run_status=str(run.status),
        environment=environment,
        artifacts=artifacts,
        diff_text=diff_text,
        changed_files=metadata.get("changed_files"),
    )
    report["summary"] = summarize_artifact("unified_risk_intelligence", report)
    await _save(db, run.id, "unified_risk_intelligence", report)
    await db.commit()
    return report
