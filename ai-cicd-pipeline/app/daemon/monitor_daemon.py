"""Standalone health daemon run by the orion-monitor systemd unit."""

import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from typing import Any

import psutil
import requests

from app.config import settings

ORION_SERVICES = ("orion-api", "orion-worker", "orion-beat", "orion-monitor")
SELF_SERVICE = "orion-monitor"
CHECK_INTERVAL_SECONDS = 60
LOG_DIR = "/var/log/orion"
MIN_FREE_BYTES = 500 * 1024 * 1024
MAX_API_RSS_BYTES = 2 * 1024 * 1024 * 1024
RESTART_COOLDOWN_SECONDS = 120

logger = logging.getLogger("orion.monitor_daemon")


def _sync_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg2://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")


class OrionMonitorDaemon:
    def __init__(self, interval: int = CHECK_INTERVAL_SECONDS) -> None:
        self.running = True
        self.interval = interval
        self._stop = threading.Event()
        self._last_restart: dict[str, float] = {}

    def _signal_handler(self, signum: int, frame: Any) -> None:
        logger.info("Received signal %s, shutting down", signum)
        self.running = False
        self._stop.set()

    # ---- systemd ------------------------------------------------------------------------
    def is_active(self, service: str) -> bool:
        try:
            result = subprocess.run(["systemctl", "is-active", service], capture_output=True, encoding="utf-8", errors="replace", timeout=30)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("systemctl unavailable for %s: %s", service, exc)
            return True
        return result.stdout == "active\n"

    def restart(self, service: str, reason: str) -> bool:
        now = time.monotonic()
        if now - self._last_restart.get(service, -RESTART_COOLDOWN_SECONDS) < RESTART_COOLDOWN_SECONDS:
            logger.warning("Skipping restart of %s (cooldown): %s", service, reason)
            return False
        self._last_restart[service] = now
        logger.error("Restarting %s: %s", service, reason)
        subprocess.run(["systemctl", "restart", service], capture_output=True, encoding="utf-8", errors="replace", timeout=120)
        return True

    def main_pid(self, service: str) -> int | None:
        try:
            result = subprocess.run(
                ["systemctl", "show", service, "--property=MainPID", "--value"],
                capture_output=True,
                encoding="utf-8", errors="replace",
                timeout=15,
            )
            pid = int(result.stdout.strip() or 0)
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            return None
        return pid or None

    # ---- checks -------------------------------------------------------------------------
    def check_services(self) -> list[str]:
        restarted = []
        for service in ORION_SERVICES:
            if service == SELF_SERVICE:
                continue
            if not self.is_active(service):
                logger.error("Service %s is not active", service)
                if self.restart(service, "not active"):
                    restarted.append(service)
                    self.slack_alert(f":rotating_light: ORION monitor restarted `{service}` (was not active)")
        return restarted

    def check_disk(self) -> bool:
        path = LOG_DIR if os.path.isdir(LOG_DIR) else "/"
        try:
            free = shutil.disk_usage(path).free
        except OSError as exc:
            logger.warning("disk_usage(%s) failed: %s", path, exc)
            return True
        if free >= MIN_FREE_BYTES:
            return True
        logger.error("Low disk space on %s: %d MB free; vacuuming journal", path, free // (1024 * 1024))
        subprocess.run(["journalctl", "--vacuum-size=1G"], capture_output=True, encoding="utf-8", errors="replace", timeout=300)
        return False

    def api_rss_bytes(self) -> int | None:
        pid = self.main_pid("orion-api")
        if pid is None:
            return None
        try:
            proc = psutil.Process(pid)
            # uvicorn --workers N: the memory lives in the worker children, not the supervisor.
            return proc.memory_info().rss + sum(c.memory_info().rss for c in proc.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def check_memory(self) -> bool:
        rss = self.api_rss_bytes()
        if rss is None or rss <= MAX_API_RSS_BYTES:
            return True
        logger.warning("orion-api RSS %.0f MB exceeds 2 GB", rss / (1024 * 1024))
        self.restart("orion-api", "memory limit exceeded")
        return False

    def check_database(self) -> bool:
        import psycopg2

        try:
            conn = psycopg2.connect(_sync_dsn(settings.sync_database_url), connect_timeout=5)
            conn.close()
            return True
        except psycopg2.Error as exc:
            logger.critical("Database connectivity check failed: %s", exc)
            self.slack_alert(f":red_circle: ORION monitor: database unreachable — {exc}")
            return False

    def slack_alert(self, text: str) -> None:
        if not settings.slack_enabled:
            return
        try:
            requests.post(settings.slack_webhook_url, json={"text": text}, timeout=10)
        except requests.RequestException as exc:
            logger.warning("Slack alert failed: %s", exc)

    def run_once(self) -> dict[str, Any]:
        return {
            "restarted": self.check_services(),
            "disk_ok": self.check_disk(),
            "memory_ok": self.check_memory(),
            "database_ok": self.check_database(),
        }

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        logger.info("ORION monitor daemon started (interval=%ss)", self.interval)
        while self.running:
            try:
                status = self.run_once()
                logger.info("health cycle: %s", status)
            except Exception:  # noqa: BLE001 - the daemon must survive any single failed cycle
                logger.exception("health cycle failed")
            self._stop.wait(self.interval)
        logger.info("ORION monitor daemon stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    OrionMonitorDaemon().run()


if __name__ == "__main__":
    main()
