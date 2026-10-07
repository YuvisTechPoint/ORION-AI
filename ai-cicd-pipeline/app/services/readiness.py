"""Production readiness probes for ORION."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text

from app.config import settings
from app.database import AsyncSessionLocal
from app.services.events import redis_available
from app.tasks.dispatch import executor_mode


async def probe_database() -> tuple[bool, str]:
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return True, "database ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"database error: {exc}"


async def readiness_report() -> dict[str, Any]:
    db_ok, db_msg = await probe_database()
    redis_ok = await asyncio.to_thread(redis_available)
    executor = executor_mode()
    checks = {
        "database": {"ok": db_ok, "message": db_msg},
        "redis": {"ok": redis_ok, "message": "redis reachable" if redis_ok else "redis unreachable"},
        "executor": {"ok": True, "message": executor},
    }
    if executor == "celery" and not redis_ok:
        checks["executor"] = {"ok": False, "message": "celery executor requires redis"}
    ready = db_ok and checks["executor"]["ok"]
    if settings.pipeline_executor.strip().lower() == "celery":
        ready = ready and redis_ok
    return {
        "ready": ready,
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "environment": settings.app_env,
        "checks": checks,
    }
