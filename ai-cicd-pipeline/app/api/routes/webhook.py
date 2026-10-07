import re
import copy
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.database import AsyncSessionLocal
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.schemas.webhook import GitHubPushPayload
from app.services.github_service import github_service
from app.services.pipeline_dedup import dedup_response, find_inflight_run
from app.services.slack_service import slack_service
from app.tasks.dispatch import dispatch_pipeline
from app.services.github_app_service import handle_github_app_event
from app.utils.hmac_validator import get_validated_github_app_payload, get_validated_github_payload
from app.observability.metrics import webhook_deliveries_total
from app.services.webhook_ledger import find_delivery, record_delivery
from app.utils.logger import get_logger

router = APIRouter(prefix="/webhook", tags=["Webhooks"])
logger = get_logger("webhook")


def _parse_json(body: bytes) -> dict[str, Any]:
    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")
    return data


@router.post("/github")
async def github_push(
    request: Request,
    body: bytes = Depends(get_validated_github_payload),
) -> Any:
    data = _parse_json(body)

    event = request.headers.get("X-GitHub-Event", "push")
    if event == "ping":
        return {"status": "ok", "event": "ping"}
    if event == "pull_request":
        return await _handle_pull_request(data)
    if event != "push":
        return {"status": "ignored", "event": event}

    delivery_id = (request.headers.get("X-GitHub-Delivery") or "").strip()
    if delivery_id:
        async with AsyncSessionLocal() as db:
            prior = await find_delivery(db, delivery_id)
            if prior is not None and prior.response_body:
                webhook_deliveries_total.inc(event=event, status="replay")
                return JSONResponse(prior.response_body, status_code=status.HTTP_202_ACCEPTED)

    try:
        payload = GitHubPushPayload.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc

    if payload.ref.startswith("refs/tags/"):
        return {"status": "ignored", "reason": "tag push"}
    commit_id = payload.after
    if not commit_id or set(commit_id) == {"0"}:
        return {"status": "ignored", "reason": "branch deletion"}
    if not re.fullmatch(r"[0-9a-f]{40}", commit_id):
        raise HTTPException(status_code=400, detail="Invalid commit SHA in webhook payload")

    try:
        async with AsyncSessionLocal() as db:
            existing = await find_inflight_run(
                db,
                repo_full_name=payload.repository.full_name,
                commit_id=commit_id,
            )
            if existing is not None:
                executor = dispatch_pipeline(existing.id, github_token=request.session.get("github_token"))
                return JSONResponse(
                    dedup_response(existing, executor),
                    status_code=status.HTTP_202_ACCEPTED,
                )

            run = PipelineRun(
                commit_id=commit_id,
                short_commit_id=commit_id[:8],
                branch=payload.branch,
                pusher=payload.pusher.name or "unknown",
                repo_full_name=payload.repository.full_name,
                clone_url=payload.repository.clone_url,
                status="queued",
                correlation_id=getattr(request.state, "correlation_id", None),
                trace_id=getattr(request.state, "trace_id", None),
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id

        await github_service.safe_commit_status(
            payload.repository.full_name, commit_id, "pending", "Pipeline queued"
        )
        executor = dispatch_pipeline(run_id, github_token=request.session.get("github_token"))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("failed to enqueue pipeline for %s", commit_id)
        raise HTTPException(status_code=500, detail=f"Failed to queue pipeline: {exc}") from exc

    body_out = {
        "status": "accepted",
        "pipeline_run_id": str(run_id),
        "commit_id": commit_id,
        "executor": executor,
        "correlation_id": getattr(request.state, "correlation_id", None),
    }
    if delivery_id:
        async with AsyncSessionLocal() as db:
            await record_delivery(
                db,
                delivery_id=delivery_id,
                event_type=event,
                repo_full_name=payload.repository.full_name,
                commit_id=commit_id,
                pipeline_run_id=run_id,
                status="accepted",
                response_body=body_out,
            )
    webhook_deliveries_total.inc(event=event, status="accepted")
    return JSONResponse(body_out, status_code=status.HTTP_202_ACCEPTED)


@router.post("/github/pr")
async def github_pr(body: bytes = Depends(get_validated_github_payload)) -> dict[str, Any]:
    return await _handle_pull_request(_parse_json(body))


@router.post("/github/app")
async def github_app_webhook(
    request: Request,
    body: bytes = Depends(get_validated_github_app_payload),
) -> dict[str, Any]:
    event = request.headers.get("X-GitHub-Event", "unknown")
    data = _parse_json(body)
    result = handle_github_app_event(event, data)
    logger.info("GitHub App event %s -> %s", event, result.get("status"))
    return result


def _registry_entries(content: dict[str, Any]) -> list[dict[str, Any]]:
    # "bundles"/"branch" is the legacy registry layout from earlier ORION versions.
    entries = content.get("branches")
    if entries is None:
        entries = content.get("bundles") or []
    return [e for e in entries if isinstance(e, dict)]


async def _handle_pull_request(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("action") != "closed":
        return {"status": "ignored", "reason": f"action {data.get('action')}"}
    pr = data.get("pull_request") or {}
    if not pr.get("merged"):
        return {"status": "ignored", "reason": "closed without merge"}

    repo_full_name = (data.get("repository") or {}).get("full_name")
    branch_name = (pr.get("head") or {}).get("ref")
    pr_number = pr.get("number")
    if not repo_full_name or not branch_name:
        raise HTTPException(status_code=400, detail="Missing repository or head branch")

    async with AsyncSessionLocal() as db:
        artifacts = (
            await db.execute(
                select(PipelineArtifact)
                .join(PipelineRun, PipelineRun.id == PipelineArtifact.pipeline_run_id)
                .where(
                    PipelineRun.repo_full_name == repo_full_name,
                    PipelineArtifact.artifact_type == "auto_pr_registry",
                )
            )
        ).scalars().all()

        for art in artifacts:
            content = copy.deepcopy(art.content or {})
            for entry in _registry_entries(content):
                if (entry.get("branch_name") or entry.get("branch")) != branch_name:
                    continue
                deleted = False
                try:
                    deleted = await github_service.delete_branch(repo_full_name, branch_name)
                except Exception as exc:
                    logger.error("failed to delete merged branch %s: %s", branch_name, exc)
                entry.update(merged=True, deleted=deleted, merged_and_deleted=deleted, merged_pr=pr_number)
                art.content = content
                flag_modified(art, "content")
                await db.commit()
                logger.info("ORION PR #%s merged; branch %s deleted=%s", pr_number, branch_name, deleted)
                await slack_service.send_text(
                    f"ORION fix PR #{pr_number} merged in {repo_full_name}; branch `{branch_name}` deleted={deleted}"
                )
                return {"status": "ok", "branch": branch_name, "branch_deleted": deleted, "pr_number": pr_number}

    return {"status": "ignored", "reason": "branch not managed by ORION"}
