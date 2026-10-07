"""REST endpoints for log text preprocessing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import optional_auth
from app.utils.text_analysis import run_text_operations, sanitize_for_agent, similarity_ratio

router = APIRouter(prefix="/api/tools", tags=["Text Tools"])

VALID_OPERATIONS = frozenset(
    {
        "metrics",
        "redact",
        "redact_secrets",
        "sanitize",
        "classify_log",
        "timeline",
        "errors",
        "error_signatures",
        "stack_traces",
        "truncate",
        "fingerprint",
        "diff_stats",
        "commit",
    }
)


class TextAnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500_000)
    operations: list[str] = Field(default_factory=lambda: ["metrics", "sanitize", "classify_log"])


class TextCompareRequest(BaseModel):
    left: str = Field(max_length=200_000)
    right: str = Field(max_length=200_000)


@router.post("/text-analyze")
async def text_analyze(body: TextAnalyzeRequest, _: dict = Depends(optional_auth)) -> dict[str, Any]:
    unknown = [op for op in body.operations if op.strip().lower() not in VALID_OPERATIONS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown operations: {unknown}")
    return run_text_operations(body.text, body.operations)


@router.post("/text-sanitize")
async def text_sanitize(body: TextAnalyzeRequest, _: dict = Depends(optional_auth)) -> dict[str, str]:
    return {"sanitized": sanitize_for_agent(body.text)}


@router.post("/text-compare")
async def text_compare(body: TextCompareRequest, _: dict = Depends(optional_auth)) -> dict[str, Any]:
    return {
        "similarity": similarity_ratio(body.left, body.right),
        "left_fingerprint": sanitize_for_agent(body.left[:200]),
        "right_fingerprint": sanitize_for_agent(body.right[:200]),
    }
