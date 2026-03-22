import asyncio
import os
import signal
import subprocess
import sys
import time
from typing import Any

import psutil
import requests
from sqlalchemy import create_engine, text

from app.config import settings


class OrionMonitorDaemon:
    def __init__(self) -> None:
        self.running = True
        self.services = (
            "orion-api.service",
            "orion-worker.service",
            "orion-beat.service",
            "orion-monitor.service",
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.running = False

    def _systemctl_active(self, unit: str) -> bool:
        try:
            p = subprocess.run(
                ["systemctl", "is-active", unit],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            return p.stdout.strip() == "active"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return True

    def _restart_unit(self, unit: str) -> None:
        subprocess.run(
            ["systemctl", "restart", unit],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def _vacuum_journal(self) -> None:
        subprocess.run(
            ["journalctl", "--vacuum-size=200M"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def _disk_free_mb(self, path: str = "/") -> float:
        try:
            usage = psutil.disk_usage(path)
            return usage.free / (1024 * 1024)
        except OSError:
            return 0.0

    def _api_memory_mb(self) -> float | None:
        for proc in psutil.process_iter(attrs=["name", "memory_info", "cmdline"]):
            try:
                cmd = " ".join(proc.info.get("cmdline") or [])
                if "uvicorn" in cmd and "app.main:app" in cmd:
                    rss = proc.info.get("memory_info")
                    if rss:
                        return rss.rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def _db_ping(self) -> bool:
        try:
            eng = create_engine(settings.sync_database_url, pool_pre_ping=True)
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def _slack_alert(self, text: str) -> None:
        if not settings.slack_webhook_url:
            return
        try:
            requests.post(
                settings.slack_webhook_url,
                json={"text": text},
                timeout=15,
            )
        except requests.RequestException:
            pass

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        while self.running:
            for unit in self.services:
                if not self._systemctl_active(unit):
                    self._slack_alert(f"ORION monitor: {unit} not active — restarting")
                    self._restart_unit(unit)

            free = self._disk_free_mb("/var")
            if free < 500 and free > 0:
                self._vacuum_journal()
                self._slack_alert(
                    f"ORION monitor: low disk on /var ({free:.0f} MB free) — journal vacuum attempted"
                )

            mem = self._api_memory_mb()
            if mem is not None and mem > 2048:
                self._slack_alert(
                    f"ORION monitor: orion-api RSS {mem:.0f} MB — restarting orion-api"
                )
                self._restart_unit("orion-api.service")

            if not self._db_ping():
                self._slack_alert("ORION monitor: database connectivity check failed")

            time.sleep(60)

        sys.exit(0)


def main() -> None:
    OrionMonitorDaemon().run()


if __name__ == "__main__":
    main()
