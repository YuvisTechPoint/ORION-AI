"""Memory Gateway API — /api/v2/memory (ORION-ARCH-001 §6, §16)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.routes.auth import optional_auth
from app.services.memory_gateway_service import (
    get_memory_gateway,
    read_memory_context,
    tenant_from_repo,
)
from shared.memory_gateway.models import MemoryWriteRequest

router = APIRouter(prefix="/memory", tags=["memory-v2"])


class MemoryWriteBody(BaseModel):
    tenant_id: str = "default"
    namespace: str
    layer: str = "L2"
    kind: str = "operator_note"
    title: str
    body: str
    structured: dict[str, Any] = Field(default_factory=dict)
    actor: str = "operator"
    purpose: str = "manual_write"
    correlation_id: str | None = None


class MemoryReadQuery(BaseModel):
    tenant_id: str = "default"
    repo_full_name: str
    query: str = ""
    correlation_id: str | None = None


@router.get("/health")
async def memory_health() -> dict[str, Any]:
    gateway = get_memory_gateway()
    return {
        "enabled": gateway.config.enabled,
        "backend": gateway.config.backend,
        "sqlite_path": gateway.config.sqlite_path,
        "quarantine_enabled": gateway.config.quarantine_enabled,
    }


@router.post("/records")
async def write_memory_record(
    body: MemoryWriteBody,
    _auth: dict = Depends(optional_auth),
) -> dict[str, Any]:
    gateway = get_memory_gateway()
    req = MemoryWriteRequest(
        tenant_id=body.tenant_id,
        namespace=body.namespace,
        layer=body.layer,
        kind=body.kind,
        title=body.title,
        body=body.body,
        structured=body.structured,
        actor=body.actor,
        purpose=body.purpose,
        correlation_id=body.correlation_id,
    )
    try:
        return gateway.write(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/context")
async def read_memory_context_api(
    body: MemoryReadQuery,
    _auth: dict = Depends(optional_auth),
) -> dict[str, Any]:
    return read_memory_context(
        tenant_id=body.tenant_id or tenant_from_repo(body.repo_full_name),
        repo_full_name=body.repo_full_name,
        query=body.query,
        correlation_id=body.correlation_id,
    )
