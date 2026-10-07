"""Autonomous remediation API — levels, analysis, and fix-loop introspection."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.remediation_intelligence_agent import RemediationIntelligenceAgent
from app.api.routes.auth import optional_auth
from app.config import settings
from app.database import get_db
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.remediation_enrichment import persist_remediation_intelligence
from app.utils.remediation_intelligence import build_remediation_intelligence_report
from app.utils.remediation_levels import list_remediation_levels

router = APIRouter(prefix="/remediation", tags=["Remediation"])


class RemediationAnalyzeRequest(BaseModel):
    pipeline_run_id: str
    use_llm: bool = Field(default=False)


@router.get("/levels")
async def remediation_levels(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "max_autonomy_level": settings.remediation_autonomy_max_level,
        "l5_auto_retry_enabled": settings.remediation_l5_auto_retry_enabled,
        "l6_auto_deploy_enabled": settings.remediation_l6_auto_deploy_enabled,
        "levels": list_remediation_levels(),
    }


@router.post("/analyze")
async def remediation_analyze(
    body: RemediationAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    try:
        run_id = uuid.UUID(body.pipeline_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid pipeline_run_id") from exc

    run = await db.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    rows = (
        await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == run.id))
    ).scalars().all()
    artifacts = {a.artifact_type: a.content or {} for a in rows}
    run_dict = {
        "id": str(run.id),
        "status": run.status,
        "error_message": run.error_message,
        "repo_full_name": run.repo_full_name,
        "branch": run.branch,
        "commit_id": run.commit_id,
    }

    if body.use_llm and settings.llm_enabled:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        agent = RemediationIntelligenceAgent(
            run.id,
            db,
            client,
            run=run_dict,
            artifacts=artifacts,
            fix_loop_report=artifacts.get("fix_loop_report"),
        )
        report = await agent.execute()
    else:
        report = await persist_remediation_intelligence(db, run, artifacts=artifacts)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": True,
        "report": report,
    }


@router.get("/runs/{run_id}")
async def remediation_for_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    try:
        rid = uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid run_id") from exc

    run = await db.get(PipelineRun, rid)
    if run is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    rows = (
        await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == run.id))
    ).scalars().all()
    artifacts = {a.artifact_type: a.content or {} for a in rows}
    run_dict = {
        "id": str(run.id),
        "status": run.status,
        "error_message": run.error_message,
        "repo_full_name": run.repo_full_name,
        "branch": run.branch,
        "commit_id": run.commit_id,
    }
    report = artifacts.get("remediation_intelligence") or build_remediation_intelligence_report(
        run=run_dict,
        artifacts=artifacts,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": str(run.id),
        "report": report,
    }
