"""Prevent duplicate concurrent pipeline runs for the same commit."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_run import TERMINAL_STATUSES, VALID_STATUSES, PipelineRun

INFLIGHT_STATUSES = frozenset(VALID_STATUSES - TERMINAL_STATUSES)


async def find_inflight_run(
    db: AsyncSession,
    *,
    repo_full_name: str,
    commit_id: str,
) -> PipelineRun | None:
    row = (
        await db.execute(
            select(PipelineRun)
            .where(
                PipelineRun.repo_full_name == repo_full_name,
                PipelineRun.commit_id == commit_id,
                PipelineRun.status.in_(INFLIGHT_STATUSES),
            )
            .order_by(PipelineRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


def dedup_response(run: PipelineRun, executor: str) -> dict:
    return {
        "status": "duplicate",
        "pipeline_run_id": str(run.id),
        "commit_id": run.commit_id,
        "repo_full_name": run.repo_full_name,
        "executor": executor,
        "existing_status": run.status,
    }
