from typing import Any

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.routes.auth import require_auth
from app.agents.multimodal.git_log_agent import GitLogAgent
from app.agents.multimodal.payment_agent import PaymentAgent
from app.config import settings

router = APIRouter(prefix="/multimodal", tags=["Multimodal Analysis"])


def _artifact_from_upload(filename: str, content_type: str | None, data: bytes) -> dict[str, Any]:
    name = filename.lower()
    ct = (content_type or "").lower()
    if ct in ("image/png", "image/jpeg") or name.endswith((".png", ".jpg", ".jpeg")):
        return {"type": "image", "content": data, "filename": filename, "mime_type": ct}
    if name.endswith(".zip"):
        return {"type": "zip", "content": data, "filename": filename, "mime_type": "application/zip"}
    if name.endswith(".log") or name.endswith(".txt"):
        return {"type": "log", "content": data, "filename": filename, "mime_type": ct}
    if name.endswith(".csv"):
        return {"type": "csv", "content": data, "filename": filename, "mime_type": ct}
    if name.endswith(".pdf"):
        return {"type": "pdf", "content": data, "filename": filename, "mime_type": "application/pdf"}
    return {"type": "text", "content": data, "filename": filename, "mime_type": ct}


@router.post("/git-logs")
async def analyze_git_logs(
    user: dict = Depends(require_auth),
    files: list[UploadFile] = File(default=[]),
    text_input: str = Form(default=""),
) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    for uf in files:
        data = await uf.read()
        artifacts.append(_artifact_from_upload(uf.filename or "file", uf.content_type, data))
    if text_input.strip():
        artifacts.append(
            {
                "type": "text",
                "content": text_input.encode("utf-8"),
                "filename": "pasted.txt",
                "mime_type": "text/plain",
            }
        )
    if not artifacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one file or text input",
        )

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    agent = GitLogAgent(anthropic_client=client, artifacts=artifacts)
    result = await agent.execute()
    return {
        "status": "success",
        "agent": "git_log_analysis",
        "analyzed_by": user.get("username"),
        "result": result,
    }


@router.post("/payment")
async def analyze_payment(
    user: dict = Depends(require_auth),
    files: list[UploadFile] = File(default=[]),
    text_input: str = Form(default=""),
) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    for uf in files:
        data = await uf.read()
        artifacts.append(_artifact_from_upload(uf.filename or "file", uf.content_type, data))
    if text_input.strip():
        artifacts.append(
            {
                "type": "text",
                "content": text_input.encode("utf-8"),
                "filename": "pasted.txt",
                "mime_type": "text/plain",
            }
        )
    if not artifacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one file or text input",
        )

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    agent = PaymentAgent(anthropic_client=client, artifacts=artifacts)
    result = await agent.execute()
    return {
        "status": "success",
        "agent": "payment_analysis",
        "analyzed_by": user.get("username"),
        "result": result,
    }
