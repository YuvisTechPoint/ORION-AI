"""ORION Unified Risk API — fused change risk, gates, and intelligence signals."""

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
from app.services.unified_risk_enrichment import persist_unified_risk_intelligence
from app.utils.unified_risk_engine import compute_unified_risk
from app.utils.unified_risk_intelligence import build_unified_risk_intelligence_report
from app.utils.unified_risk_registry import DEFAULT_DIMENSION_WEIGHTS, resolve_unified_risk_policy

router = APIRouter(prefix="/unified-risk", tags=["ORION Unified Risk"])


class UnifiedRiskAnalyzeRequest(BaseModel):
    pipeline_run_id: str | None = None
    environment: str = ""
    persist: bool = Field(default=True)


@router.get("/policy")
async def unified_risk_policy(
    repo: str = "",
    environment: str = "",
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "default_dimension_weights": DEFAULT_DIMENSION_WEIGHTS,
        **resolve_unified_risk_policy(repo, environment or settings.deploy_environment),
    }


@router.get("/score")
async def unified_risk_score(
    run_id: str = "",
    environment: str = "",
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    if not run_id:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": "Provide run_id to compute unified risk for a pipeline run.",
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
    diff_row = artifacts.get("diff") or {}
    risk = compute_unified_risk(
        artifacts=artifacts,
        repo=run.repo_full_name,
        environment=environment or settings.deploy_environment,
        diff_text=str(diff_row.get("diff") or ""),
        changed_files=(artifacts.get("metadata") or {}).get("changed_files"),
    )
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "run_id": run_id, **risk}


@router.get("/status")
async def unified_risk_status(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "enabled": settings.unified_risk_enabled,
        "gate_enabled": settings.unified_risk_gate_enabled,
        "max_score": settings.unified_risk_max_score,
        "block_on_high": settings.unified_risk_block_on_high,
        "require_gate_fusion_pass": settings.unified_risk_require_gate_fusion_pass,
    }


@router.post("/analyze")
async def unified_risk_analyze(
    body: UnifiedRiskAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    if not body.pipeline_run_id:
        sample = build_unified_risk_intelligence_report(
            repo="demo/sample",
            environment=body.environment or settings.deploy_environment,
            artifacts={
                "code_analysis": {"severity": "pass"},
                "security_scan": {"highest_severity": "low"},
                "qa_report": {"verdict": "pass"},
                "stress_report": {"performance_verdict": "pass"},
            },
        )
        return {"generated_at": datetime.now(timezone.utc).isoformat(), "sample": True, **sample}

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
    diff_text = str((artifacts.get("diff") or {}).get("diff") or "")

    if body.persist:
        report = await persist_unified_risk_intelligence(
            db,
            run,
            artifacts=artifacts,
            environment=body.environment,
            diff_text=diff_text,
        )
    else:
        report = build_unified_risk_intelligence_report(
            run_id=str(run.id),
            repo=run.repo_full_name,
            branch=run.branch,
            commit=run.commit_id,
            run_status=str(run.status),
            environment=body.environment,
            artifacts=artifacts,
            diff_text=diff_text,
            changed_files=(artifacts.get("metadata") or {}).get("changed_files"),
        )
    return {"generated_at": datetime.now(timezone.utc).isoformat(), **report}
