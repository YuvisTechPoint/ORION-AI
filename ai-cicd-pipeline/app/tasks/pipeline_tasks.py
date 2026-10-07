import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from celery import Celery
from celery.signals import worker_init, worker_process_init
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.services.events import mark_celery_worker
from app.utils.logger import get_logger

logger = get_logger("celery.pipeline")


@worker_init.connect
@worker_process_init.connect
def _flag_worker_process(**_: Any) -> None:
    # Workers are separate processes from the API, so live events must also travel over Redis.
    mark_celery_worker()

celery_app = Celery(
    "ai_cicd_pipeline",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_max_retries=3,
    task_default_retry_delay=60,
    beat_schedule={
        "reap-stale-pipeline-runs": {
            "task": "reap_stale_runs",
            "schedule": 600.0,
        },
    },
)


def _run_async(factory: Callable[[], Awaitable[Any]]) -> Any:
    """Run a coroutine on a fresh loop; Celery workers are synchronous but agents are async."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(factory())
    finally:
        from app.database import async_engine

        # asyncpg connections are bound to the loop that created them.
        loop.run_until_complete(async_engine.dispose())
        loop.close()


def run_pipeline_sync(pipeline_run_id: str, github_token: str | None = None, resume: bool = False) -> None:
    from app.agents.orchestrator import orchestrator

    _run_async(
        lambda: orchestrator.execute_pipeline(pipeline_run_id, github_token=github_token, resume=resume)
    )


def _mark_run_failed_sync(pipeline_run_id: str, reason: str) -> None:
    from app.models.pipeline_run import PipelineRun

    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            run = session.get(PipelineRun, uuid.UUID(pipeline_run_id))
            if run is not None:
                run.status = "failed"
                run.error_message = reason[:8000]
                run.completed_at = datetime.now(timezone.utc)
                session.commit()
    except Exception as exc:
        logger.error("could not mark run %s failed: %s", pipeline_run_id, exc)
    finally:
        engine.dispose()


@celery_app.task(name="run_pipeline", bind=True, max_retries=3)
def run_pipeline_task(self, pipeline_run_id: str, github_token: str | None = None, resume: bool = False) -> None:
    logger.info("pipeline task start run=%s attempt=%d resume=%s", pipeline_run_id, self.request.retries, resume)
    try:
        run_pipeline_sync(pipeline_run_id, github_token=github_token, resume=resume)
    except Exception as exc:
        if self.request.retries < self.max_retries:
            logger.warning("pipeline task error run=%s, retrying: %s", pipeline_run_id, exc)
            raise self.retry(exc=exc, countdown=60)
        logger.error("pipeline task failed permanently run=%s: %s", pipeline_run_id, exc)
        _mark_run_failed_sync(pipeline_run_id, f"Pipeline task failed after retries: {exc}")
        raise
    logger.info("pipeline task end run=%s", pipeline_run_id)


@celery_app.task(name="run_monitoring")
def run_monitoring_task(pipeline_run_id: str) -> dict[str, Any]:
    from app.agents.orchestrator import orchestrator

    logger.info("monitoring task start run=%s", pipeline_run_id)
    return _run_async(lambda: orchestrator.run_monitoring(pipeline_run_id))


@celery_app.task(name="reap_stale_runs")
def reap_stale_runs_task() -> int:
    return reap_stale_runs()


def reap_stale_runs() -> int:
    """Mark runs stuck in a non-terminal state (e.g. worker crash) as failed."""
    from app.models.pipeline_run import TERMINAL_STATUSES, PipelineRun

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.stale_run_timeout_minutes)
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    reaped = 0
    try:
        with Session(engine) as session:
            rows = session.scalars(
                select(PipelineRun).where(
                    PipelineRun.status.not_in(TERMINAL_STATUSES | {"monitoring"}),
                    PipelineRun.updated_at < cutoff,
                )
            ).all()
            for run in rows:
                run.status = "failed"
                run.error_message = "Run exceeded stale timeout without progress"
                run.completed_at = datetime.now(timezone.utc)
                reaped += 1
            session.commit()
    finally:
        engine.dispose()
    if reaped:
        logger.warning("reaped %d stale pipeline runs", reaped)
    return reaped
