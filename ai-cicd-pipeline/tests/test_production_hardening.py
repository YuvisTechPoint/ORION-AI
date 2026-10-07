"""Production hardening checklist tests."""

import pytest

from app.config import Settings
from app.utils.production_hardening import evaluate_production_hardening


def _apply_production_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    env = {
        "APP_ENV": "production",
        "API_REQUIRE_AUTH": "true",
        "SECRET_KEY": "x" * 40,
        "SESSION_SECRET_KEY": "y" * 40,
        "GITHUB_WEBHOOK_SECRET": "dedicated-webhook-secret-value",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@db.example.com:5432/orion",
        "AUTH_API_KEYS_JSON": '{"ops-key":{"user_id":"ops","roles":["operator"]}}',
        "DEPLOY_MODE": "auto",
        "CORS_ORIGINS": "https://orion.example.com",
    }
    env.update(overrides)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_hardening_dev_not_ready_for_production(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("API_REQUIRE_AUTH", "false")
    cfg = Settings()
    report = evaluate_production_hardening(cfg)
    assert report["production_mode"] is False
    assert report["ready_for_production"] is False
    assert "app_env_production" in report["critical_failures"]


def test_hardening_production_passes_with_secure_config(monkeypatch: pytest.MonkeyPatch):
    _apply_production_env(monkeypatch)
    cfg = Settings()
    report = evaluate_production_hardening(cfg)
    assert report["production_mode"] is True
    assert report["ready_for_production"] is True
    assert report["critical_failures"] == []


def test_secure_session_cookies_disabled_for_local_sim(monkeypatch: pytest.MonkeyPatch):
    _apply_production_env(monkeypatch)
    monkeypatch.setenv("PRODUCTION_LOCAL_SIM", "true")
    cfg = Settings()
    assert cfg.is_production is True
    assert cfg.use_secure_session_cookies is False


def test_secure_session_cookies_enabled_for_real_production(monkeypatch: pytest.MonkeyPatch):
    _apply_production_env(monkeypatch)
    monkeypatch.setenv("PRODUCTION_LOCAL_SIM", "false")
    cfg = Settings()
    assert cfg.use_secure_session_cookies is True


def test_validate_startup_rejects_sqlite_in_production(monkeypatch: pytest.MonkeyPatch):
    _apply_production_env(monkeypatch, DATABASE_URL="sqlite+aiosqlite:///./orion.db")
    monkeypatch.setenv("PRODUCTION_LOCAL_SIM", "false")
    cfg = Settings()
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        cfg.validate_startup()
