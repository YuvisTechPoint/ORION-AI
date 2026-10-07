import logging
import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _settings_env_files() -> tuple[str, ...]:
    backend_dir = Path(__file__).resolve().parents[1]
    if os.getenv("APP_ENV", "").lower() in {"production", "prod"}:
        return (str(backend_dir / ".env.production"), str(backend_dir / ".env"))
    return (str(backend_dir / ".env"),)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_settings_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "multi-agent-devops"
    app_env: str = Field(default="dev", alias="APP_ENV")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    huggingface_api_key: str = Field(default="", alias="HUGGINGFACE_API_KEY")
    llm_base_url: str = Field(default="https://api.openai.com/v1/chat/completions", alias="LLM_BASE_URL")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_mode: str = Field(default="auto", alias="LLM_MODE")
    hf_api_url: str = Field(default="https://api-inference.huggingface.co/models", alias="HF_API_URL")
    llm_agent_models_json: str = Field(default="{}", alias="LLM_AGENT_MODELS_JSON")
    anthropic_agent_models_json: str = Field(default="{}", alias="ANTHROPIC_AGENT_MODELS_JSON")

    database_url: str = Field(default="sqlite:///./devops_platform.db", alias="DATABASE_URL")
    queue_backend: str = Field(default="memory", alias="QUEUE_BACKEND")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    agent_memory_enabled: bool = Field(default=False, alias="AGENT_MEMORY_ENABLED")
    retriever_backend: str = Field(default="hybrid", alias="RETRIEVER_BACKEND")
    qa_mode: str = Field(default="simulated", alias="QA_MODE")
    qa_timeout_seconds: int = Field(default=30, alias="QA_TIMEOUT_SECONDS")
    auto_redeploy_on_blocked: bool = Field(default=True, alias="AUTO_REDEPLOY_ON_BLOCKED")
    auto_pr_enabled: bool = Field(default=True, alias="AUTO_PR_ENABLED")
    auth_enabled: bool = Field(default=False, alias="AUTH_ENABLED")
    api_require_auth: bool = Field(default=False, alias="API_REQUIRE_AUTH")
    auth_api_keys_json: str = Field(default="{}", alias="AUTH_API_KEYS_JSON")
    pipeline_executor: str = Field(default="auto", alias="PIPELINE_EXECUTOR")
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    github_webhook_secret: str = Field(default="", alias="GITHUB_WEBHOOK_SECRET")
    github_client_id: str = Field(default="", alias="GITHUB_CLIENT_ID")
    github_client_secret: str = Field(default="", alias="GITHUB_CLIENT_SECRET")
    app_port: int = Field(default=8000, alias="APP_PORT")
    github_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/auth/github/callback",
        alias="GITHUB_REDIRECT_URI",
    )
    session_secret_key: str = Field(
        default="orion-change-this-to-random-32-chars!!",
        alias="SESSION_SECRET_KEY",
    )
    frontend_url: str = Field(default="http://localhost:5173", alias="FRONTEND_URL")
    oauth_token_expiry_hours: int = Field(default=24, alias="OAUTH_TOKEN_EXPIRY_HOURS")
    sync_database_url: str = Field(default="", alias="SYNC_DATABASE_URL")
    slack_webhook_url: str = Field(default="", alias="SLACK_WEBHOOK_URL")
    slo_alert_slack_enabled: bool = Field(default=True, alias="SLO_ALERT_SLACK_ENABLED")
    slo_alert_cooldown_seconds: int = Field(default=3600, alias="SLO_ALERT_COOLDOWN_SECONDS")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-3-7-sonnet-latest", alias="ANTHROPIC_MODEL")
    require_runtime_secrets: bool = Field(default=False, alias="REQUIRE_RUNTIME_SECRETS")
    multimodal_auth_required: bool = Field(default=False, alias="MULTIMODAL_AUTH_REQUIRED")
    multimodal_max_file_bytes: int = Field(default=8_388_608, alias="MULTIMODAL_MAX_FILE_BYTES")
    multimodal_timeout_seconds: int = Field(default=45, alias="MULTIMODAL_TIMEOUT_SECONDS")
    production_local_sim: bool = Field(default=False, alias="PRODUCTION_LOCAL_SIM")
    hub_url: str = Field(default="http://127.0.0.1:5180", alias="HUB_URL")
    orion_api_url: str = Field(default="http://127.0.0.1:8001", alias="ORION_API_URL")
    devops_api_url: str = Field(default="http://127.0.0.1:8002", alias="DEVOPS_API_URL")
    devops_ui_url: str = Field(default="http://127.0.0.1:3000", alias="DEVOPS_UI_URL")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def use_secure_session_cookies(self) -> bool:
        return self.is_production and not self.production_local_sim


def get_settings() -> Settings:
    return Settings()


def check_required_env_vars(settings: Settings | None = None) -> None:
    """Validate required runtime secrets and raise clear startup errors when missing."""
    logger = logging.getLogger(__name__)
    cfg = settings or get_settings()

    llm_key = (cfg.huggingface_api_key or cfg.llm_api_key or "").strip()
    anthropic_key = (cfg.anthropic_api_key or "").strip()
    github_token = (cfg.github_token or "").strip()

    missing_messages: list[str] = []
    if not llm_key:
        missing_messages.append(
            "Missing LLM key: set HUGGINGFACE_API_KEY (preferred) or LLM_API_KEY in environment/.env."
        )
    if not anthropic_key:
        missing_messages.append(
            "Missing ANTHROPIC_API_KEY: set ANTHROPIC_API_KEY in environment/.env for Auto-PR AI fix generation."
        )
    if not github_token:
        missing_messages.append(
            "Missing GITHUB_TOKEN: set GITHUB_TOKEN in environment/.env for repository automation operations."
        )

    production = cfg.app_env.lower() in {"prod", "production"}
    must_fail = production or cfg.require_runtime_secrets
    for message in missing_messages:
        if must_fail:
            logger.error(message)
        else:
            logger.warning("%s (continuing because APP_ENV=%s)", message, cfg.app_env)

    if missing_messages and must_fail:
        raise EnvironmentError(os.linesep.join(missing_messages))

    if production:
        session_key = (cfg.session_secret_key or "").strip()
        if session_key.startswith("orion-change-this"):
            raise EnvironmentError(
                "SESSION_SECRET_KEY must be changed from the default placeholder in production."
            )
        webhook = (cfg.github_webhook_secret or "").strip()
        if not webhook or webhook.startswith("your-") or webhook == "your-webhook-secret":
            raise EnvironmentError("GITHUB_WEBHOOK_SECRET must be set in production.")
        if not cfg.api_require_auth and not cfg.auth_enabled:
            raise EnvironmentError(
                "Enable API_REQUIRE_AUTH or AUTH_ENABLED in production."
            )
