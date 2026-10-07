"""GitHub webhook HMAC validation — fail-closed in production."""

from __future__ import annotations

import hashlib
import hmac

from fastapi import HTTPException, status

from app.config import Settings, get_settings

_PLACEHOLDER_MARKERS = ("your-", "changeme", "your_webhook", "devops-approver-key", "ghp_your")


def _is_placeholder(value: str | None) -> bool:
    if not value or not value.strip():
        return True
    low = value.strip().lower()
    return any(marker in low for marker in _PLACEHOLDER_MARKERS)


def resolve_webhook_secret(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    secret = (cfg.github_webhook_secret or "").strip()
    if _is_placeholder(secret):
        if cfg.is_production:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GITHUB_WEBHOOK_SECRET is not configured",
            )
        return "test-webhook-secret"
    return secret


def verify_github_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
