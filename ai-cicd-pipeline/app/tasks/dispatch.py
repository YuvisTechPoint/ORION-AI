"""Route pipeline work to Celery when a broker is reachable, otherwise run it inside the API process.

PIPELINE_EXECUTOR=celery|inline forces a mode; the default "auto" picks per dispatch.
"""

import asyncio
import uuid
from collections.abc import Coroutine
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.services.events import publish_event, redis_available
from app.utils.logger import get_logger

logger = get_logger("dispatch")

_background: set[asyncio.Task[Any]] = set()
_semaphores: dict[int, asyncio.Semaphore] = {}


def executor_mode() -> str:
    mode = settings.pipeline_executor.strip().lower()
    if mode in ("celery", "inline"):
        return mode
    return "celery" if redis_available() else "inline"


def _semaphore() -> asyncio.Semaphore:
    loop_id = id(asyncio.get_running_loop())
    sem = _semaphores.get(loop_id)
    if sem is None:
        sem = asyncio.Semaphore(max(1, settings.pipeline_inline_concurrency))
        _semaphores[loop_id] = sem
    return sem


def _spawn(coro: Coroutine[Any, Any, Any], name: str) -> None:
    task = asyncio.get_running_loop().create_task(coro, name=name)
    _background.add(task)
    task.add_done_callback(_background.discard)


def inline_tasks() -> set[asyncio.Task[Any]]:
    return set(_background)


def cancel_inline(run_id: uuid.UUID | str) -> bool:
    name = f"pipeline-{run_id}"
    cancelled = False
    for task in list(_background):
        if task.get_name() == name and not task.done():
            task.cancel()
            cancelled = True
    return cancelled


async def _mark_failed(run_id: str, reason: str) -> None:
    from app.database import AsyncSessionLocal
    from app.models.pipeline_run import TERMINAL_STATUSES, PipelineRun

    try:
        async with AsyncSessionLocal() as db:
            run = await db.get(PipelineRun, uuid.UUID(run_id))
            if run is not None and run.status not in TERMINAL_STATUSES:
                run.status = "failed"
                run.error_message = reason[:8000]
                run.completed_at = datetime.now(timezone.utc)
                await db.commit()
                publish_event(run_id, {"kind": "stage-update", "stage": "failed", "status": "failed"})
    except Exception as exc:  # noqa: BLE001
        logger.error("could not mark run %s failed: %s", run_id, exc)


def dispatch_pipeline(
    run_id: uuid.UUID | str, github_token: str | None = None, *, resume: bool = False
) -> str:
    run_id = str(run_id)
    mode = executor_mode()
    if mode == "celery":
        from app.tasks.pipeline_tasks import run_pipeline_task

        run_pipeline_task.delay(run_id, github_token=github_token, resume=resume)
    else:
        _spawn(_run_pipeline_inline(run_id, github_token, resume), f"pipeline-{run_id}")
    logger.info("dispatched pipeline %s via %s executor (resume=%s)", run_id, mode, resume)
    return mode


async def _run_pipeline_inline(run_id: str, github_token: str | None, resume: bool = False) -> None:
    from app.agents.orchestrator import orchestrator

    async with _semaphore():
        try:
            await orchestrator.execute_pipeline(run_id, github_token=github_token, resume=resume)
        except Exception as exc:  # noqa: BLE001 - execute_pipeline handles stage errors; this is the last resort
            logger.exception("inline pipeline %s crashed", run_id)
            await _mark_failed(run_id, f"Pipeline crashed: {exc}")


async def _run_monitoring_inline(run_id: str) -> None:
    from app.agents.orchestrator import orchestrator

    try:
        await orchestrator.run_monitoring(run_id)
    except Exception:  # noqa: BLE001
        logger.exception("inline monitoring for %s crashed", run_id)


def dispatch_monitoring(run_id: uuid.UUID | str) -> str:
    run_id = str(run_id)
    mode = executor_mode()
    if mode == "celery":
        from app.tasks.pipeline_tasks import run_monitoring_task

        run_monitoring_task.delay(run_id)
    else:
        _spawn(_run_monitoring_inline(run_id), f"monitoring-{run_id}")
    return mode


async def recover_interrupted_runs() -> list[str]:
    """With the inline executor, runs die with the process. Settle runs a restart interrupted and
    return the ids of runs that never started so the caller can dispatch them again."""
    from app.database import AsyncSessionLocal
    from app.models.pipeline_run import TERMINAL_STATUSES, PipelineRun

    requeue: list[str] = []
    settled = 0
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(PipelineRun).where(PipelineRun.status.not_in(TERMINAL_STATUSES)))
        ).scalars().all()
        for run in rows:
            if run.status == "queued":
                requeue.append(str(run.id))
                continue
            if run.status == "monitoring":
                run.status = "deployed"
            else:
                run.status = "failed"
                run.error_message = "Interrupted: the API restarted while this run was in progress. Retry it."
                run.completed_at = datetime.now(timezone.utc)
            settled += 1
        await db.commit()
    if settled or requeue:
        logger.warning("restart recovery: settled %d interrupted run(s), re-queueing %d", settled, len(requeue))
    return requeue
