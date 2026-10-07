import asyncio
import json
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("journald_service")

ORION_UNITS = ("orion-api", "orion-worker", "orion-beat", "orion-monitor")


def priority_to_level(priority: int | None) -> str:
    if priority is None:
        return "INFO"
    if priority <= 2:
        return "CRITICAL"
    if priority == 3:
        return "ERROR"
    if priority == 4:
        return "WARNING"
    if priority <= 6:
        return "INFO"
    return "DEBUG"


def normalize_entry(raw: dict[str, Any], unit_name: str) -> dict[str, Any]:
    try:
        priority = int(raw.get("PRIORITY")) if raw.get("PRIORITY") is not None else None
    except (TypeError, ValueError):
        priority = None
    ts = raw.get("__REALTIME_TIMESTAMP")
    try:
        iso = datetime.fromtimestamp(int(ts) / 1_000_000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        iso = None
    message = raw.get("MESSAGE", "")
    if isinstance(message, list):
        # journald emits non-UTF8 messages as byte arrays.
        message = bytes(message).decode("utf-8", errors="replace")
    return {
        "timestamp": iso,
        "level": priority_to_level(priority),
        "service": unit_name,
        "message": str(message),
        "identifier": raw.get("SYSLOG_IDENTIFIER"),
    }


class JournaldService:
    @staticmethod
    def available() -> bool:
        return settings.journald_enabled and shutil.which("journalctl") is not None

    async def stream_logs(self, unit_name: str, since_minutes: int = 5) -> list[dict[str, Any]]:
        if not self.available():
            return []
        cmd = [
            "journalctl",
            "-u",
            unit_name,
            "--since",
            f"{since_minutes} minutes ago",
            "-o",
            "json",
            "--no-pager",
        ]

        def _run() -> str:
            try:
                p = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", check=False, timeout=60)
                return p.stdout or ""
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                logger.warning("journalctl failed for %s: %s", unit_name, exc)
                return ""

        raw = await asyncio.to_thread(_run)
        entries: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(normalize_entry(json.loads(line), unit_name))
            except json.JSONDecodeError:
                continue
        return entries

    async def get_error_summary(self, since_minutes: int = 5) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "available": self.available(),
            "total_errors": 0,
            "total_warnings": 0,
            "services": {},
            "recent_critical_messages": [],
        }
        for unit in ORION_UNITS:
            logs = await self.stream_logs(unit, since_minutes=since_minutes)
            errors = [e for e in logs if e["level"] in ("ERROR", "CRITICAL")]
            warnings = [e for e in logs if e["level"] == "WARNING"]
            summary["services"][unit] = {
                "errors": len(errors),
                "warnings": len(warnings),
                "last_error": errors[-1]["message"] if errors else None,
            }
            summary["total_errors"] += len(errors)
            summary["total_warnings"] += len(warnings)
            summary["recent_critical_messages"].extend(
                e["message"] for e in logs if e["level"] == "CRITICAL"
            )
        summary["recent_critical_messages"] = summary["recent_critical_messages"][-20:]
        return summary


journald_service = JournaldService()
