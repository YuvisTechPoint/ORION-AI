"""Developer UX API — VS Code extension catalog, GitHub App manifest, readiness."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import optional_auth
from app.database import get_db
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.developer_ux_enrichment import persist_developer_ux_intelligence
from app.services.github_app_service import github_app_status
from app.utils.developer_ux_intelligence import (
    assess_developer_ux_readiness,
    build_developer_ux_intelligence_report,
)
from app.utils.developer_ux_registry import build_developer_catalog, build_vscode_extension_manifest
from app.utils.github_app_registry import build_github_app_manifest, resolve_github_app_config

router = APIRouter(prefix="/developer", tags=["Developer UX"])


class DeveloperUxRequest(BaseModel):
    pipeline_run_id: str | None = None
    persist: bool = Field(default=True)


@router.get("/catalog")
async def developer_catalog(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **build_developer_catalog(),
    }


@router.get("/vscode")
async def developer_vscode(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **build_vscode_extension_manifest(),
    }


@router.get("/github-app")
async def developer_github_app(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **github_app_status(),
    }


@router.get("/github-app/manifest")
async def developer_github_app_manifest(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": build_github_app_manifest(),
    }


@router.get("/status")
async def developer_status(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    readiness = assess_developer_ux_readiness()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "readiness": readiness,
        "github_app": resolve_github_app_config(),
        "catalog": build_developer_catalog(),
    }


@router.post("/analyze")
async def analyze_developer_ux(
    body: DeveloperUxRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    run: PipelineRun | None = None
    artifacts: dict[str, dict[str, Any]] = {}

    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="pipeline_run_id must be a UUID") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == pipeline_run_id))
        ).scalars().all()
        artifacts = {row.artifact_type: row.content or {} for row in rows}

    if body.persist and run is not None:
        report = await persist_developer_ux_intelligence(db, run, artifacts=artifacts, skip_if_present=False)
    else:
        report = build_developer_ux_intelligence_report(
            run_id=str(run.id) if run else "",
            repo=run.repo_full_name if run else "",
            artifacts=artifacts,
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": bool(body.persist and run is not None),
        "report": report,
    }
