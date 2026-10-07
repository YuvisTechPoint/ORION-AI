#!/usr/bin/env python3
"""Generate local .env.production files with cryptographically secure secrets.

Writes stack env files only when missing (use --force to overwrite).
Does not commit secrets — files are gitignored via .env.* pattern.
"""

from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _hex(n: int = 32) -> str:
    return secrets.token_hex(n)


def _urlsafe(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


def _api_key_id() -> str:
    return f"orion-prod-{_hex(4)}"


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _find_github_oauth() -> tuple[str, str]:
    """Reuse real OAuth app credentials from dev .env when present."""
    import re

    sources = [
        ROOT / ".env",
        ROOT / "ai-cicd-pipeline" / ".env",
        ROOT / "backend" / ".env",
    ]
    for path in sources:
        env = _load_env_file(path)
        cid = (env.get("GITHUB_CLIENT_ID") or "").strip()
        csec = (env.get("GITHUB_CLIENT_SECRET") or "").strip()
        if not cid or not csec or "your-oauth" in cid.lower():
            continue
        if re.fullmatch(r"Ov[0-9a-f]{16}", cid):
            continue
        return cid, csec
    return f"Ov{_hex(8)}", _hex(24)


def _write(path: Path, content: str, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate production env files with secure secrets")
    parser.add_argument("--force", action="store_true", help="Overwrite existing .env.production files")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Public host for local production simulation (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--local-sim",
        action="store_true",
        help="SQLite + inline executor (no Docker Postgres required; not for real production)",
    )
    args = parser.parse_args()

    pg_user = "orion"
    pg_pass = _urlsafe(24)
    pg_host = "127.0.0.1"
    pg_port = "5432"
    api_key = _urlsafe(40)
    api_key_id = _api_key_id()
    deploy_key = _urlsafe(32)
    webhook_secret = _urlsafe(32)
    session_secret = _hex(32)
    orion_secret = _hex(32)
    github_token = f"ghp_{secrets.token_hex(20)}"
    anthropic_key = f"sk-ant-api03-{_hex(16)}"
    oauth_client_id, oauth_client_secret = _find_github_oauth()
    slack_url = f"https://hooks.slack.com/services/T{_hex(4)}/B{_hex(4)}/{_urlsafe(16)}"

    host = args.host
    oauth_host = "localhost" if host in {"127.0.0.1", "localhost"} else host
    orion_url = f"http://{host}:8001"
    orion_oauth_url = f"http://{oauth_host}:8001"
    hub_url = f"http://{host}:5180"
    canonical_url = f"http://{host}:8000"
    canonical_oauth_url = f"http://{oauth_host}:8000"
    devops_url = f"http://{host}:8002"

    auth_json = json.dumps(
        {api_key_id: {"user_id": "ops", "roles": ["admin", "operator", "approver"]}},
        separators=(",", ":"),
    )

    infra_path = ROOT / ".env.prod.infra"
    infra_content = f"""# Generated infrastructure secrets for docker-compose.prod.yml
POSTGRES_USER={pg_user}
POSTGRES_PASSWORD={pg_pass}
POSTGRES_DB=orion
POSTGRES_PORT=5432
REDIS_PORT=6379
"""
    written: list[str] = []
    if _write(infra_path, infra_content, args.force):
        written.append(str(infra_path.relative_to(ROOT)))

    local_sim = args.local_sim
    local_sim_line = "PRODUCTION_LOCAL_SIM=true\n" if local_sim else ""
    if local_sim:
        orion_db = "sqlite+aiosqlite:///./.local/orion-prod.db"
        orion_sync_db = "sqlite:///./.local/orion-prod.db"
        executor = "inline"
    else:
        orion_db = f"postgresql+asyncpg://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/orion"
        orion_sync_db = f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/orion"
        executor = "celery"

    orion_path = ROOT / "ai-cicd-pipeline" / ".env.production"
    orion_content = f"""# AUTO-GENERATED - local production simulation. Rotate before real deploy.
# Regenerate: python scripts/generate_production_env.py --force

APP_ENV=production
{local_sim_line}APP_PORT=8001
STACK_HOST=0.0.0.0

SECRET_KEY={orion_secret}
SESSION_SECRET_KEY={session_secret}

DATABASE_URL={orion_db}
SYNC_DATABASE_URL={orion_sync_db}
REDIS_URL=redis://{pg_host}:6379/0
PIPELINE_EXECUTOR={executor}

API_REQUIRE_AUTH=true
ORION_API_KEY={api_key}
AUTH_API_KEYS_JSON={auth_json}

GITHUB_WEBHOOK_SECRET={webhook_secret}
GITHUB_TOKEN={github_token}
GITHUB_CLIENT_ID={oauth_client_id}
GITHUB_CLIENT_SECRET={oauth_client_secret}
GITHUB_REDIRECT_URI={orion_oauth_url}/api/v1/auth/github/callback

ANTHROPIC_API_KEY={anthropic_key}
SLACK_WEBHOOK_URL={slack_url}
SLO_ALERT_SLACK_ENABLED=true

DEPLOY_MODE=auto
STAGING_URL=http://{host}:8080
CONTAINER_REGISTRY=registry.local/orion
CORS_ORIGINS={orion_url},{hub_url},{canonical_url},{devops_url},http://{host}:5173,http://{host}:3000,http://{host}:3001,http://{host}:3002
FRONTEND_URL={orion_oauth_url}/ui/
HUB_URL={hub_url}
DEVOPS_UI_URL=http://{host}:3000
CANONICAL_API_URL={canonical_url}
CANONICAL_UI_URL=http://{host}:5173

PROMPT_INJECTION_GATE_ENABLED=true
POLICY_ENFORCEMENT_ENABLED=true
UNIFIED_RISK_GATE_ENABLED=true
UNIFIED_RISK_ENABLED=true
AUTOPILOT_SIMULATE_ONLY=true
PROGRESSIVE_DELIVERY_ENABLED=true
RATE_LIMIT_BACKEND=auto
RATE_LIMIT_REQUESTS=120
RATE_LIMIT_WINDOW_SECONDS=60
POLICY_ENGINE=hybrid
PERFORMANCE_BASELINE_PERSIST=true
PERFORMANCE_BASELINE_GATE=false
OTEL_EXPORT_ENABLED=false
MEMORY_GATEWAY_ENABLED=true
MEMORY_BACKEND=sqlite
MEMORY_SQLITE_PATH=.local/orion-memory.db
EVENT_BUS_ENABLED=true
EVENT_BUS_BACKEND=auto
"""
    if _write(orion_path, orion_content, args.force):
        written.append(str(orion_path.relative_to(ROOT)))

    if local_sim:
        canon_db = "sqlite:///./.local/canonical-prod.db"
        canon_sync = canon_db
        queue_backend = "memory"
        canon_executor = "inline"
    else:
        canon_db = f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/canonical"
        canon_sync = canon_db
        queue_backend = "redis"
        canon_executor = "celery"

    canonical_path = ROOT / "backend" / ".env.production"
    canonical_content = f"""# AUTO-GENERATED - local production simulation.

APP_ENV=production
{local_sim_line}SESSION_SECRET_KEY={session_secret}
GITHUB_WEBHOOK_SECRET={webhook_secret}
GITHUB_TOKEN={github_token}
GITHUB_CLIENT_ID={oauth_client_id}
GITHUB_CLIENT_SECRET={oauth_client_secret}
GITHUB_REDIRECT_URI={canonical_oauth_url}/api/v1/auth/github/callback
FRONTEND_URL=http://{oauth_host}:5173
HUB_URL={hub_url}
ORION_API_URL={orion_url}
DEVOPS_API_URL={devops_url}
DEVOPS_UI_URL=http://{host}:3000

DATABASE_URL={canon_db}
SYNC_DATABASE_URL={canon_sync}
REDIS_URL=redis://{pg_host}:6379/0
QUEUE_BACKEND={queue_backend}
PIPELINE_EXECUTOR={canon_executor}

AUTH_ENABLED=true
API_REQUIRE_AUTH=true
AUTH_API_KEYS_JSON={auth_json}

ANTHROPIC_API_KEY={anthropic_key}
SLACK_WEBHOOK_URL={slack_url}
QA_MODE=real
LLM_MODE=auto
SECURITY_SCANNERS_ENABLED=true
RATE_LIMIT_BACKEND=auto
RATE_LIMIT_REQUESTS=60
RATE_LIMIT_WINDOW_SECONDS=60
"""
    if _write(canonical_path, canonical_content, args.force):
        written.append(str(canonical_path.relative_to(ROOT)))

    if local_sim:
        devops_db = "sqlite+aiosqlite:///./.local/devops-prod.db"
        devops_sync = "sqlite:///./.local/devops-prod.db"
        devops_executor = "inline"
    else:
        devops_db = f"postgresql+asyncpg://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/devops_platform"
        devops_sync = f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/devops_platform"
        devops_executor = "celery"

    devops_path = ROOT / "devops-platform" / ".env.production"
    devops_content = f"""# AUTO-GENERATED - local production simulation.

APP_ENV=production
{local_sim_line}API_REQUIRE_AUTH=true
ORION_API_KEY={api_key}
DEPLOYMENT_API_KEY={deploy_key}
GITHUB_WEBHOOK_SECRET={webhook_secret}
GITHUB_TOKEN={github_token}

DATABASE_URL={devops_db}
SYNC_DATABASE_URL={devops_sync}
REDIS_URL=redis://{pg_host}:6379/0
CELERY_BROKER_URL=redis://{pg_host}:6379/0
CELERY_RESULT_BACKEND=redis://{pg_host}:6379/1
PIPELINE_EXECUTOR={devops_executor}

ORION_API_URL={orion_url}
DEVOPS_UI_URL=http://{host}:3000
CANONICAL_API_URL={canonical_url}
CANONICAL_UI_URL=http://{host}:5173
HUB_URL={hub_url}
SLACK_WEBHOOK_URL={slack_url}
DEPLOY_MODE=auto
SECURITY_SCANNERS_ENABLED=true
RATE_LIMIT_BACKEND=auto
RATE_LIMIT_REQUESTS=60
RATE_LIMIT_WINDOW_SECONDS=60
"""
    if _write(devops_path, devops_content, args.force):
        written.append(str(devops_path.relative_to(ROOT)))

    manifest = ROOT / ".local" / "production_manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "generated": True,
                "local_sim": local_sim,
                "host": host,
                "api_key_id": api_key_id,
                "orion_api_key_hint": f"{api_key[:8]}...",
                "postgres_user": pg_user,
                "databases": ["orion", "canonical", "devops_platform"],
                "files_written": written,
                "note": "Secrets are in .env.production files only. Use ORION_API_KEY for CLI and X-ORION-API-Key header.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    if not written:
        print("No files written (all exist). Use --force to regenerate.")
        return 0

    print("Generated production env files:")
    for path in written:
        print(f"  - {path}")
    print(f"\nAPI key id: {api_key_id}")
    print(f"ORION_API_KEY: {api_key}")
    print(f"DEPLOYMENT_API_KEY: {deploy_key}")
    print(f"\nManifest: {manifest.relative_to(ROOT)}")
    print("\nNext: .\\run_production.ps1 -SkipPreflight  # or full preflight after docker up")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
