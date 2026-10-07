"""Proxy multimodal requests to ORION CI/CD (avoids cross-origin browser calls)."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import expected_api_key, optional_auth
from app.config import get_settings

router = APIRouter(prefix="/api/multimodal", tags=["multimodal"])


def _orion_headers() -> dict[str, str]:
    key = expected_api_key()
    return {"X-ORION-API-Key": key} if key else {}


@router.post("/analyze")
async def proxy_multimodal_analyze(
    agent_type: str = Form(...),
    text_input: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
    _: dict = Depends(optional_auth),
) -> dict:
    settings = get_settings()
    fd: list[tuple[str, tuple[str, bytes, str]]] = []
    for upload in files:
        raw = await upload.read()
        fd.append(
            (
                "files",
                (
                    upload.filename or "upload.txt",
                    raw,
                    upload.content_type or "application/octet-stream",
                ),
            )
        )
    data = {"agent_type": agent_type}
    if text_input.strip():
        data["text_input"] = text_input

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.orion_api_url.rstrip('/')}/api/v1/multimodal/analyze",
                data=data,
                files=fd or None,
                headers=_orion_headers(),
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"ORION multimodal unreachable: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text[:500]
        raise HTTPException(status_code=response.status_code, detail=detail or "ORION multimodal error")
    return response.json()
