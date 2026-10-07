"""Webhook security fail-closed behavior."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.webhook_security import resolve_webhook_secret, verify_github_signature


def test_resolve_webhook_secret_dev_fallback():
    secret = resolve_webhook_secret(Settings(github_webhook_secret="", app_env="development"))
    assert secret == "test-webhook-secret"


def test_resolve_webhook_secret_production_raises(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    from app.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(HTTPException) as exc:
        resolve_webhook_secret(get_settings())
    assert exc.value.status_code == 503
    get_settings.cache_clear()


def test_verify_github_signature_roundtrip():
    body = b'{"repository":{"clone_url":"https://github.com/o/r.git"}}'
    secret = "test-webhook-secret"
    import hashlib
    import hmac

    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_github_signature(body, sig, secret)
    assert not verify_github_signature(body, "sha256=bad", secret)
