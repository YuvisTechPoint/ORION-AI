from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    app_env: str = Field(default="development")
    app_port: int = Field(default=8001)
    secret_key: str = Field(default="orion-secret-key-min-32-chars-here")
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/aicicd"
    )
    sync_database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/aicicd"
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    anthropic_api_key: str = Field(default="sk-ant-api03-your-key-here")
    anthropic_model: str = Field(default="claude-sonnet-4-20250514")
    github_webhook_secret: str = Field(default="your-webhook-secret")
    github_token: str = Field(default="ghp_your-personal-access-token")
    github_owner: str = Field(default="your-github-username")
    github_client_id: str = Field(default="your-oauth-app-client-id")
    github_client_secret: str = Field(default="your-oauth-app-client-secret")
    github_redirect_uri: str = Field(
        default="http://localhost:8001/api/v1/auth/github/callback"
    )
    session_secret_key: str = Field(default="orion-super-secret-session-key-abc123")
    frontend_url: str = Field(default="http://localhost:5173")
    oauth_token_expiry_hours: int = Field(default=24)
    slack_webhook_url: str = Field(
        default="https://hooks.slack.com/services/xxx/yyy/zzz"
    )
    staging_url: str = Field(default="http://localhost:8080")
    container_registry: str = Field(default="your-registry.io")
    app_name: str = Field(default="orion-app")
    deploy_environment: str = Field(default="staging")
    max_security_severity: str = Field(default="medium")
    stress_test_users: int = Field(default=1000)
    stress_test_duration: int = Field(default=60)
    stress_test_spawn_rate: int = Field(default=50)
    monitoring_poll_interval_seconds: int = Field(default=30)
    monitoring_window_minutes: int = Field(default=5)
    health_check_timeout_seconds: int = Field(default=180)
    nginx_mode: str = Field(default="development")
    flower_basic_auth_user: str = Field(default="admin")
    flower_basic_auth_password: str = Field(default="orion_admin")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def database_url_sync(self) -> str:
        return self.sync_database_url


settings = Settings()
