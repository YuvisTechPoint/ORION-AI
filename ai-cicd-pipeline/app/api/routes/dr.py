"""Disaster recovery API — backup policy, status, and intelligence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import optional_auth
from app.database import get_db
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.dr_enrichment import persist_dr_intelligence
from app.utils.dr_backup import list_backups, run_database_backup
from app.utils.dr_intelligence import build_dr_intelligence_report
from app.utils.dr_registry import resolve_backup_dir, resolve_dr_policy

router = APIRouter(prefix="/dr", tags=["Disaster Recovery"])


class DrAnalyzeRequest(BaseModel):
    pipeline_run_id: str | None = None
    persist: bool = Field(default=True)


class DrBackupRequest(BaseModel):
    output_dir: str | None = None


@router.get("/policy")
async def dr_policy(
    repo: str = "",
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **resolve_dr_policy(repo),
    }


@router.get("/backups")
async def dr_backups(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    backup_dir = resolve_backup_dir()
    backups = list_backups(backup_dir)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backup_dir": str(backup_dir),
        "backups": backups,
        "count": len(backups),
    }


@router.get("/status")
async def dr_status(
    repo: str = "",
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    report = build_dr_intelligence_report(repo=repo)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report": report,
    }


@router.post("/backup")
async def dr_backup(
    body: DrBackupRequest,
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    output_dir = Path(body.output_dir) if body.output_dir else None
    result = run_database_backup(output_dir=output_dir)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }


@router.post("/analyze")
async def analyze_dr(
    body: DrAnalyzeRequest,
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
        report = await persist_dr_intelligence(db, run, artifacts=artifacts, skip_if_present=False)
    else:
        report = build_dr_intelligence_report(
            run_id=str(run.id) if run else "",
            repo=run.repo_full_name if run else "",
            artifacts=artifacts,
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": bool(body.persist and run is not None),
        "report": report,
    }
