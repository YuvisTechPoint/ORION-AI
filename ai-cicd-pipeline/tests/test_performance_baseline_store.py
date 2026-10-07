"""Persistent performance baseline store tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_run import PipelineRun
from app.services.performance_baseline_store import get_baseline, upsert_baseline


@pytest.mark.asyncio
async def test_baseline_upsert_and_read(db_session: AsyncSession, pipeline_run: PipelineRun):
    run = pipeline_run
    first = await upsert_baseline(
        db_session,
        repo_full_name=run.repo_full_name,
        stress_report={"p95_ms": 420.0, "error_rate_pct": 0.5},
        run_id=run.id,
    )
    assert first["updated"] is True
    assert first["p95_ms"] == 420.0
    await db_session.commit()

    second = await upsert_baseline(
        db_session,
        repo_full_name=run.repo_full_name,
        stress_report={"p95_ms": 500.0, "error_rate_pct": 0.6},
        run_id=uuid.uuid4(),
    )
    assert second["updated"] is True
    assert second["p95_ms"] == 460.0
    await db_session.commit()

    stored = await get_baseline(db_session, repo_full_name=run.repo_full_name)
    assert stored is not None
    assert stored["p95_ms"] == 460.0
    assert stored["sample_count"] == 2
