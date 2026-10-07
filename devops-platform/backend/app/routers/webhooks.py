import hashlib
import hmac
import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import PipelineRun, PipelineStatus, WebhookDelivery
from app.orchestrator.dispatch import dispatch_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_github_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not secret:
        return False
    if not signature.startswith("sha256="):
        return False
    sig = signature[7:]
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, sig)


async def _find_delivery(session: AsyncSession, delivery_id: str) -> WebhookDelivery | None:
    if not delivery_id:
        return None
    return (
        await session.execute(select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id))
    ).scalar_one_or_none()


@router.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
    x_github_delivery: str | None = Header(None, alias="X-GitHub-Delivery"),
    x_github_event: str | None = Header(None, alias="X-GitHub-Event"),
) -> dict:
    from app.config import get_settings

    settings = get_settings()
    body = await request.body()
    event = x_github_event or "push"

    if settings.github_webhook_secret and not _verify_github_signature(
        body, x_hub_signature_256, settings.github_webhook_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid signature")

    delivery_id = (x_github_delivery or "").strip()
    if delivery_id:
        async with async_session_factory() as session:
            prior = await _find_delivery(session, delivery_id)
            if prior is not None and prior.response_body:
                return JSONResponse(prior.response_body, status_code=202)

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    repo = payload.get("repository") or {}
    repo_url = repo.get("clone_url") or repo.get("html_url") or ""
    if not repo_url:
        raise HTTPException(status_code=400, detail="No repository URL in payload")

    async with async_session_factory() as session:
        run = PipelineRun(
            id=uuid4(),
            repo_url=repo_url,
            commit_sha=(payload.get("after") or "")[:40] or "",
            status=PipelineStatus.PENDING,
            metadata_json={
                "repo_url": repo_url,
                "webhook": True,
                "event": event,
                "correlation_id": getattr(request.state, "correlation_id", None),
                "trace_id": getattr(request.state, "trace_id", None),
            },
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        pipeline_id = run.id

    pid = str(pipeline_id)
    executor = dispatch_pipeline(pid)
    body_out = {"pipeline_id": pid, "status": "enqueued", "executor": executor}

    if delivery_id:
        async with async_session_factory() as session:
            session.add(
                WebhookDelivery(
                    delivery_id=delivery_id,
                    event_type=event,
                    repo_url=repo_url,
                    pipeline_id=pipeline_id,
                    status="accepted",
                    response_body=body_out,
                )
            )
            await session.commit()

    return JSONResponse(body_out, status_code=202)
