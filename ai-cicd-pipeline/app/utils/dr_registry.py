"""Disaster recovery registry — RTO/RPO targets and backup policy defaults."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings

DEFAULT_BACKUP_DIR = Path("/var/lib/orion/backups")


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text or text == "{}":
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def resolve_backup_dir() -> Path:
    configured = (settings.dr_backup_dir or "").strip()
    if configured:
        return Path(configured)
    return DEFAULT_BACKUP_DIR


def resolve_dr_policy(repo: str = "") -> dict[str, Any]:
    custom = _parse_json(settings.dr_policy_json)
    org = repo.split("/", 1)[0] if "/" in repo else repo
    org_block = custom.get(org) if isinstance(custom.get(org), dict) else {}
    repo_block = custom.get(repo) if isinstance(custom.get(repo), dict) else {}

    def _float(key: str, default: float) -> float:
        raw = repo_block.get(key) if key in repo_block else org_block.get(key)
        if raw is None:
            return default
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def _int(key: str, default: int) -> int:
        raw = repo_block.get(key) if key in repo_block else org_block.get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    rto = _float("rto_target_hours", settings.dr_rto_target_hours)
    rpo = _float("rpo_target_hours", settings.dr_rpo_target_hours)
    max_age = _float("max_backup_age_hours", settings.dr_max_backup_age_hours)
    retention = _int("retention_count", settings.dr_backup_retention_count)

    return {
        "repository": repo or None,
        "organization": org or None,
        "rto_target_hours": rto,
        "rpo_target_hours": rpo,
        "max_backup_age_hours": max_age,
        "retention_count": retention,
        "backup_dir": str(resolve_backup_dir()),
        "restore_drill_simulated": settings.dr_restore_drill_simulated,
        "summary": (
            f"DR policy: RTO {rto:.0f}h, RPO {rpo:.0f}h, "
            f"max backup age {max_age:.0f}h, retain {retention} file(s)."
        ),
    }
