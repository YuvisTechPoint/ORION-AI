#!/usr/bin/env python3
"""Cross-stack production preflight — validates env files before deploy."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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


def _apply_env(path: Path) -> None:
    for key, value in _load_env_file(path).items():
        os.environ[key] = value


def _check_file(label: str, path: Path, required_keys: list[str]) -> list[str]:
    problems: list[str] = []
    if not path.is_file():
        return [f"{label}: missing {path.relative_to(ROOT)} — copy from .env.production.example"]
    env = _load_env_file(path)
    if env.get("APP_ENV", "").lower() not in {"production", "prod"}:
        problems.append(f"{label}: APP_ENV must be production in {path.name}")
    placeholders = (
        "your-",
        "changeme",
        "replace_",
        "orion-secret-key",
        "orion-super-secret",
        "ghp_your",
        "sk-ant-api03-your",
        "devops-approver-key",
    )
    for key in required_keys:
        val = env.get(key, "")
        if not val:
            problems.append(f"{label}: {key} is not set in {path.name}")
        elif any(p in val.lower() for p in placeholders):
            problems.append(f"{label}: {key} still contains a placeholder in {path.name}")
    return problems


def main() -> int:
    stacks = [
        (
            "ORION",
            ROOT / "ai-cicd-pipeline" / ".env.production",
            ["APP_ENV", "SECRET_KEY", "SESSION_SECRET_KEY", "GITHUB_WEBHOOK_SECRET", "DATABASE_URL"],
        ),
        (
            "Canonical",
            ROOT / "backend" / ".env.production",
            ["APP_ENV", "SESSION_SECRET_KEY", "GITHUB_WEBHOOK_SECRET"],
        ),
        (
            "DevOps",
            ROOT / "devops-platform" / ".env.production",
            ["APP_ENV", "DATABASE_URL", "GITHUB_WEBHOOK_SECRET", "DEPLOYMENT_API_KEY"],
        ),
    ]

    import re

    problems: list[str] = []
    for label, path, keys in stacks:
        problems.extend(_check_file(label, path, keys))

    for label, path, _keys in stacks:
        env = _load_env_file(path)
        cid = env.get("GITHUB_CLIENT_ID", "")
        if path.name.endswith(".production") and label in {"ORION", "Canonical"}:
            if not cid:
                problems.append(f"{label}: GITHUB_CLIENT_ID missing — run python scripts/sync_github_oauth.py")
            elif re.fullmatch(r"Ov[0-9a-f]{16}", cid):
                problems.append(
                    f"{label}: GITHUB_CLIENT_ID looks auto-generated (not a real GitHub OAuth app) — "
                    "run python scripts/sync_github_oauth.py"
                )

    orion_prod = ROOT / "ai-cicd-pipeline" / ".env.production"
    if orion_prod.is_file():
        try:
            _apply_env(orion_prod)
            sys.path.insert(0, str(ROOT / "ai-cicd-pipeline"))
            from app.config import Settings
            from app.utils.production_hardening import evaluate_production_hardening

            cfg = Settings()
            report = evaluate_production_hardening(cfg)
            if report.get("critical_failures"):
                problems.append(
                    "ORION hardening: critical failures — " + ", ".join(report["critical_failures"])
                )
            try:
                cfg.validate_startup()
            except RuntimeError as exc:
                problems.append(f"ORION validate_startup: {exc}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"ORION hardening check failed: {exc}")

    result = {
        "ok": not problems,
        "problems": problems,
        "stacks_checked": [s[0] for s in stacks],
    }
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
