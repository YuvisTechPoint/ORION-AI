from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from core.logging_config import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="Multi-Agent Multi-Modal DevOps Automation Platform",
        version="0.1.0",
        description="Prototype platform for AI-assisted DevOps workflow automation.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
