from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import UTC, datetime
from typing import Any


class JournaldService:
    SERVICE_UNITS = ["orion-api", "orion-worker", "orion-beat", "orion-monitor"]

    async def stream_logs(self, unit_name: str, since_minutes: int = 5) -> list[dict[str, Any]]:
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
        try:
            proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return []
        entries: list[dict[str, Any]] = []

        for raw_line in proc.stdout.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                item = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            entries.append(self._normalize_entry(item, unit_name))
        return entries

    async def get_error_summary(self, since_minutes: int = 5) -> dict[str, Any]:
        total_errors = 0
        total_warnings = 0
        services: dict[str, dict[str, Any]] = {}
        recent_critical_messages: list[str] = []

        for unit_name in self.SERVICE_UNITS:
            logs = await self.stream_logs(unit_name, since_minutes=since_minutes)
            errors = [entry for entry in logs if entry["level"] == "ERROR"]
            warnings = [entry for entry in logs if entry["level"] == "WARNING"]
            criticals = [entry for entry in logs if entry["level"] == "CRITICAL"]

            total_errors += len(errors)
            total_warnings += len(warnings)
            if criticals:
                recent_critical_messages.extend([entry["message"] for entry in criticals][-3:])

            last_error = errors[-1]["message"] if errors else None
            services[unit_name] = {
                "errors": len(errors),
                "warnings": len(warnings),
                "last_error": last_error,
            }

        return {
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "services": services,
            "recent_critical_messages": recent_critical_messages[-10:],
        }

    def _normalize_entry(self, item: dict[str, Any], service: str) -> dict[str, Any]:
        ts_raw = str(item.get("__REALTIME_TIMESTAMP") or "0")
        iso_ts = self._to_iso(ts_raw)
        priority = int(item.get("PRIORITY", 6))
        level = self._priority_to_level(priority)

        return {
            "timestamp": iso_ts,
            "level": level,
            "service": service,
            "message": str(item.get("MESSAGE", "")),
        }

    def _to_iso(self, ts_microseconds: str) -> str:
        try:
            dt = datetime.fromtimestamp(int(ts_microseconds) / 1_000_000, tz=UTC)
            return dt.isoformat()
        except Exception:  # noqa: BLE001
            return datetime.now(tz=UTC).isoformat()

    def _priority_to_level(self, priority: int) -> str:
        if priority <= 2:
            return "CRITICAL"
        if priority == 3:
            return "ERROR"
        if priority == 4:
            return "WARNING"
        if priority <= 6:
            return "INFO"
        return "DEBUG"
