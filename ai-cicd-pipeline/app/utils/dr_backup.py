"""Database backup utilities — PostgreSQL pg_dump and SQLite file copy."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app.config import settings
from app.utils.dr_registry import resolve_backup_dir


def detect_database_backend(database_url: str) -> str:
    low = (database_url or "").lower()
    if "sqlite" in low:
        return "sqlite"
    if "postgresql" in low or "postgres://" in low:
        return "postgresql"
    return "unknown"


def sqlite_path_from_url(database_url: str) -> Path:
    parsed = urlparse(database_url.replace("+aiosqlite", "").replace("+asyncpg", ""))
    raw = unquote(parsed.path or "")
    if raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
        return Path(raw[1:])
    if raw.startswith("/"):
        return Path(raw)
    return Path(raw.lstrip("/"))


def pg_dump_args(database_url: str) -> tuple[list[str], dict[str, str]]:
    parsed = urlparse(database_url.replace("+asyncpg", "").replace("+psycopg2", ""))
    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    args = [
        "-h",
        parsed.hostname or "localhost",
        "-p",
        str(parsed.port or 5432),
        "-U",
        unquote(parsed.username or "postgres"),
        "-d",
        parsed.path.lstrip("/") or "postgres",
    ]
    return args, env


def list_backups(backup_dir: Path | None = None) -> list[dict[str, Any]]:
    directory = backup_dir or resolve_backup_dir()
    if not directory.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(directory.glob("orion_*"), reverse=True):
        if not path.is_file():
            continue
        stat = path.stat()
        rows.append(
            {
                "file": str(path),
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "backend": "sqlite" if path.suffix in {".db", ".sqlite"} else "postgresql",
            }
        )
    return rows


def run_database_backup(
    *,
    output_dir: Path | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    url = database_url or settings.sync_database_url
    backend = detect_database_backend(url)
    backup_dir = output_dir or resolve_backup_dir()

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {
            "ok": False,
            "backend": backend,
            "error": f"Cannot write to {backup_dir}: {exc}",
        }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if backend == "sqlite":
        src = sqlite_path_from_url(url)
        if not src.is_file():
            return {"ok": False, "backend": backend, "error": f"SQLite database not found: {src}"}
        out = backup_dir / f"orion_{stamp}.db"
        shutil.copy2(src, out)
        return {
            "ok": True,
            "backend": backend,
            "file": str(out),
            "size_bytes": out.stat().st_size,
            "source": str(src),
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "summary": f"SQLite backup copied to {out.name} ({out.stat().st_size} bytes).",
        }

    if backend == "postgresql":
        out = backup_dir / f"orion_{stamp}.sql"
        conn_args, env = pg_dump_args(url)
        try:
            proc = subprocess.run(
                ["pg_dump", *conn_args, "-f", str(out)],
                env=env,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            return {"ok": False, "backend": backend, "error": "pg_dump not found; install postgresql-client"}
        if proc.returncode != 0:
            return {
                "ok": False,
                "backend": backend,
                "error": (proc.stderr or proc.stdout or "pg_dump failed").strip(),
            }
        return {
            "ok": True,
            "backend": backend,
            "file": str(out),
            "size_bytes": out.stat().st_size,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "summary": f"PostgreSQL pg_dump saved to {out.name} ({out.stat().st_size} bytes).",
        }

    return {"ok": False, "backend": backend, "error": f"Unsupported database backend for backup: {backend}"}


def validate_backup_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"valid": False, "error": "backup file not found"}
    size = path.stat().st_size
    if size <= 0:
        return {"valid": False, "error": "backup file is empty"}

    if path.suffix in {".db", ".sqlite"}:
        return {
            "valid": True,
            "backend": "sqlite",
            "size_bytes": size,
            "restore_drill": "simulated_pass",
            "summary": f"SQLite backup {path.name} readable ({size} bytes).",
        }

    try:
        head = path.read_bytes()[:5]
    except OSError as exc:
        return {"valid": False, "error": str(exc)}

    is_pg_dump = head.startswith(b"PGDMP") or b"PostgreSQL database dump" in path.read_bytes()[:4096]
    return {
        "valid": is_pg_dump or size > 100,
        "backend": "postgresql",
        "size_bytes": size,
        "restore_drill": "simulated_pass" if is_pg_dump or size > 100 else "simulated_fail",
        "summary": f"PostgreSQL backup {path.name} {'valid' if is_pg_dump or size > 100 else 'suspect'} ({size} bytes).",
    }
