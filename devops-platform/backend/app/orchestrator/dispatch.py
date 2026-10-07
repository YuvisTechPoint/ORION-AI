"""Route pipeline work to Celery when Redis is reachable, otherwise run inline in a background thread."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import redis

from app.config import get_settings
from app.orchestrator.pipeline_runner import _run_pipeline_impl, run_pipeline

logger = logging.getLogger(__name__)

_REDIS_CACHE: dict[str, Any] = {"ok": False, "checked": None}
_CACHE_SECONDS = 60.0
_threads: set[threading.Thread] = set()


def redis_available() -> bool:
    checked = _REDIS_CACHE["checked"]
    if checked is not None and time.monotonic() - float(checked) < _CACHE_SECONDS:
        return bool(_REDIS_CACHE["ok"])
    settings = get_settings()
    try:
        client = redis.from_url(settings.redis_url, socket_connect_timeout=1)
        client.ping()
        ok = True
        client.close()
    except Exception:
        ok = False
    _REDIS_CACHE.update(ok=ok, checked=time.monotonic())
    return ok


def executor_mode() -> str:
    mode = get_settings().pipeline_executor.strip().lower()
    if mode in ("celery", "inline"):
        return mode
    return "celery" if redis_available() else "inline"


def _run_inline(pipeline_id: str) -> None:
    try:
        _run_pipeline_impl(pipeline_id)
    except Exception:
        logger.exception("inline pipeline %s crashed", pipeline_id)


def dispatch_pipeline(pipeline_id: str, *, resume: bool = False) -> str:
    if resume:
        from uuid import UUID as _UUID

        from app.database_sync import SyncSessionLocal
        from app.models import PipelineRun

        db = SyncSessionLocal()
        try:
            run = db.query(PipelineRun).filter(PipelineRun.id == _UUID(str(pipeline_id))).first()
            if run is not None:
                meta = dict(run.metadata_json or {})
                meta["resume"] = True
                run.metadata_json = meta
                db.commit()
        finally:
            db.close()

    mode = executor_mode()
    if mode == "celery":
        run_pipeline.delay(pipeline_id)
    else:
        thread = threading.Thread(
            target=_run_inline,
            args=(pipeline_id,),
            name=f"pipeline-{pipeline_id}",
            daemon=True,
        )
        thread.start()
        _threads.add(thread)
        thread.join(timeout=0)

    logger.info("dispatched pipeline %s via %s executor", pipeline_id, mode)
    return mode
