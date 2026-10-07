"""Persistent performance baselines per repository (p95, error rate)."""

from __future__ import annotations

import statistics
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.performance_baseline import PerformanceBaseline


async def get_baseline(
    db: AsyncSession,
    *,
    repo_full_name: str,
    profile: str = "standard",
    environment: str = "staging",
) -> dict[str, Any] | None:
    row = (
        await db.execute(
            select(PerformanceBaseline).where(
                PerformanceBaseline.repo_full_name == repo_full_name,
                PerformanceBaseline.profile == profile,
                PerformanceBaseline.environment == environment,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "repo_full_name": row.repo_full_name,
        "profile": row.profile,
        "environment": row.environment,
        "p95_ms": row.p95_ms,
        "error_rate_pct": row.error_rate_pct,
        "sample_count": row.sample_count,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "source": "persistent_store",
    }


async def upsert_baseline(
    db: AsyncSession,
    *,
    repo_full_name: str,
    stress_report: dict[str, Any],
    profile: str = "standard",
    environment: str = "staging",
    run_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    p95 = stress_report.get("p95_ms")
    if p95 is None and isinstance(stress_report.get("overall"), dict):
        p95 = stress_report["overall"].get("p95_ms")
    error_rate = stress_report.get("error_rate_pct")
    if error_rate is None and isinstance(stress_report.get("overall"), dict):
        error_rate = stress_report["overall"].get("failure_rate_pct")
    if p95 is None:
        return {"updated": False, "reason": "missing p95_ms"}

    row = (
        await db.execute(
            select(PerformanceBaseline).where(
                PerformanceBaseline.repo_full_name == repo_full_name,
                PerformanceBaseline.profile == profile,
                PerformanceBaseline.environment == environment,
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if row is None:
        row = PerformanceBaseline(
            repo_full_name=repo_full_name,
            profile=profile,
            environment=environment,
            p95_ms=float(p95),
            error_rate_pct=float(error_rate or 0.0),
            sample_count=1,
            last_run_id=run_id,
            updated_at=now,
        )
        db.add(row)
    else:
        samples = [row.p95_ms, float(p95)]
        row.p95_ms = float(statistics.median(samples))
        if error_rate is not None:
            row.error_rate_pct = float(statistics.median([row.error_rate_pct, float(error_rate)]))
        row.sample_count = int(row.sample_count or 0) + 1
        row.last_run_id = run_id
        row.updated_at = now

    await db.flush()
    return {
        "updated": True,
        "p95_ms": row.p95_ms,
        "error_rate_pct": row.error_rate_pct,
        "sample_count": row.sample_count,
        "source": "persistent_store",
    }
