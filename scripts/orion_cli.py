#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import psutil

SERVICE_NAMES = ["orion-api", "orion-worker", "orion-beat", "orion-monitor"]
DEFAULT_BASE_URL = os.environ.get("ORION_API_BASE_URL", "http://127.0.0.1:8000")


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _print(data: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2))
        return
    if isinstance(data, dict):
        for key, value in data.items():
            print(f"{key}: {value}")
    elif isinstance(data, list):
        for item in data:
            print(item)
    else:
        print(str(data))


def cmd_status(args: argparse.Namespace) -> None:
    rows = []
    for service in SERVICE_NAMES:
        show = _run(["systemctl", "show", service, "--no-page", "--property=Id,SubState,MainPID,ActiveEnterTimestamp"])
        fields = {}
        for line in show.stdout.splitlines():
            if "=" in line:
                key, val = line.split("=", 1)
                fields[key] = val

        pid = int(fields.get("MainPID", "0") or "0")
        rss = None
        if pid > 0:
            try:
                rss = psutil.Process(pid).memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                rss = None

        rows.append(
            {
                "service": service,
                "status": fields.get("SubState", "unknown"),
                "pid": pid,
                "memory_rss_bytes": rss,
                "active_since": fields.get("ActiveEnterTimestamp", ""),
            }
        )

    _print(rows, args.json)


def cmd_restart(args: argparse.Namespace) -> None:
    targets = SERVICE_NAMES if args.service == "all" else [args.service]
    results = []
    for service in targets:
        result = _run(["systemctl", "restart", service])
        results.append({"service": service, "returncode": result.returncode, "stderr": result.stderr.strip()})
    _print(results, args.json)


def cmd_logs(args: argparse.Namespace) -> None:
    cmd = ["journalctl", "-u", args.service, "-n", str(args.lines), "--no-pager"]
    result = _run(cmd)
    data = {
        "service": args.service,
        "lines": args.lines,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }
    _print(data if args.json else data["stdout"], args.json)


def cmd_deploy(args: argparse.Namespace) -> None:
    payload = {
        "repository": {"full_name": "manual/local"},
        "ref": "refs/heads/main",
        "head_commit": {"id": "manual-trigger", "message": f"manual deploy for {args.repo_path}"},
    }
    url = f"{DEFAULT_BASE_URL}/api/v1/webhook/github"
    try:
        response = httpx.post(url, json=payload, timeout=10.0)
        output = {"url": url, "status_code": response.status_code, "body": response.text}
    except Exception as exc:  # noqa: BLE001
        output = {"url": url, "error": str(exc)}
    _print(output, args.json)


def cmd_health(args: argparse.Namespace) -> None:
    url = f"{DEFAULT_BASE_URL}/health"
    try:
        response = httpx.get(url, timeout=10.0)
        output = {"url": url, "status_code": response.status_code, "body": response.json()}
    except Exception as exc:  # noqa: BLE001
        output = {"url": url, "error": str(exc)}
    _print(output, args.json)


def cmd_db_migrate(args: argparse.Namespace) -> None:
    python_bin = "/opt/orion/venv/bin/python"
    cmd = [python_bin, "-m", "alembic", "upgrade", "head"]
    result = _run(cmd)
    output = {"command": " ".join(cmd), "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    _print(output, args.json)


def cmd_workers(args: argparse.Namespace) -> None:
    url = "http://127.0.0.1:5555/api/workers"
    try:
        response = httpx.get(url, timeout=10.0)
        output = {"url": url, "status_code": response.status_code, "body": response.text}
    except Exception as exc:  # noqa: BLE001
        output = {"url": url, "error": str(exc)}
    _print(output, args.json)


def cmd_backup_db(args: argparse.Namespace) -> None:
    env_file = Path("/etc/orion/orion.env")
    env_vars: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()

    db_user = env_vars.get("POSTGRES_USER", "devops")
    db_pass = env_vars.get("POSTGRES_PASSWORD", "devops")
    db_name = env_vars.get("POSTGRES_DB", "devops")
    db_host = env_vars.get("POSTGRES_HOST", "127.0.0.1")
    out_dir = Path("/var/lib/orion/backups")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"orion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"

    env = os.environ.copy()
    env["PGPASSWORD"] = db_pass
    cmd = ["pg_dump", "-h", db_host, "-U", db_user, "-d", db_name, "-f", str(out_file)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    output = {"command": " ".join(cmd), "returncode": result.returncode, "output_file": str(out_file), "stderr": result.stderr}
    _print(output, args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orion", description="ORION service management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_status = subparsers.add_parser("status", help="Show status of ORION services")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_restart = subparsers.add_parser("restart", help="Restart one service or all")
    p_restart.add_argument("service", choices=["all", *SERVICE_NAMES])
    p_restart.add_argument("--json", action="store_true")
    p_restart.set_defaults(func=cmd_restart)

    p_logs = subparsers.add_parser("logs", help="Tail journald logs")
    p_logs.add_argument("service", choices=SERVICE_NAMES)
    p_logs.add_argument("--lines", type=int, default=100)
    p_logs.add_argument("--json", action="store_true")
    p_logs.set_defaults(func=cmd_logs)

    p_deploy = subparsers.add_parser("deploy", help="Trigger a synthetic deploy webhook")
    p_deploy.add_argument("repo_path")
    p_deploy.add_argument("--json", action="store_true")
    p_deploy.set_defaults(func=cmd_deploy)

    p_health = subparsers.add_parser("health", help="Call ORION health endpoint")
    p_health.add_argument("--json", action="store_true")
    p_health.set_defaults(func=cmd_health)

    p_db = subparsers.add_parser("db-migrate", help="Run alembic upgrade")
    p_db.add_argument("--json", action="store_true")
    p_db.set_defaults(func=cmd_db_migrate)

    p_workers = subparsers.add_parser("workers", help="Query Flower workers API")
    p_workers.add_argument("--json", action="store_true")
    p_workers.set_defaults(func=cmd_workers)

    p_backup = subparsers.add_parser("backup-db", help="Backup PostgreSQL DB")
    p_backup.add_argument("--json", action="store_true")
    p_backup.set_defaults(func=cmd_backup_db)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
