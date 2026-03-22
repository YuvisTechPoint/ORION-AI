from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "devops_platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)

# Register Celery tasks (shared_task bindings)
import app.orchestrator.pipeline_runner  # noqa: E402, F401
