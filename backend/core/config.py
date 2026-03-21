from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "multi-agent-devops"
    app_env: str = Field(default="dev", alias="APP_ENV")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(default="https://api.openai.com/v1/chat/completions", alias="LLM_BASE_URL")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")

    database_url: str = Field(default="sqlite:///./devops_platform.db", alias="DATABASE_URL")
    queue_backend: str = Field(default="memory", alias="QUEUE_BACKEND")
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    agent_memory_enabled: bool = Field(default=False, alias="AGENT_MEMORY_ENABLED")
    retriever_backend: str = Field(default="none", alias="RETRIEVER_BACKEND")
    qa_mode: str = Field(default="simulated", alias="QA_MODE")
    qa_timeout_seconds: int = Field(default=30, alias="QA_TIMEOUT_SECONDS")
    auto_redeploy_on_blocked: bool = Field(default=True, alias="AUTO_REDEPLOY_ON_BLOCKED")
    auth_enabled: bool = Field(default=False, alias="AUTH_ENABLED")
    auth_api_keys_json: str = Field(default="{}", alias="AUTH_API_KEYS_JSON")
    github_token: str = Field(default="", alias="GITHUB_TOKEN")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
