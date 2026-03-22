from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-20250514", alias="ANTHROPIC_MODEL")
    github_token: str = Field(default="", alias="GITHUB_TOKEN")

    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="devops_platform", alias="POSTGRES_DB")
    postgres_user: str = Field(default="devops", alias="POSTGRES_USER")
    postgres_password: str = Field(default="devops_secret", alias="POSTGRES_PASSWORD")

    database_url: str = Field(
        default="postgresql+asyncpg://devops:devops_secret@localhost:5432/devops_platform",
        alias="DATABASE_URL",
    )
    sync_database_url: str = Field(
        default="postgresql://devops:devops_secret@localhost:5432/devops_platform",
        alias="SYNC_DATABASE_URL",
    )

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://localhost:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/1", alias="CELERY_RESULT_BACKEND")

    github_webhook_secret: str = Field(default="your_webhook_secret", alias="GITHUB_WEBHOOK_SECRET")
    deployment_api_key: str = Field(default="devops-approver-key", alias="DEPLOYMENT_API_KEY")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
