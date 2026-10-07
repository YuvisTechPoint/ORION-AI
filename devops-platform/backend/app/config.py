from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_MARKERS = ("your-", "changeme", "your_webhook", "devops-approver-key", "ghp_your")


def _is_placeholder(value: str | None) -> bool:
    if not value or not value.strip():
        return True
    low = value.strip().lower()
    return any(marker in low for marker in _PLACEHOLDER_MARKERS)


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

    github_webhook_secret: str = Field(default="", alias="GITHUB_WEBHOOK_SECRET")
    deployment_api_key: str = Field(default="devops-approver-key", alias="DEPLOYMENT_API_KEY")
    orion_api_key: str = Field(default="", alias="ORION_API_KEY")
    orion_api_url: str = Field(default="http://127.0.0.1:8001", alias="ORION_API_URL")
    api_require_auth: bool = Field(default=False, alias="API_REQUIRE_AUTH")
    app_env: str = Field(default="development", alias="APP_ENV")
    slack_webhook_url: str = Field(default="", alias="SLACK_WEBHOOK_URL")
    slo_alert_slack_enabled: bool = Field(default=True, alias="SLO_ALERT_SLACK_ENABLED")
    slo_alert_cooldown_seconds: int = Field(default=3600, alias="SLO_ALERT_COOLDOWN_SECONDS")
    auto_pr_enabled: bool = Field(default=False, alias="AUTO_PR_ENABLED")
    deploy_mode: str = Field(default="auto", alias="DEPLOY_MODE")
    pipeline_executor: str = Field(default="auto", alias="PIPELINE_EXECUTOR")
    rate_limit_requests: int = Field(default=60, alias="RATE_LIMIT_REQUESTS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    production_local_sim: bool = Field(default=False, alias="PRODUCTION_LOCAL_SIM")
    devops_ui_url: str = Field(default="http://127.0.0.1:3000", alias="DEVOPS_UI_URL")
    hub_url: str = Field(default="http://127.0.0.1:5180", alias="HUB_URL")
    canonical_api_url: str = Field(default="http://127.0.0.1:8000", alias="CANONICAL_API_URL")
    canonical_ui_url: str = Field(default="http://127.0.0.1:5173", alias="CANONICAL_UI_URL")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @model_validator(mode="after")
    def _production_defaults(self) -> "Settings":
        if self.is_production and not self.api_require_auth:
            object.__setattr__(self, "api_require_auth", True)
        return self

    def validate_startup(self) -> None:
        if not self.is_production:
            return
        problems: list[str] = []
        if _is_placeholder(self.github_webhook_secret):
            problems.append("GITHUB_WEBHOOK_SECRET must be set in production.")
        if _is_placeholder(self.deployment_api_key):
            problems.append("DEPLOYMENT_API_KEY must be set in production.")
        if "sqlite" in (self.database_url or "").lower() and not self.production_local_sim:
            problems.append("DATABASE_URL must use PostgreSQL in production.")
        if problems:
            raise RuntimeError(" ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
