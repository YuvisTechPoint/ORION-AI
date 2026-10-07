import hashlib
import hmac

from fastapi import Header, HTTPException, Request, status

from app.config import _is_placeholder, settings


def validate_github_signature(
    payload_body: bytes, signature_header: str | None, secret: str
) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), payload_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _webhook_secret() -> str:
    secret = (settings.github_webhook_secret or "").strip()
    if _is_placeholder(secret):
        if settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GITHUB_WEBHOOK_SECRET is not configured",
            )
        return "test-webhook-secret"
    return secret


def _github_app_webhook_secret() -> str:
    secret = (settings.github_app_webhook_secret or "").strip()
    if secret:
        return secret
    return _webhook_secret()


async def get_validated_github_payload(
    request: Request,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> bytes:
    body = await request.body()
    if not validate_github_signature(body, x_hub_signature_256, _webhook_secret()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid GitHub signature"
        )
    return body


async def get_validated_github_app_payload(
    request: Request,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> bytes:
    body = await request.body()
    if not validate_github_signature(body, x_hub_signature_256, _github_app_webhook_secret()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid GitHub App signature"
        )
    return body
