from __future__ import annotations

from typing import List

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.config import settings
from app.api.routes.auth import require_auth
from app.agents.multimodal.git_log_agent import GitLogAgent
from app.agents.multimodal.payment_agent import PaymentAgent

router = APIRouter(prefix="/multimodal", tags=["Multimodal Analysis"])


def _detect_artifact_type(filename: str, content_type: str) -> str:
    name = filename.lower()
    ctype = (content_type or "").lower()

    if ctype in {"image/png", "image/jpeg", "image/jpg"}:
        return "image"
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".csv") or ctype in {"text/csv", "application/csv"}:
        return "csv"
    if name.endswith(".log") or name.endswith(".txt"):
        return "log"
    return "text"


@router.post("/git-logs")
async def analyze_git_logs(
    request: Request,
    files: List[UploadFile] = File(default=[]),
    text_input: str = Form(default=""),
    user: dict = Depends(require_auth),
) -> dict:
    # Read uploaded files into artifacts
    artifacts: list[dict] = []
    for file in files:
        filename = file.filename or "uploaded_file"
        content_type = file.content_type or "application/octet-stream"
        raw = await file.read()
        artifact_type = _detect_artifact_type(filename, content_type)
        artifacts.append(
            {
                "type": artifact_type,
                "content": raw,
                "filename": filename,
                "mime_type": content_type,
            }
        )

    if text_input:
        artifacts.append(
            {
                "type": "text",
                "content": text_input,
                "filename": "user_input.txt",
                "mime_type": "text/plain",
            }
        )

    if not artifacts:
        raise HTTPException(status_code=400, detail="Provide at least one log file or paste log text")

    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    agent = GitLogAgent(anthropic_client=anthropic_client, artifacts=artifacts)
    result = await agent.execute()

    analyzed_by = user.get("username") or user.get("github_username") or "unknown"

    return {
        "status": "success",
        "agent": "git_log_analysis",
        "analyzed_by": analyzed_by,
        "result": result,
    }


@router.post("/payment")
async def analyze_payment(
    request: Request,
    files: List[UploadFile] = File(default=[]),
    text_input: str = Form(default=""),
    user: dict = Depends(require_auth),
) -> dict:
    artifacts: list[dict] = []
    for file in files:
        filename = file.filename or "uploaded_file"
        content_type = file.content_type or "application/octet-stream"
        raw = await file.read()

        name_lower = filename.lower()
        ctype_lower = content_type.lower()

        if name_lower.endswith(".csv") or ctype_lower in {"text/csv", "application/csv"}:
            artifact_type = "csv"
        elif name_lower.endswith(".pdf") or ctype_lower == "application/pdf":
            artifact_type = "pdf"
        elif ctype_lower in {"image/png", "image/jpeg", "image/jpg"}:
            artifact_type = "image"
        elif name_lower.endswith(".json") or ctype_lower == "application/json":
            artifact_type = "text"
        else:
            artifact_type = "text"

        artifacts.append(
            {
                "type": artifact_type,
                "content": raw,
                "filename": filename,
                "mime_type": content_type,
            }
        )

    if text_input:
        artifacts.append(
            {
                "type": "text",
                "content": text_input,
                "filename": "user_input.txt",
                "mime_type": "text/plain",
            }
        )

    if not artifacts:
        raise HTTPException(status_code=400, detail="Provide at least one log file or paste log text")

    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    agent = PaymentAgent(anthropic_client=anthropic_client, artifacts=artifacts)
    result = await agent.execute()

    analyzed_by = user.get("username") or user.get("github_username") or "unknown"

    return {
        "status": "success",
        "agent": "payment_analysis",
        "analyzed_by": analyzed_by,
        "result": result,
    }
