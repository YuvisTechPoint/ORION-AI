"""Production hardening checklist — fail-closed guidance for ORION deployments."""

from __future__ import annotations

import json
from typing import Any

from app.config import Settings, settings


def _is_placeholder(value: str) -> bool:
    raw = (value or "").strip().lower()
    if not raw or raw in {"{}", "null", "none", "changeme", "your-webhook-secret"}:
        return True
    markers = (
        "your-",
        "changeme",
        "placeholder",
        "example",
        "xxx/yyy/zzz",
        "orion-secret-key",
        "orion-super-secret",
        "sk-ant-api03-your",
        "ghp_your",
        "replace_with",
        "replace-me",
    )
    return any(marker in raw for marker in markers)


def _has_api_keys(cfg: Settings) -> bool:
    raw = (cfg.auth_api_keys_json or "").strip()
    if raw and raw != "{}":
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and data:
                return True
        except json.JSONDecodeError:
            return False
    legacy = (getattr(cfg, "orion_api_key", None) or "").strip()
    return bool(legacy) and not _is_placeholder(legacy)


def _db_is_sqlite(url: str) -> bool:
    return "sqlite" in (url or "").lower()


def evaluate_production_hardening(cfg: Settings | None = None) -> dict[str, Any]:
    """Return structured production readiness checklist (critical / warning / info)."""
    cfg = cfg or settings
    items: list[dict[str, Any]] = []

    def add(
        code: str,
        category: str,
        ok: bool,
        detail: str,
        *,
        severity: str = "critical",
        recommendation: str = "",
    ) -> None:
        items.append(
            {
                "code": code,
                "category": category,
                "ok": ok,
                "severity": severity,
                "detail": detail,
                "recommendation": recommendation,
            }
        )

    is_prod = cfg.is_production

    add(
        "app_env_production",
        "core",
        is_prod,
        f"APP_ENV={cfg.app_env}",
        severity="critical" if not is_prod else "info",
        recommendation="Set APP_ENV=production for production deployments.",
    )
    add(
        "api_require_auth",
        "auth",
        cfg.api_require_auth,
        f"API_REQUIRE_AUTH={cfg.api_require_auth}",
        recommendation="Enable API_REQUIRE_AUTH (auto-enabled when APP_ENV=production).",
    )
    add(
        "api_keys_configured",
        "auth",
        _has_api_keys(cfg),
        "AUTH_API_KEYS_JSON or ORION_API_KEY",
        severity="critical" if is_prod else "warning",
        recommendation='Set AUTH_API_KEYS_JSON={"key-id":{"user_id":"ops","roles":["operator"]}}.',
    )
    add(
        "session_secret",
        "secrets",
        not _is_placeholder(cfg.session_secret_key) and not cfg.session_secret_key.startswith("orion-super-secret"),
        "SESSION_SECRET_KEY",
        recommendation="Use 32+ random bytes; rotate on compromise.",
    )
    add(
        "secret_key",
        "secrets",
        not _is_placeholder(cfg.secret_key) and not cfg.secret_key.startswith("orion-secret-key"),
        "SECRET_KEY",
        recommendation="Set SECRET_KEY to a unique random value.",
    )
    add(
        "github_webhook_secret",
        "webhooks",
        not _is_placeholder(cfg.github_webhook_secret),
        "GITHUB_WEBHOOK_SECRET",
        recommendation="Use a dedicated webhook secret (never GITHUB_TOKEN).",
    )
    local_sim = bool(getattr(cfg, "production_local_sim", False))
    add(
        "database_not_sqlite",
        "data",
        not _db_is_sqlite(cfg.database_url) or local_sim,
        f"DATABASE_URL backend (local_sim={local_sim})",
        severity="warning" if local_sim else ("critical" if is_prod else "warning"),
        recommendation="Use PostgreSQL with TLS in production (see docker-compose.prod.yml).",
    )
    add(
        "prompt_injection_gate",
        "security",
        cfg.prompt_injection_gate_enabled,
        f"PROMPT_INJECTION_GATE_ENABLED={cfg.prompt_injection_gate_enabled}",
        severity="warning",
        recommendation="Keep prompt injection gate enabled in production.",
    )
    add(
        "policy_enforcement",
        "policy",
        cfg.policy_enforcement_enabled,
        f"POLICY_ENFORCEMENT_ENABLED={cfg.policy_enforcement_enabled}",
        severity="warning",
        recommendation="Enable policy-as-code enforcement for production promotion.",
    )
    add(
        "autopilot_simulate_only",
        "automation",
        cfg.autopilot_simulate_only,
        f"AUTOPILOT_SIMULATE_ONLY={cfg.autopilot_simulate_only}",
        severity="warning",
        recommendation="Keep simulate-only until autonomy policies are reviewed.",
    )
    add(
        "unified_risk_enabled",
        "risk",
        cfg.unified_risk_enabled,
        f"UNIFIED_RISK_ENABLED={cfg.unified_risk_enabled}",
        severity="info",
        recommendation="Enable unified risk fusion before deploy gates.",
    )
    cors = cfg.cors_origin_list
    add(
        "cors_no_wildcard",
        "network",
        "*" not in cors and not any(o.strip() == "*" for o in (cfg.cors_origins or "").split(",")),
        f"CORS_ORIGINS={cfg.cors_origins[:80]}",
        severity="warning",
        recommendation="Restrict CORS to known UI origins only.",
    )
    add(
        "deploy_mode",
        "delivery",
        str(cfg.deploy_mode).lower() in {"auto", "docker"},
        f"DEPLOY_MODE={cfg.deploy_mode}",
        severity="warning",
        recommendation="Use DEPLOY_MODE=auto or docker in production (not simulate/skip).",
    )
    add(
        "slack_configured",
        "observability",
        cfg.slack_enabled,
        "SLACK_WEBHOOK_URL",
        severity="info",
        recommendation="Configure Slack for SLO and pipeline alerts.",
    )

    critical_fail = [i for i in items if not i["ok"] and i["severity"] == "critical"]
    warning_fail = [i for i in items if not i["ok"] and i["severity"] == "warning"]
    passed = sum(1 for i in items if i["ok"])
    score = round(100 * passed / max(len(items), 1))

    return {
        "environment": cfg.app_env,
        "production_mode": is_prod,
        "ready_for_production": is_prod and not critical_fail,
        "score": score,
        "summary": (
            f"Production hardening {score}% — "
            f"{len(critical_fail)} critical, {len(warning_fail)} warning(s)."
        ),
        "critical_failures": [i["code"] for i in critical_fail],
        "warnings": [i["code"] for i in warning_fail],
        "items": items,
    }
