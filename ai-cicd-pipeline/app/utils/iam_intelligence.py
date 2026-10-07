"""Enterprise IAM intelligence — SSO readiness, RBAC hygiene, and gate evaluation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.utils.enterprise_sso import assess_sso_readiness
from app.utils.iam_registry import resolve_iam_policy
from app.utils.tenant_rbac import resolve_tenant_context

_PLACEHOLDER_MARKERS = ("your-", "example", "changeme", "placeholder", "orion-super-secret")


def _configured(value: str | None, *extra_markers: str) -> bool:
    if not value or not str(value).strip():
        return False
    low = str(value).strip().lower()
    markers = _PLACEHOLDER_MARKERS + tuple(extra_markers)
    return not any(m in low for m in markers)


def assess_session_hardening() -> dict[str, Any]:
    secret = settings.session_secret_key or ""
    weak_secret = not _configured(secret) or secret.startswith("orion-super-secret")
    issues: list[str] = []
    score = 100

    if weak_secret:
        issues.append("SESSION_SECRET_KEY is default or placeholder — rotate before production.")
        score -= 35
    elif len(secret) < 32:
        issues.append("SESSION_SECRET_KEY shorter than 32 characters.")
        score -= 15

    if settings.is_production and not settings.api_require_auth:
        issues.append("API_REQUIRE_AUTH disabled in production.")
        score -= 25

    if settings.rate_limit_requests <= 0:
        issues.append("Rate limiting disabled (RATE_LIMIT_REQUESTS <= 0).")
        score -= 10

    return {
        "session_secret_configured": not weak_secret,
        "session_secret_length": len(secret),
        "api_require_auth": settings.api_require_auth,
        "rate_limit_requests": settings.rate_limit_requests,
        "issues": issues,
        "hardening_score": max(0, score),
        "summary": f"Session hardening {max(0, score)}% — API auth={'on' if settings.api_require_auth else 'off'}.",
    }


def assess_api_key_hygiene() -> dict[str, Any]:
    raw = (settings.auth_api_keys_json or "").strip()
    issues: list[str] = []
    keys: list[dict[str, Any]] = []

    if not raw or raw == "{}":
        legacy = _configured(settings.orion_api_key)
        if legacy:
            keys.append({"user_id": "legacy", "roles": ["admin", "operator"], "source": "ORION_API_KEY"})
        else:
            issues.append("No AUTH_API_KEYS_JSON or ORION_API_KEY configured.")
    else:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for key_id, meta in parsed.items():
                    if not isinstance(meta, dict):
                        continue
                    roles = meta.get("roles") or []
                    keys.append(
                        {
                            "key_id": key_id[:8] + "…" if len(key_id) > 8 else key_id,
                            "user_id": meta.get("user_id"),
                            "roles": roles,
                            "source": "AUTH_API_KEYS_JSON",
                        }
                    )
        except json.JSONDecodeError:
            issues.append("AUTH_API_KEYS_JSON is not valid JSON.")

    role_counts: dict[str, int] = {}
    for row in keys:
        for role in row.get("roles") or []:
            role_counts[str(role)] = role_counts.get(str(role), 0) + 1

    if settings.api_require_auth and not keys:
        issues.append("API auth enabled but no API keys configured.")
    if role_counts.get("admin", 0) > 3:
        issues.append("More than 3 admin API keys — review least-privilege assignment.")

    score = 100 - min(50, len(issues) * 15)
    return {
        "key_count": len(keys),
        "role_distribution": role_counts,
        "keys": keys[:12],
        "issues": issues,
        "hygiene_score": max(0, score),
        "summary": f"API key hygiene {max(0, score)}% — {len(keys)} key(s), roles {role_counts or 'none'}.",
    }


def assess_mfa_readiness() -> dict[str, Any]:
    """MFA is delegated to IdP when SAML/OIDC is configured."""
    saml = _configured(settings.sso_saml_entity_id)
    oidc = _configured(settings.sso_oidc_issuer)
    idp_mfa_capable = saml or oidc
    required = settings.iam_mfa_required

    issues: list[str] = []
    if required and not idp_mfa_capable:
        issues.append("IAM_MFA_REQUIRED but no SAML/OIDC IdP configured for federated MFA.")
    status = "ready" if (not required or idp_mfa_capable) else "gap"

    return {
        "mfa_required": required,
        "idp_mfa_capable": idp_mfa_capable,
        "status": status,
        "issues": issues,
        "summary": (
            f"MFA readiness {status}: required={required}, IdP federation={'yes' if idp_mfa_capable else 'no'}."
        ),
    }


def compute_iam_readiness_score(
    *,
    sso: dict[str, Any],
    session: dict[str, Any],
    api_keys: dict[str, Any],
    mfa: dict[str, Any],
    tenant: dict[str, Any],
) -> int:
    sso_pts = 25 if sso.get("enterprise_ready") else (10 if sso.get("active_providers") else 0)
    session_pts = int(session.get("hardening_score", 0) * 0.25)
    key_pts = int(api_keys.get("hygiene_score", 0) * 0.20)
    mfa_pts = 15 if mfa.get("status") == "ready" else 0
    rbac_pts = 15 if tenant.get("rbac_enforced") else 5
    return min(100, sso_pts + session_pts + key_pts + mfa_pts + rbac_pts)


def evaluate_iam_gates(
    *,
    policy: dict[str, Any],
    readiness_score: int,
    sso: dict[str, Any],
    session: dict[str, Any],
    mfa: dict[str, Any],
) -> dict[str, Any]:
    violations: list[str] = []
    warnings: list[str] = []

    min_score = float(policy.get("min_readiness_score") or 0)
    if readiness_score < min_score:
        violations.append(f"IAM readiness {readiness_score}% below minimum {min_score:.0f}%")

    if policy.get("require_api_auth") and not session.get("api_require_auth"):
        violations.append("API_REQUIRE_AUTH required by IAM policy but disabled")

    if policy.get("require_sso"):
        providers = sso.get("active_providers") or []
        has_federation = any(p in providers for p in ("saml", "oidc"))
        if not has_federation:
            violations.append("Enterprise SSO (SAML/OIDC) required but not configured")

    if policy.get("require_mfa") and mfa.get("status") != "ready":
        violations.append("MFA required but IdP federation not ready")

    if session.get("issues"):
        warnings.extend(session["issues"][:3])
    if sso.get("recommendations"):
        warnings.extend(sso["recommendations"][:2])

    if violations and settings.iam_gate_enabled:
        gate = "fail"
    elif violations or warnings:
        gate = "warn"
    else:
        gate = "pass"

    return {"gate_verdict": gate, "violations": violations, "warnings": warnings}


def build_iam_intelligence_report(
    *,
    run_id: str = "",
    repo: str = "",
    artifacts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    artifacts = artifacts or {}
    policy = resolve_iam_policy(repo)
    sso = artifacts.get("sso_readiness") or assess_sso_readiness()
    tenant = artifacts.get("tenant_rbac_context") or resolve_tenant_context(repo)
    session = assess_session_hardening()
    api_keys = assess_api_key_hygiene()
    mfa = assess_mfa_readiness()
    compliance = artifacts.get("compliance_report") or {}

    readiness_score = compute_iam_readiness_score(
        sso=sso,
        session=session,
        api_keys=api_keys,
        mfa=mfa,
        tenant=tenant,
    )
    gates = evaluate_iam_gates(
        policy=policy,
        readiness_score=readiness_score,
        sso=sso,
        session=session,
        mfa=mfa,
    )

    report: dict[str, Any] = {
        "run_id": run_id or None,
        "repository": repo or None,
        "policy": policy,
        "sso_readiness": sso,
        "tenant_rbac": tenant,
        "session_hardening": session,
        "api_key_hygiene": api_keys,
        "mfa_readiness": mfa,
        "compliance_score_percent": compliance.get("overall_score_percent"),
        "readiness_score": readiness_score,
        "gates": gates,
        "gate_verdict": gates["gate_verdict"],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "analysis_mode": "heuristic",
    }
    report["summary"] = (
        f"IAM {gates['gate_verdict']}: readiness {readiness_score}%, "
        f"SSO providers {len(sso.get('active_providers') or [])}, "
        f"API auth={'on' if session.get('api_require_auth') else 'off'}."
    )
    return report
