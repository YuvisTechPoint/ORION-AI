import asyncio

from celery import Celery

from app.config import settings

celery_app = Celery(
    "orion",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


def run_pipeline_sync(pipeline_run_id: str, github_token: str | None = None) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from app.agents.orchestrator import orchestrator

        loop.run_until_complete(
            orchestrator.execute_pipeline(pipeline_run_id, github_token=github_token)
        )
    finally:
        loop.close()


@celery_app.task(name="run_pipeline", bind=True, max_retries=3)
def run_pipeline_task(self, pipeline_run_id: str, github_token: str | None = None) -> None:
    try:
        run_pipeline_sync(pipeline_run_id, github_token=github_token)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
