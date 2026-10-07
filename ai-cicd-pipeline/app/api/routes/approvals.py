"""Enterprise approvals API — workflow, sign-offs, and status."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import optional_auth, require_pipeline_operator
from app.config import settings
from app.database import get_db
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.approval_enrichment import _org_from_repo, add_enterprise_signoff
from app.tasks.dispatch import dispatch_pipeline
from app.utils.approval_intelligence import build_approval_intelligence_report
from app.utils.approval_workflow import resolve_approval_workflow

router = APIRouter(prefix="/approvals", tags=["Approvals"])


class ApprovalSignRequest(BaseModel):
    approver: str = Field(..., max_length=200)
    role: str = Field(default="release_manager", max_length=100)
    comment: str = Field(default="", max_length=500)
    signature_token: str | None = Field(default=None, description="HMAC token when signed approvals required")


@router.get("/workflow")
async def approval_workflow(
    repo: str,
    environment: str | None = None,
    change_risk: int | None = None,
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    org = _org_from_repo(repo)
    env = environment or settings.deploy_environment
    workflow = resolve_approval_workflow(
        org=org,
        repo=repo,
        environment=env,
        change_risk_score=change_risk,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "org": org,
        "repo": repo,
        "environment": env,
        "workflow": workflow,
    }


@router.get("/runs/{run_id}")
async def approval_status(
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
    intel = artifacts.get("approval_intelligence")
    if not intel:
        org = _org_from_repo(run.repo_full_name)
        change_risk = artifacts.get("change_risk_report") or {}
        intel = build_approval_intelligence_report(
            org=org,
            repo=run.repo_full_name,
            environment=settings.deploy_environment,
            commit=run.commit_id,
            committer=(artifacts.get("metadata") or {}).get("pusher") or "unknown",
            automated_approval=artifacts.get("approval") or {},
            enterprise_approval=artifacts.get("enterprise_approval"),
            change_risk_score=change_risk.get("final_risk"),
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": str(run.id),
        "status": run.status,
        "report": intel,
        "enterprise_approval": artifacts.get("enterprise_approval"),
    }


@router.post("/runs/{run_id}/sign")
async def approval_sign(
    run_id: str,
    body: ApprovalSignRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(optional_auth),
) -> dict[str, Any]:
    require_pipeline_operator(user)
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

    try:
        updated = await add_enterprise_signoff(
            db,
            run,
            approver=body.approver,
            role=body.role,
            comment=body.comment,
            artifacts=artifacts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    resumed = False
    if updated.get("ready_for_deploy") and run.status == "awaiting_approval":
        dispatch_pipeline(run.id, resume=True)
        resumed = True

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": str(run.id),
        "enterprise_approval": updated,
        "ready_for_deploy": updated.get("ready_for_deploy"),
        "pipeline_resumed": resumed,
    }
