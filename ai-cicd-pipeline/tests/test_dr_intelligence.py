"""Tests for Phase 26 disaster recovery intelligence."""

from __future__ import annotations

import json
from pathlib import Path

from app.utils.dr_backup import detect_database_backend, list_backups, run_database_backup, validate_backup_file
from app.utils.dr_intelligence import assess_backup_freshness, build_dr_intelligence_report, evaluate_dr_gates
from app.utils.dr_registry import resolve_dr_policy


def test_detect_database_backend():
    assert detect_database_backend("postgresql://u:p@localhost/db") == "postgresql"
    assert detect_database_backend("sqlite+aiosqlite:///./orion.db") == "sqlite"


def test_resolve_dr_policy_override(monkeypatch):
    monkeypatch.setattr(
        "app.utils.dr_registry.settings.dr_policy_json",
        json.dumps({"acme": {"rto_target_hours": 2, "rpo_target_hours": 6}}),
    )
    policy = resolve_dr_policy("acme/app")
    assert policy["rto_target_hours"] == 2.0
    assert policy["rpo_target_hours"] == 6.0


def test_assess_backup_freshness_missing():
    freshness = assess_backup_freshness([], max_age_hours=24)
    assert freshness["status"] == "missing"
    assert freshness["within_rpo"] is False


def test_assess_backup_freshness_fresh():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    freshness = assess_backup_freshness(
        [{"name": "orion_test.sql", "modified_at": now, "file": "/tmp/orion_test.sql"}],
        max_age_hours=24,
    )
    assert freshness["status"] == "fresh"
    assert freshness["within_rpo"] is True


def test_validate_backup_sql_file(tmp_path: Path):
    backup = tmp_path / "orion_test.sql"
    backup.write_text("-- PostgreSQL database dump\nCREATE TABLE foo ();", encoding="utf-8")
    result = validate_backup_file(backup)
    assert result["valid"] is True
    assert result["backend"] == "postgresql"


def test_sqlite_backup_roundtrip(tmp_path: Path, monkeypatch):
    db = tmp_path / "test.db"
    db.write_bytes(b"sqlite-format")
    url = f"sqlite+aiosqlite:///{db.as_posix()}"
    monkeypatch.setattr("app.utils.dr_backup.settings.sync_database_url", url)
    out_dir = tmp_path / "backups"
    result = run_database_backup(output_dir=out_dir)
    assert result["ok"] is True
    assert result["backend"] == "sqlite"
    assert Path(result["file"]).is_file()
    backups = list_backups(out_dir)
    assert len(backups) == 1


def test_evaluate_dr_gates_missing_backup(monkeypatch):
    monkeypatch.setattr("app.utils.dr_intelligence.settings.dr_gate_enabled", True)
    gates = evaluate_dr_gates(
        policy={"rpo_target_hours": 24},
        freshness={"status": "missing", "within_rpo": False, "issues": ["No backups"]},
        restore_drill={"valid": False, "error": "no backup"},
        database_backend="postgresql",
    )
    assert gates["gate_verdict"] == "fail"


def test_build_dr_intelligence_report(tmp_path: Path, monkeypatch):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "orion_20260101_120000.sql").write_text("-- PostgreSQL database dump\n", encoding="utf-8")
    monkeypatch.setattr("app.utils.dr_registry.settings.dr_backup_dir", str(backup_dir))
    monkeypatch.setattr("app.utils.dr_intelligence.settings.dr_backup_dir", str(backup_dir))
    report = build_dr_intelligence_report(run_id="run-dr-1", repo="org/api")
    assert report["gate_verdict"] in {"pass", "warn", "fail"}
    assert report["database_backend"] in {"postgresql", "sqlite", "unknown"}
    assert report["backup_count"] >= 1
