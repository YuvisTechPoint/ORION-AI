"""Persist remediation intelligence after fix loop or pipeline block."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.artifact_summaries import summarize_artifact
from app.utils.remediation_intelligence import build_remediation_intelligence_report


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def persist_remediation_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    fix_loop_report: dict[str, Any] | None = None,
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("remediation_intelligence"):
        return artifacts["remediation_intelligence"]

    run_dict = {
        "id": str(run.id),
        "status": run.status,
        "error_message": run.error_message,
        "repo_full_name": run.repo_full_name,
        "branch": run.branch,
        "commit_id": run.commit_id,
    }
    report = build_remediation_intelligence_report(
        run=run_dict,
        artifacts=artifacts,
        fix_loop_report=fix_loop_report,
    )
    report["summary"] = summarize_artifact("remediation_intelligence", report)
    await _save(db, run.id, "remediation_intelligence", report)
    await db.commit()
    return report
