from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "multi-agent-devops"
    app_env: str = Field(default="dev", alias="APP_ENV")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(default="https://api.openai.com/v1/chat/completions", alias="LLM_BASE_URL")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    hf_api_url: str = Field(default="https://api-inference.huggingface.co/models", alias="HF_API_URL")
    llm_agent_models_json: str = Field(default="{}", alias="LLM_AGENT_MODELS_JSON")
    anthropic_agent_models_json: str = Field(default="{}", alias="ANTHROPIC_AGENT_MODELS_JSON")

    database_url: str = Field(default="sqlite:///./devops_platform.db", alias="DATABASE_URL")
    queue_backend: str = Field(default="memory", alias="QUEUE_BACKEND")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    agent_memory_enabled: bool = Field(default=False, alias="AGENT_MEMORY_ENABLED")
    retriever_backend: str = Field(default="none", alias="RETRIEVER_BACKEND")
    qa_mode: str = Field(default="real", alias="QA_MODE")
    qa_timeout_seconds: int = Field(default=30, alias="QA_TIMEOUT_SECONDS")
    auto_redeploy_on_blocked: bool = Field(default=True, alias="AUTO_REDEPLOY_ON_BLOCKED")
    auto_pr_enabled: bool = Field(default=True, alias="AUTO_PR_ENABLED")
    auth_enabled: bool = Field(default=False, alias="AUTH_ENABLED")
    auth_api_keys_json: str = Field(default="{}", alias="AUTH_API_KEYS_JSON")
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
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
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-3-7-sonnet-latest", alias="ANTHROPIC_MODEL")


def get_settings() -> Settings:
    return Settings()
