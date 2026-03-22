import hashlib
import hmac
import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import PipelineRun, PipelineStatus
from app.orchestrator.pipeline_runner import run_pipeline

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


@router.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> dict:
    from app.config import get_settings

    settings = get_settings()
    body = await request.body()

    if settings.github_webhook_secret and not _verify_github_signature(
        body, x_hub_signature_256, settings.github_webhook_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    repo = payload.get("repository") or {}
    repo_url = repo.get("clone_url") or repo.get("html_url") or ""
    if not repo_url:
        raise HTTPException(status_code=400, detail="No repository URL in payload")

    async with async_session_factory() as session:
        p = PipelineRun(
            id=uuid4(),
            repo_url=repo_url,
            commit_sha=payload.get("after", "")[:40] or "",
            status=PipelineStatus.PENDING,
            metadata_json={"repo_url": repo_url, "webhook": True},
        )
        session.add(p)
        await session.commit()
        await session.refresh(p)
        pid = str(p.id)

    run_pipeline.delay(pid)
    return {"pipeline_id": pid, "status": "enqueued"}
