from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from api.routes import router
from api.multimodal import router as multimodal_router
from api import auth as auth_routes
from core.config import get_settings
from core.logging_config import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="Multi-Agent Multi-Modal DevOps Automation Platform",
        version="0.1.0",
        description="Prototype platform for AI-assisted DevOps workflow automation.",
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret_key,
        max_age=settings.oauth_token_expiry_hours * 3600,
        same_site="lax",
        https_only=False,
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
    app.include_router(router)
    app.include_router(auth_routes.router, prefix="/api/v1")
    app.include_router(multimodal_router, prefix="/api/v1/multimodal", tags=["multimodal"])
    return app


app = create_app()
