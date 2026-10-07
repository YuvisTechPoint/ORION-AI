"""ORION Autopilot API — policy-gated delivery and remediation plans."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import optional_auth
from app.config import settings
from app.database import get_db
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.autopilot_enrichment import persist_autopilot_intelligence
from app.utils.autopilot_intelligence import build_autopilot_intelligence_report
from app.utils.autopilot_planner import plan_autopilot_actions
from app.utils.autopilot_registry import ACTION_CATALOG, resolve_autopilot_policy

router = APIRouter(prefix="/autopilot", tags=["ORION Autopilot"])


class AutopilotAnalyzeRequest(BaseModel):
    pipeline_run_id: str | None = None
    environment: str = ""
    persist: bool = Field(default=True)


@router.get("/policy")
async def autopilot_policy(
    repo: str = "",
    environment: str = "",
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **resolve_autopilot_policy(repo, environment or settings.deploy_environment),
    }


@router.get("/catalog")
async def autopilot_catalog(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "actions": ACTION_CATALOG,
    }


@router.get("/plan")
async def autopilot_plan(
    run_id: str = "",
    environment: str = "",
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    if not run_id:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "actions": [],
            "summary": "Provide run_id to build a run-specific autopilot plan.",
        }
    try:
        pipeline_run_id = uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="run_id must be a UUID") from exc
    run = await db.get(PipelineRun, pipeline_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    rows = (
        await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == pipeline_run_id))
    ).scalars().all()
    artifacts = {row.artifact_type: row.content or {} for row in rows}
    actions = plan_autopilot_actions(
        repo=run.repo_full_name,
        environment=environment or settings.deploy_environment,
        run_status=str(run.status),
        artifacts=artifacts,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": str(run.id),
        "status": run.status,
        "actions": actions,
    }


@router.get("/status")
async def autopilot_status(
    repo: str = "",
    environment: str = "",
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    policy = resolve_autopilot_policy(repo, environment or settings.deploy_environment)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": policy,
        "enabled": policy.get("enabled"),
        "simulate_only": policy.get("simulate_only"),
    }


@router.post("/analyze")
async def analyze_autopilot(
    body: AutopilotAnalyzeRequest,
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

    env = body.environment or settings.deploy_environment
    if body.persist and run is not None:
        report = await persist_autopilot_intelligence(db, run, artifacts=artifacts, environment=env, skip_if_present=False)
    else:
        report = build_autopilot_intelligence_report(
            run_id=str(run.id) if run else "",
            repo=run.repo_full_name if run else "",
            branch=run.branch if run else "",
            commit=run.commit_id if run else "",
            run_status=str(run.status) if run else "",
            environment=env,
            artifacts=artifacts,
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": bool(body.persist and run is not None),
        "report": report,
    }
