"""Persist cloud / Kubernetes intelligence artifacts."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.artifact_summaries import summarize_artifact
from app.utils.cloud_intelligence import build_cloud_intelligence_report


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def persist_cloud_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    repo_path: str | None = None,
    deploy_mode: str | None = None,
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("cloud_intelligence"):
        return artifacts["cloud_intelligence"]

    report = build_cloud_intelligence_report(
        repo=run.repo_full_name,
        repo_path=repo_path,
        environment=settings.deploy_environment,
        deploy_mode=deploy_mode,
        kubernetes_manifest_scan=artifacts.get("kubernetes_manifest_scan"),
        iac_security_scan=artifacts.get("iac_security_scan"),
        container_security_scan=artifacts.get("container_security_scan"),
        dockerfile_analysis=artifacts.get("dockerfile_analysis"),
        service_graph=artifacts.get("service_graph"),
        deployment_info=artifacts.get("deployment_info"),
    )
    report["summary"] = summarize_artifact("cloud_intelligence", report)
    await _save(db, run.id, "cloud_intelligence", report)
    await db.commit()
    return report
