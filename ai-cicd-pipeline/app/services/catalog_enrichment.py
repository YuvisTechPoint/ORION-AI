"""Persist service catalog artifacts on pipeline runs."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.artifact_summaries import summarize_artifact
from app.utils.service_catalog import build_service_catalog
from app.utils.service_catalog_intelligence import build_service_catalog_intelligence_report


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def persist_service_catalog(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    repo_path: str | None = None,
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("service_catalog"):
        return artifacts["service_catalog"]

    catalog = build_service_catalog(
        repo=run.repo_full_name,
        repo_path=repo_path,
        service_graph=artifacts.get("service_graph"),
        repository_intelligence=artifacts.get("repository_intelligence"),
        cloud_intelligence=artifacts.get("cloud_intelligence"),
    )
    catalog["summary"] = summarize_artifact("service_catalog", catalog)
    await _save(db, run.id, "service_catalog", catalog)
    await db.commit()
    return catalog


async def persist_service_catalog_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    repo_path: str | None = None,
    fleet_runs: list[PipelineRun] | None = None,
    fleet_artifacts: dict[str, dict[str, dict[str, Any]]] | None = None,
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("service_catalog_intelligence"):
        return artifacts["service_catalog_intelligence"]

    report = build_service_catalog_intelligence_report(
        repo=run.repo_full_name,
        repo_path=repo_path,
        artifacts=artifacts,
        fleet_runs=fleet_runs,
        fleet_artifacts=fleet_artifacts,
    )
    report["summary"] = summarize_artifact("service_catalog_intelligence", report)
    await _save(db, run.id, "service_catalog_intelligence", report)
    await db.commit()
    return report
