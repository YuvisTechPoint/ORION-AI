"""Production readiness and hardening APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.routes.auth import optional_auth
from app.config import settings
from app.services.readiness import readiness_report
from app.utils.production_hardening import evaluate_production_hardening

router = APIRouter(prefix="/production", tags=["ORION Production"])


@router.get("/checklist")
async def production_checklist(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    report = evaluate_production_hardening()
    return {"generated_at": datetime.now(timezone.utc).isoformat(), **report}


@router.get("/ready")
async def production_ready(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    hardening = evaluate_production_hardening()
    runtime = await readiness_report()
    ready = bool(runtime.get("ready")) and hardening.get("ready_for_production")
    if not ready and settings.is_production:
        raise HTTPException(
            status_code=503,
            detail={
                "ready": False,
                "runtime": runtime,
                "hardening": hardening,
            },
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ready": ready,
        "runtime": runtime,
        "hardening": hardening,
    }
