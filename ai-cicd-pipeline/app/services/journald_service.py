import asyncio
import json
import subprocess
from typing import Any


class JournaldService:
    _UNITS = (
        "orion-api.service",
        "orion-worker.service",
        "orion-beat.service",
        "orion-monitor.service",
    )

    def _priority_to_level(self, p: int | None) -> str:
        if p is None:
            return "INFO"
        if p <= 2:
            return "CRITICAL"
        if p == 3:
            return "ERROR"
        if p == 4:
            return "WARNING"
        if p in (5, 6):
            return "INFO"
        return "DEBUG"

    async def stream_logs(
        self, unit_name: str, since_minutes: int = 5
    ) -> list[dict[str, Any]]:
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
                p = subprocess.run(
                    cmd, capture_output=True, text=True, check=False, timeout=60
                )
                return p.stdout or ""
            except (FileNotFoundError, subprocess.TimeoutExpired):
                return ""

        raw = await asyncio.to_thread(_run)
        entries: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            pri = obj.get("PRIORITY")
            try:
                pri_int = int(pri) if pri is not None else None
            except (TypeError, ValueError):
                pri_int = None
            entries.append(
                {
                    "unit": unit_name,
                    "message": obj.get("MESSAGE", ""),
                    "level": self._priority_to_level(pri_int),
                    "timestamp": obj.get("__REALTIME_TIMESTAMP"),
                    "raw": obj,
                }
            )
        return entries

    async def get_error_summary(self, since_minutes: int = 5) -> dict[str, Any]:
        totals: dict[str, Any] = {"units": {}, "error_total": 0, "warning_total": 0}
        for unit in self._UNITS:
            logs = await self.stream_logs(unit, since_minutes=since_minutes)
            err = sum(1 for e in logs if e["level"] == "ERROR")
            warn = sum(1 for e in logs if e["level"] == "WARNING")
            crit = sum(1 for e in logs if e["level"] == "CRITICAL")
            totals["units"][unit] = {
                "errors": err,
                "warnings": warn,
                "critical": crit,
                "lines": len(logs),
            }
            totals["error_total"] += err + crit
            totals["warning_total"] += warn
        return totals
