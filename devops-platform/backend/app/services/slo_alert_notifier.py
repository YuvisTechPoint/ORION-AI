"""Slack notifications for SLO breach alerts with per-code cooldown dedupe."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger("slo_alerts")

_lock = threading.Lock()
_last_sent: dict[str, float] = {}


async def notify_slo_alerts(
    stack: str,
    alerts: list[dict[str, Any]],
    *,
    webhook_url: str,
    enabled: bool = True,
    cooldown_seconds: int = 3600,
) -> int:
    url = (webhook_url or "").strip()
    if not enabled or not url or not alerts:
        return 0

    sent = 0
    now = time.time()
    async with httpx.AsyncClient(timeout=15.0) as client:
        for alert in alerts:
            code = str(alert.get("code") or "slo_alert")
            key = f"{stack}:{code}"
            with _lock:
                if now - _last_sent.get(key, 0.0) < cooldown_seconds:
                    continue
                _last_sent[key] = now

            severity = str(alert.get("severity") or "warning").upper()
            message = str(alert.get("message") or code)
            text = f":rotating_light: *SLO alert* [{stack}] `{code}` ({severity})\n{message}"
            try:
                response = await client.post(url, json={"text": text[:3500]})
                response.raise_for_status()
                sent += 1
            except Exception as exc:
                logger.warning("SLO Slack alert failed for %s: %s", key, exc)
    return sent
