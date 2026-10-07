from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import time
from typing import Any

import psutil
import psycopg2
import requests

from core.config import get_settings

LOGGER = logging.getLogger("orion_monitor_daemon")
SERVICES = ["orion-api", "orion-worker", "orion-beat", "orion-monitor"]


class OrionMonitorDaemon:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.running = True
        self.sync_database_url = os.getenv("SYNC_DATABASE_URL", self.settings.database_url)
        self.slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
        signal.signal(signal.SIGTERM, self._handle_stop)
        signal.signal(signal.SIGINT, self._handle_stop)

    def _handle_stop(self, _signum: int, _frame: Any) -> None:
        self.running = False

    def run(self) -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
        LOGGER.info("ORION monitor daemon started")
        while self.running:
            self._check_services()
            self._check_disk_space()
            self._check_api_memory()
            self._check_database_connectivity()
            time.sleep(60)
        LOGGER.info("ORION monitor daemon stopped")

    def _check_services(self) -> None:
        for service_name in SERVICES:
            result = subprocess.run(["systemctl", "is-active", service_name], capture_output=True, text=True, check=False)
            if result.stdout != "active\n":
                LOGGER.error("Service %s is not active (status=%s). Restarting.", service_name, result.stdout.strip())
                subprocess.run(["systemctl", "restart", service_name], check=False)

    def _check_disk_space(self) -> None:
        usage = shutil.disk_usage("/var/log/orion")
        free_mb = usage.free / (1024 * 1024)
        if free_mb < 500:
            LOGGER.error("Low disk space on /var/log/orion: %.2f MB free. Vacuuming journals.", free_mb)
            subprocess.run(["journalctl", "--vacuum-size=1G"], check=False)

    def _check_api_memory(self) -> None:
        target_pid: int | None = None
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = " ".join(proc.info.get("cmdline") or [])
                if "uvicorn" in cmdline and "backend.main:app" in cmdline:
                    target_pid = int(proc.info["pid"])
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if target_pid is None:
            return

        rss = psutil.Process(target_pid).memory_info().rss
        if rss > 2 * 1024 * 1024 * 1024:
            LOGGER.warning("orion-api RSS exceeds 2GB (pid=%s). Restarting service.", target_pid)
            subprocess.run(["systemctl", "restart", "orion-api"], check=False)

    def _check_database_connectivity(self) -> None:
        conn = None
        try:
            conn = psycopg2.connect(self.sync_database_url, connect_timeout=5)
        except Exception as exc:  # noqa: BLE001
            LOGGER.critical("Database connectivity check failed: %s", exc)
            if self.slack_webhook_url:
                payload = {
                    "text": f"ORION monitor alert: database connectivity failed - {exc}",
                }
                try:
                    requests.post(self.slack_webhook_url, json=payload, timeout=5)
                except Exception:  # noqa: BLE001
                    LOGGER.exception("Failed to send Slack alert")
        finally:
            if conn is not None:
                conn.close()


if __name__ == "__main__":
    OrionMonitorDaemon().run()
