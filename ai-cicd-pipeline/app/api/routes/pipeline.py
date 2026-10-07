import asyncio
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import optional_auth, require_pipeline_operator
from app.config import settings
from app.database import get_db
from app.models.pipeline_artifact import VALID_ARTIFACT_TYPES, PipelineArtifact
from app.models.pipeline_run import RETRYABLE_STATUSES, TERMINAL_STATUSES, VALID_STATUSES, PipelineRun
from app.schemas.pipeline_run import PipelineRunListResponse, PipelineRunResponse
from app.services.events import publish_event
from app.services.pipeline_dedup import dedup_response, find_inflight_run
from app.services.audit_trail import append_audit_event, list_audit_events
from app.services.readiness import readiness_report
from app.tasks.dispatch import cancel_inline, dispatch_pipeline
from app.utils.artifact_summaries import artifact_verdict, summarize_artifact
from app.utils.logger import get_logger
from app.utils.security import validate_branch_name, validate_remote_clone_url

logger = get_logger("pipeline_api")

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])


def _artifact_dict(a: PipelineArtifact, include_raw: bool = False) -> dict[str, Any]:
    content = a.content if isinstance(a.content, dict) else {}
    data = {
        "id": str(a.id),
        "artifact_type": a.artifact_type,
        "content": a.content,
        "summary": summarize_artifact(a.artifact_type, content),
        "verdict": artifact_verdict(a.artifact_type, content),
        "agent_model": a.agent_model,
        "tokens_used": a.tokens_used,
        "duration_seconds": a.duration_seconds,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
    if include_raw:
        data["raw_output"] = a.raw_output
    return data


async def _get_run_or_404(db: AsyncSession, run_id: UUID) -> PipelineRun:
    row = (await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@router.get("/health")
async def pipeline_health() -> dict[str, Any]:
    report = await readiness_report()
    if not report.get("ready"):
        raise HTTPException(status_code=503, detail=report)
    return {
        "status": "ok",
        "ready": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": report.get("checks"),
    }


@router.get("/runs", response_model=PipelineRunListResponse)
async def list_runs(
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(None, alias="status"),
    branch: str | None = None,
    repo: str | None = None,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: dict = Depends(optional_auth),
) -> PipelineRunListResponse:
    if status_filter and status_filter not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status filter: {status_filter}")
    q = select(PipelineRun)
    cq = select(func.count()).select_from(PipelineRun)
    for column, value in ((PipelineRun.status, status_filter), (PipelineRun.branch, branch), (PipelineRun.repo_full_name, repo)):
        if value:
            q = q.where(column == value)
            cq = cq.where(column == value)
    rows = (
        await db.execute(q.order_by(PipelineRun.created_at.desc()).offset(offset).limit(limit))
    ).scalars().all()
    total = int((await db.execute(cq)).scalar_one() or 0)
    items = [PipelineRunResponse.model_validate(x) for x in rows]
    return PipelineRunListResponse(
        total=total,
        items=items,
        runs=items,
        filters={"status": status_filter, "branch": branch, "repo": repo, "limit": limit, "offset": offset},
    )


@router.get("/runs/{run_id}", response_model=PipelineRunResponse)
async def get_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> PipelineRunResponse:
    return PipelineRunResponse.model_validate(await _get_run_or_404(db, run_id))


@router.get("/runs/{run_id}/artifacts")
async def list_artifacts(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    await _get_run_or_404(db, run_id)
    rows = (
        await db.execute(
            select(PipelineArtifact)
            .where(PipelineArtifact.pipeline_run_id == run_id)
            .order_by(PipelineArtifact.created_at.asc())
        )
    ).scalars().all()
    return {"items": [_artifact_dict(a) for a in rows], "total": len(rows)}


@router.get("/runs/{run_id}/artifacts/{artifact_type}")
async def get_artifact(
    run_id: UUID,
    artifact_type: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    if artifact_type not in VALID_ARTIFACT_TYPES:
        raise HTTPException(status_code=422, detail=f"Unknown artifact type: {artifact_type}")
    row = (
        await db.execute(
            select(PipelineArtifact)
            .where(PipelineArtifact.pipeline_run_id == run_id, PipelineArtifact.artifact_type == artifact_type)
            .order_by(PipelineArtifact.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return _artifact_dict(row, include_raw=True)


@router.get("/runs/{run_id}/diagnostics")
async def get_run_diagnostics(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    """Operator playbook: evidence, remediation steps, and config pointers for blocked/failed runs."""
    from app.utils.run_diagnostics import build_run_diagnostics

    row = await _get_run_or_404(db, run_id)
    artifacts = (
        await db.execute(
            select(PipelineArtifact)
            .where(PipelineArtifact.pipeline_run_id == run_id)
            .order_by(PipelineArtifact.created_at.asc())
        )
    ).scalars().all()
    run_dict = PipelineRunResponse.model_validate(row).model_dump()
    return build_run_diagnostics(run_dict, [_artifact_dict(a) for a in artifacts])


@router.get("/runs/{run_id}/audit")
async def get_audit_trail(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    await _get_run_or_404(db, run_id)
    events = await list_audit_events(db, run_id)
    return {"pipeline_run_id": str(run_id), "events": events, "total": len(events)}


RESUMABLE_STATUSES = RETRYABLE_STATUSES | {"awaiting_approval"}


@router.post("/runs/{run_id}/retry")
async def retry_run(
    run_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(optional_auth),
) -> dict[str, Any]:
    require_pipeline_operator(user)
    await _get_run_or_404(db, run_id)
    result = await db.execute(
        update(PipelineRun)
        .where(PipelineRun.id == run_id, PipelineRun.status.in_(RETRYABLE_STATUSES))
        .values(status="queued", error_message=None, completed_at=None)
    )
    if result.rowcount == 0:
        row = await _get_run_or_404(db, run_id)
        raise HTTPException(
            status_code=409,
            detail=f"Run in status '{row.status}' cannot be retried; only blocked, failed or rejected runs can.",
        )
    await db.commit()
    from app.services.workdir_manager import release_run_workspace

    try:
        release_run_workspace(run_id)
    except Exception as exc:  # noqa: BLE001 — retry must not fail on cleanup alone
        logger.warning("retry workspace cleanup for %s: %s", run_id, exc)
    await append_audit_event(
        db,
        run_id,
        action="pipeline.retry",
        user=user,
        outcome="queued",
        details={"mode": "full"},
    )
    executor = dispatch_pipeline(run_id, github_token=request.session.get("github_token"))
    return {"status": "retrying", "pipeline_run_id": str(run_id), "executor": executor}


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(optional_auth),
) -> dict[str, Any]:
    require_pipeline_operator(user)
    row = await _get_run_or_404(db, run_id)
    if row.status not in RESUMABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Run status '{row.status}' cannot be resumed; use retry for blocked runs.",
        )
    arts = (
        await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == run_id))
    ).scalars().all()
    artifact_types = {a.artifact_type for a in arts}
    if not artifact_types.intersection({"metadata", "full_scan_combined", "code_analysis"}):
        raise HTTPException(status_code=409, detail="No checkpoint artifacts found; use full retry instead.")

    await db.execute(
        update(PipelineRun)
        .where(PipelineRun.id == run_id)
        .values(status="queued", error_message=None, completed_at=None)
    )
    await db.commit()
    await append_audit_event(
        db,
        run_id,
        action="pipeline.resume",
        user=user,
        outcome="queued",
        details={"checkpoint_artifacts": sorted(artifact_types)},
    )
    executor = dispatch_pipeline(
        run_id,
        github_token=request.session.get("github_token"),
        resume=True,
    )
    return {"status": "resuming", "pipeline_run_id": str(run_id), "executor": executor, "resume": True}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(optional_auth),
) -> dict[str, Any]:
    require_pipeline_operator(user)
    row = await _get_run_or_404(db, run_id)
    if row.status in TERMINAL_STATUSES:
        return {"status": row.status, "pipeline_run_id": str(run_id), "cancelled": False}
    result = await db.execute(
        update(PipelineRun)
        .where(PipelineRun.id == run_id, PipelineRun.status.not_in(TERMINAL_STATUSES))
        .values(
            status="cancelled",
            error_message="Cancelled by operator",
            completed_at=datetime.now(timezone.utc),
        )
    )
    if result.rowcount == 0:
        await db.refresh(row)
        return {"status": row.status, "pipeline_run_id": str(run_id), "cancelled": False}
    await db.commit()
    await append_audit_event(
        db,
        run_id,
        action="pipeline.cancel",
        user=user,
        outcome="cancelled",
        details={},
    )
    cancel_inline(run_id)
    publish_event(run_id, {"kind": "stage-update", "stage": "cancelled", "status": "cancelled"})
    return {"status": "cancelled", "pipeline_run_id": str(run_id), "cancelled": True}


_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
_REMOTE_PREFIXES = ("https://", "http://", "ssh://", "git@")


class TriggerRequest(BaseModel):
    clone_url: str = Field(min_length=1, max_length=2000, description="git URL, or a local path outside production")
    branch: str = Field(default="main")
    repo_full_name: str | None = Field(default=None, max_length=255)


def _repo_name_for(url: str) -> str:
    if "github.com" in url:
        tail = url.rstrip("/").removesuffix(".git").split("github.com")[-1].lstrip(":/")
        if tail.count("/") == 1:
            return tail
    name = Path(url.rstrip("/\\").removesuffix(".git")).name or "repository"
    return f"local/{name}"


def _resolve_head(url: str, branch: str) -> str | None:
    try:
        p = subprocess.run(
            ["git", "ls-remote", url, f"refs/heads/{branch}"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=502, detail=f"git ls-remote failed: {exc}") from exc
    if p.returncode != 0:
        raise HTTPException(status_code=400, detail=f"Cannot read repository: {p.stderr.strip()[:500]}")
    line = p.stdout.strip().splitlines()[0] if p.stdout.strip() else ""
    sha = line.split()[0] if line else ""
    return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None


@router.post("/trigger", status_code=202)
async def trigger_run(
    body: TriggerRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(optional_auth),
) -> dict[str, Any]:
    """Start a pipeline for the head of a branch without a GitHub webhook (dashboard, scripts)."""
    require_pipeline_operator(user)
    url = body.clone_url.strip()
    branch = body.branch.strip() or "main"
    validate_branch_name(branch)
    if url.startswith("-") or not _BRANCH_RE.fullmatch(branch):
        raise HTTPException(status_code=400, detail="Invalid repository URL or branch name")
    if url.startswith(_REMOTE_PREFIXES):
        validate_remote_clone_url(url)
        clone_url = url
    else:
        if settings.is_production:
            raise HTTPException(status_code=400, detail="Local repository paths are disabled in production")
        local = Path(url.removeprefix("file://")).expanduser()
        if not local.is_dir() or not (local / ".git").is_dir():
            raise HTTPException(
                status_code=400,
                detail=f"Local path must be an existing git repository: {url}",
            )
        clone_url = str(local.resolve())

    commit_id = await asyncio.to_thread(_resolve_head, clone_url, branch)
    if commit_id is None:
        raise HTTPException(status_code=400, detail=f"Branch '{branch}' not found in {url}")

    repo_full_name = body.repo_full_name or _repo_name_for(clone_url)
    existing = await find_inflight_run(db, repo_full_name=repo_full_name, commit_id=commit_id)
    if existing is not None:
        executor = dispatch_pipeline(existing.id, github_token=request.session.get("github_token"))
        return dedup_response(existing, executor)

    run = PipelineRun(
        commit_id=commit_id,
        short_commit_id=commit_id[:8],
        branch=branch,
        pusher=user.get("username") or "dashboard",
        repo_full_name=repo_full_name,
        clone_url=clone_url,
        status="queued",
        correlation_id=getattr(request.state, "correlation_id", None),
        trace_id=getattr(request.state, "trace_id", None),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    await append_audit_event(
        db,
        run.id,
        action="pipeline.trigger",
        user=user,
        outcome="queued",
        details={
            "repo_full_name": repo_full_name,
            "branch": branch,
            "commit_id": commit_id,
            "correlation_id": getattr(request.state, "correlation_id", None),
        },
    )
    executor = dispatch_pipeline(run.id, github_token=request.session.get("github_token"))
    return {
        "status": "accepted",
        "pipeline_run_id": str(run.id),
        "commit_id": commit_id,
        "repo_full_name": run.repo_full_name,
        "executor": executor,
    }
