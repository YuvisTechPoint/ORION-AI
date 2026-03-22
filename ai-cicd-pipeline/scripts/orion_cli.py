#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import psutil
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402


def _systemctl_show(unit: str) -> dict[str, str]:
    try:
        out = subprocess.check_output(
            ["systemctl", "show", unit], text=True, timeout=30
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    data: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k] = v
    return data


def cmd_status(_: argparse.Namespace) -> int:
    units = [
        "orion-api.service",
        "orion-worker.service",
        "orion-beat.service",
        "orion-monitor.service",
    ]
    print(f"{'UNIT':<24} {'ACTIVE':<12} {'SUB':<12} {'PID':<8}")
    for u in units:
        st = _systemctl_show(u)
        print(
            f"{u:<24} {st.get('ActiveState','?'):<12} {st.get('SubState','?'):<12} {st.get('MainPID','-'):<8}"
        )
    print("\nLoad (1m):", psutil.getloadavg()[0])
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    target = args.service or "orion-api.service"
    if target == "all":
        for u in [
            "orion-api.service",
            "orion-worker.service",
            "orion-beat.service",
            "orion-monitor.service",
        ]:
            subprocess.run(["systemctl", "restart", u], check=False)
    else:
        subprocess.run(["systemctl", "restart", target], check=False)
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    unit = args.service or "orion-api.service"
    lines = str(args.lines)
    subprocess.run(["journalctl", "-u", unit, "-n", lines, "-f"], check=False)
    return 0


def cmd_deploy(args: argparse.Namespace) -> int:
    repo_path = Path(args.repo_path).resolve()
    payload = {
        "ref": "refs/heads/main",
        "after": "a" * 40,
        "commits": [{"id": "b" * 40, "message": "synthetic deploy"}],
        "repository": {
            "full_name": "example/synthetic",
            "clone_url": str(repo_path.as_uri()),
        },
        "pusher": {"name": "orion-cli"},
    }
    body = json.dumps(payload).encode("utf-8")
    sig = (
        "sha256="
        + hmac.new(
            settings.github_webhook_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
    )
    r = requests.post(
        f"http://127.0.0.1:{settings.app_port}/api/v1/webhook/github",
        data=body,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "push",
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    print(r.status_code, r.text)
    return 0 if r.status_code in (200, 202) else 1


def cmd_health(_: argparse.Namespace) -> int:
    r = httpx.get(
        f"http://127.0.0.1:{settings.app_port}/api/v1/pipeline/health", timeout=10.0
    )
    print(r.status_code, r.text)
    return 0 if r.status_code == 200 else 1


def cmd_db_migrate(_: argparse.Namespace) -> int:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(ROOT),
        check=False,
    )
    return 0


def cmd_workers(_: argparse.Namespace) -> int:
    r = httpx.get("http://127.0.0.1:5555/api/workers", timeout=10.0)
    print(r.status_code, r.text)
    return 0


def cmd_backup_db(_: argparse.Namespace) -> int:
    backup_dir = Path("/var/lib/orion/backups")
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        backup_dir = ROOT / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = backup_dir / f"orion-{stamp}.sql"
    proc = subprocess.run(
        ["pg_dump", settings.sync_database_url, "-f", str(out)],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    print(proc.returncode, out, proc.stderr)
    return 0 if proc.returncode == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="orion")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="Show service status")
    p_status.set_defaults(func=cmd_status)

    p_restart = sub.add_parser("restart", help="Restart services")
    p_restart.add_argument(
        "service",
        nargs="?",
        help="systemd unit or 'all'",
    )
    p_restart.set_defaults(func=cmd_restart)

    p_logs = sub.add_parser("logs", help="Tail journal logs")
    p_logs.add_argument("service", nargs="?", help="systemd unit")
    p_logs.add_argument("--lines", default="200")
    p_logs.set_defaults(func=cmd_logs)

    p_deploy = sub.add_parser("deploy", help="Send synthetic webhook")
    p_deploy.add_argument("repo_path")
    p_deploy.set_defaults(func=cmd_deploy)

    p_health = sub.add_parser("health", help="GET /api/v1/pipeline/health")
    p_health.set_defaults(func=cmd_health)

    p_migrate = sub.add_parser("db-migrate", help="alembic upgrade head")
    p_migrate.set_defaults(func=cmd_db_migrate)

    p_workers = sub.add_parser("workers", help="Query Flower workers API")
    p_workers.set_defaults(func=cmd_workers)

    p_backup = sub.add_parser("backup-db", help="pg_dump database")
    p_backup.set_defaults(func=cmd_backup_db)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
