from typing import Any

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from api.routes import router
from api.text_tools import router as text_tools_router
from api.multimodal import router as multimodal_router
from api.intelligence import router as intelligence_router
from api.runtime import router as runtime_router
from api import auth as auth_routes
from core.config import check_required_env_vars, get_settings
from core.logging_config import configure_logging
from core.observability import RequestMetricsMiddleware, render_prometheus
from core.rate_limit import RateLimitMiddleware
from services.preflight import preflight_report


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    check_required_env_vars(settings)
    app = FastAPI(
        title="Multi-Agent Multi-Modal DevOps Automation Platform",
        version="0.1.0",
        description="Prototype platform for AI-assisted DevOps workflow automation.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        ],
        # Accept any localhost/127.0.0.1 dev port (Vite may auto-increment).
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Add session middleware after CORS so CORS preflight/headers are applied
    # before session handling. This avoids subtle browser-side failures when
    # requests include credentials (cookies) on cross-origin requests.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret_key,
        max_age=settings.oauth_token_expiry_hours * 3600,
        same_site="none" if settings.use_secure_session_cookies else "lax",
        https_only=settings.use_secure_session_cookies,
    )
    from core.correlation_middleware import CorrelationMiddleware

    app.add_middleware(CorrelationMiddleware)
    app.add_middleware(RequestMetricsMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        max_requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
        redis_url=settings.redis_url,
        backend=settings.rate_limit_backend,
    )
    app.include_router(router)
    app.include_router(auth_routes.router, prefix="/api/v1")
    app.include_router(multimodal_router, prefix="/api/v1/multimodal", tags=["multimodal"])
    app.include_router(text_tools_router, prefix="/api/v1")
    app.include_router(intelligence_router)
    app.include_router(runtime_router, prefix="/api/v1")

    @app.on_event("startup")
    def _ensure_webhook_ledger_table() -> None:
        from core.db import engine
        from models.db_models import WebhookDelivery

        WebhookDelivery.__table__.create(bind=engine, checkfirst=True)

    @app.get("/ready")
    def ready(settings=Depends(get_settings)) -> Any:
        from fastapi.responses import JSONResponse

        report = preflight_report(settings)
        code = 200 if report.get("healthy") else 503
        return JSONResponse({"ready": report.get("healthy"), **report}, status_code=code)

    @app.get("/metrics")
    def metrics() -> Any:
        from starlette.responses import PlainTextResponse

        return PlainTextResponse(render_prometheus(), media_type="text/plain; version=0.0.4; charset=utf-8")

    return app


app = create_app()
