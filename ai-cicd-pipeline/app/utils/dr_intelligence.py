"""Disaster recovery intelligence — backup freshness, RTO/RPO, and restore drill."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.utils.dr_backup import detect_database_backend, list_backups, validate_backup_file
from app.utils.dr_registry import resolve_backup_dir, resolve_dr_policy


def _hours_since(iso_ts: str) -> float | None:
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0)
    except (TypeError, ValueError):
        return None


def assess_backup_freshness(
    backups: list[dict[str, Any]],
    *,
    max_age_hours: float,
) -> dict[str, Any]:
    if not backups:
        return {
            "status": "missing",
            "latest": None,
            "age_hours": None,
            "within_rpo": False,
            "issues": ["No backups found in backup directory"],
            "summary": "DR: no backups on disk.",
        }

    latest = backups[0]
    age = _hours_since(latest.get("modified_at") or "")
    within = age is not None and age <= max_age_hours
    issues: list[str] = []
    if age is not None and age > max_age_hours:
        issues.append(f"Latest backup is {age:.1f}h old (max {max_age_hours:.0f}h)")

    return {
        "status": "fresh" if within else "stale",
        "latest": latest,
        "age_hours": round(age, 2) if age is not None else None,
        "within_rpo": within,
        "issues": issues,
        "summary": (
            f"DR backup {'fresh' if within else 'stale'}: "
            f"{latest.get('name')} ({age:.1f}h ago)." if age is not None else f"DR backup: {latest.get('name')}."
        ),
    }


def evaluate_dr_gates(
    *,
    policy: dict[str, Any],
    freshness: dict[str, Any],
    restore_drill: dict[str, Any],
    database_backend: str,
) -> dict[str, Any]:
    violations: list[str] = []
    warnings: list[str] = []

    if freshness.get("status") == "missing":
        violations.append("No database backup available for disaster recovery")
    elif not freshness.get("within_rpo"):
        violations.append(freshness.get("issues", ["Backup exceeds RPO window"])[0])

    if not restore_drill.get("valid", False):
        violations.append(restore_drill.get("error") or "Restore drill validation failed")

    if database_backend == "unknown":
        warnings.append("Database backend unrecognized — backup strategy unverified")

    if violations and settings.dr_gate_enabled:
        gate = "fail"
    elif violations or warnings:
        gate = "warn"
    else:
        gate = "pass"

    return {"gate_verdict": gate, "violations": violations, "warnings": warnings}


def build_dr_intelligence_report(
    *,
    run_id: str = "",
    repo: str = "",
    artifacts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    artifacts = artifacts or {}
    policy = resolve_dr_policy(repo)
    backup_dir = resolve_backup_dir()
    backups = list_backups(backup_dir)
    database_backend = detect_database_backend(settings.sync_database_url)

    freshness = assess_backup_freshness(backups, max_age_hours=float(policy["rpo_target_hours"]))
    latest_path = Path((freshness.get("latest") or {}).get("file") or "")
    restore_drill = (
        validate_backup_file(latest_path)
        if latest_path.is_file()
        else {"valid": False, "error": "no backup file for restore drill", "restore_drill": "skipped"}
    )

    if not settings.dr_restore_drill_simulated and restore_drill.get("restore_drill") == "simulated_pass":
        restore_drill["note"] = "Live restore drill not implemented — file validation only"

    gates = evaluate_dr_gates(
        policy=policy,
        freshness=freshness,
        restore_drill=restore_drill,
        database_backend=database_backend,
    )

    readiness_score = 100
    if freshness.get("status") == "missing":
        readiness_score = 20
    elif not freshness.get("within_rpo"):
        readiness_score = 55
    elif not restore_drill.get("valid"):
        readiness_score = 40
    if gates["warnings"]:
        readiness_score = max(30, readiness_score - 10)

    report: dict[str, Any] = {
        "run_id": run_id or None,
        "repository": repo or None,
        "policy": policy,
        "database_backend": database_backend,
        "backup_dir": str(backup_dir),
        "backups": backups[: policy.get("retention_count", 5)],
        "backup_count": len(backups),
        "freshness": freshness,
        "restore_drill": restore_drill,
        "rto_target_hours": policy["rto_target_hours"],
        "rpo_target_hours": policy["rpo_target_hours"],
        "readiness_score": readiness_score,
        "gates": gates,
        "gate_verdict": gates["gate_verdict"],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "analysis_mode": "heuristic",
    }
    report["summary"] = (
        f"DR {gates['gate_verdict']}: {database_backend} backend, "
        f"{len(backups)} backup(s), score {readiness_score}%."
    )
    return report
