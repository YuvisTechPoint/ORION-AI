"""Enterprise SSO readiness assessment (GitHub OAuth + optional SAML/OIDC)."""

from __future__ import annotations

from typing import Any

from app.config import settings


def _configured(value: str | None, *markers: str) -> bool:
    if not value or not value.strip():
        return False
    low = value.strip().lower()
    return not any(m in low for m in markers)


def assess_sso_readiness() -> dict[str, Any]:
    github_oauth = _configured(settings.github_client_id, "your-oauth") and _configured(
        settings.github_client_secret, "your-oauth"
    )
    saml = _configured(settings.sso_saml_entity_id, "your-", "example")
    saml_meta = _configured(getattr(settings, "sso_saml_metadata_url", ""), "your-", "example")
    oidc = _configured(settings.sso_oidc_issuer, "your-", "example")
    oidc_client = _configured(getattr(settings, "sso_oidc_client_id", ""), "your-", "example")

    providers: list[dict[str, Any]] = [
        {
            "provider": "github_oauth",
            "enabled": github_oauth,
            "status": "active" if github_oauth else "not_configured",
        },
        {
            "provider": "saml",
            "enabled": saml,
            "status": "configured" if saml else "not_configured",
            "entity_id": settings.sso_saml_entity_id if saml else None,
            "metadata_url": settings.sso_saml_metadata_url if saml_meta else None,
        },
        {
            "provider": "oidc",
            "enabled": oidc,
            "status": "configured" if oidc else "not_configured",
            "issuer": settings.sso_oidc_issuer if oidc else None,
            "client_id": settings.sso_oidc_client_id if oidc_client else None,
        },
    ]

    active = [p["provider"] for p in providers if p["enabled"]]
    recommendations: list[str] = []
    if not github_oauth:
        recommendations.append("Configure GitHub OAuth client ID/secret for interactive login.")
    if not saml and not oidc:
        recommendations.append("Set SSO_SAML_ENTITY_ID or SSO_OIDC_ISSUER for enterprise IdP federation.")
    if settings.is_production and not settings.api_require_auth:
        recommendations.append("Enable API_REQUIRE_AUTH in production for tenant isolation.")

    return {
        "providers": providers,
        "active_providers": active,
        "enterprise_ready": len(active) >= 1 and (saml or oidc or settings.api_require_auth),
        "recommendations": recommendations,
        "summary": (
            f"SSO readiness: {len(active)} provider(s) active — {', '.join(active) or 'none'}."
        ),
    }
