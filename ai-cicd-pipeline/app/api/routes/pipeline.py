from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import require_auth
from app.database import get_db
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.schemas.pipeline_run import PipelineRunListResponse, PipelineRunResponse
from app.tasks.pipeline_tasks import run_pipeline_task

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])


@router.get("/health")
async def pipeline_health() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/runs", response_model=PipelineRunListResponse)
async def list_runs(
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(None, alias="status"),
    branch: str | None = None,
    repo: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> PipelineRunListResponse:
    cq = select(func.count()).select_from(PipelineRun)
    q = select(PipelineRun)
    if status_filter:
        q = q.where(PipelineRun.status == status_filter)
        cq = cq.where(PipelineRun.status == status_filter)
    if branch:
        q = q.where(PipelineRun.branch == branch)
        cq = cq.where(PipelineRun.branch == branch)
    if repo:
        q = q.where(PipelineRun.repo_full_name == repo)
        cq = cq.where(PipelineRun.repo_full_name == repo)
    q = q.order_by(PipelineRun.created_at.desc()).offset(offset).limit(limit)
    r = await db.execute(q)
    rows = list(r.scalars().all())
    total = int((await db.execute(cq)).scalar_one() or 0)
    return PipelineRunListResponse(
        total=total,
        items=[PipelineRunResponse.model_validate(x) for x in rows],
        filters={
            "status": status_filter,
            "branch": branch,
            "repo": repo,
            "limit": limit,
            "offset": offset,
        },
    )


@router.get("/runs/{run_id}", response_model=PipelineRunResponse)
async def get_run(run_id: UUID, db: AsyncSession = Depends(get_db)) -> PipelineRunResponse:
    r = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    row = r.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return PipelineRunResponse.model_validate(row)


@router.get("/runs/{run_id}/artifacts")
async def list_artifacts(
    run_id: UUID, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    r = await db.execute(
        select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == run_id)
    )
    arts = list(r.scalars().all())
    return {
        "items": [
            {
                "id": str(a.id),
                "artifact_type": a.artifact_type,
                "created_at": a.created_at.isoformat(),
            }
            for a in arts
        ]
    }


@router.get("/runs/{run_id}/artifacts/{artifact_type}")
async def get_artifact(
    run_id: UUID,
    artifact_type: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    r = await db.execute(
        select(PipelineArtifact).where(
            PipelineArtifact.pipeline_run_id == run_id,
            PipelineArtifact.artifact_type == artifact_type,
        )
    )
    row = r.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {
        "id": str(row.id),
        "artifact_type": row.artifact_type,
        "content": row.content,
        "raw_output": row.raw_output,
        "created_at": row.created_at.isoformat(),
    }


@router.post("/runs/{run_id}/retry")
async def retry_run(
    run_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_auth),
) -> dict[str, Any]:
    r = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    row = r.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    row.status = "queued"
    row.error_message = None
    await db.commit()
    token = request.session.get("github_token")
    run_pipeline_task.delay(str(run_id), github_token=token)
    return {"status": "ok", "run_id": str(run_id)}

