import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.schemas.webhook import GitHubPushPayload
from app.services.github_service import github_service
from app.tasks.pipeline_tasks import run_pipeline_task
from app.utils.hmac_validator import get_validated_github_payload

router = APIRouter(prefix="/webhook", tags=["Webhooks"])


@router.post("/github")
async def github_push(
    request: Request,
    body: bytes = Depends(get_validated_github_payload),
) -> dict[str, Any]:
    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return {"status": "ok"}

    if event != "push":
        return {"status": "ignored", "event": event}

    try:
        payload = GitHubPushPayload.model_validate(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.ref.startswith("refs/tags/"):
        return {"status": "ignored", "reason": "tag_push"}

    commit_id = payload.after
    if not commit_id or commit_id.startswith("0000"):
        return {"status": "ignored", "reason": "delete_or_empty"}

    short = commit_id[:8]
    session_token = request.session.get("github_token")

    async with AsyncSessionLocal() as db:
        run = PipelineRun(
            commit_id=commit_id,
            short_commit_id=short,
            branch=payload.branch,
            pusher=payload.pusher.name or "unknown",
            repo_full_name=payload.repository.full_name,
            clone_url=payload.repository.clone_url,
            status="queued",
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

    try:
        await github_service.set_commit_status(
            payload.repository.full_name,
            commit_id,
            "pending",
            "ORION pipeline queued",
        )
    except Exception:
        pass

    run_pipeline_task.delay(str(run_id), github_token=session_token)

    return JSONResponse(
        {"status": "accepted", "pipeline_run_id": str(run_id)},
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.post("/github/pr")
async def github_pr(
    request: Request,
    body: bytes = Depends(get_validated_github_payload),
) -> dict[str, Any]:
    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if data.get("action") != "closed":
        return {"status": "ignored"}

    pr = data.get("pull_request") or {}
    if not pr.get("merged"):
        return {"status": "ignored"}

    branch_name = (pr.get("head") or {}).get("ref")
    repo_full_name = (data.get("repository") or {}).get("full_name")
    if not branch_name or not repo_full_name:
        return {"status": "ignored"}

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(PipelineRun).where(PipelineRun.repo_full_name == repo_full_name)
        )
        runs = list(r.scalars().all())
        for run in runs:
            ar = await db.execute(
                select(PipelineArtifact).where(
                    PipelineArtifact.pipeline_run_id == run.id,
                    PipelineArtifact.artifact_type == "auto_pr_registry",
                )
            )
            for art in ar.scalars().all():
                content = art.content or {}
                bundles = content.get("bundles") or []
                for b in bundles:
                    if b.get("branch") == branch_name:
                        try:
                            await github_service.delete_branch(repo_full_name, branch_name)
                        except Exception:
                            pass
                        b["branch_deleted"] = True
                        art.content = content
                        await db.commit()
                        return {"status": "ok", "branch_deleted": True}

    return {"status": "not_found"}
