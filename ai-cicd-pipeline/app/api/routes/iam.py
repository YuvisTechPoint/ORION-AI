"""Enterprise IAM API — SSO readiness, policy, and intelligence."""

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
from app.services.iam_enrichment import persist_iam_intelligence
from app.utils.enterprise_sso import assess_sso_readiness
from app.utils.iam_intelligence import (
    assess_api_key_hygiene,
    assess_mfa_readiness,
    assess_session_hardening,
    build_iam_intelligence_report,
)
from app.utils.iam_registry import resolve_iam_policy

router = APIRouter(prefix="/iam", tags=["Enterprise IAM"])


class IamAnalyzeRequest(BaseModel):
    pipeline_run_id: str | None = None
    persist: bool = Field(default=True)


@router.get("/policy")
async def iam_policy(
    repo: str = "",
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **resolve_iam_policy(repo),
    }


@router.get("/sso")
async def iam_sso(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sso_readiness": assess_sso_readiness(),
    }


@router.get("/status")
async def iam_status(
    repo: str = "",
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    policy = resolve_iam_policy(repo)
    sso = assess_sso_readiness()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": policy,
        "sso_readiness": sso,
        "session_hardening": assess_session_hardening(),
        "api_key_hygiene": assess_api_key_hygiene(),
        "mfa_readiness": assess_mfa_readiness(),
    }


@router.post("/analyze")
async def analyze_iam(
    body: IamAnalyzeRequest,
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
        report = await persist_iam_intelligence(db, run, artifacts=artifacts, skip_if_present=False)
    else:
        report = build_iam_intelligence_report(
            run_id=str(run.id) if run else "",
            repo=run.repo_full_name if run else "",
            artifacts=artifacts,
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": bool(body.persist and run is not None),
        "report": report,
    }
