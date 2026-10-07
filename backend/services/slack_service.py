"""Slack webhook notifications for canonical pipeline events."""

from __future__ import annotations

import json
from typing import Any

import httpx

from core.config import get_settings
from core.logging_config import get_logger

logger = get_logger("slack")


class SlackService:
    def __init__(self, webhook_url: str | None = None) -> None:
        settings = get_settings()
        self._webhook = (webhook_url if webhook_url is not None else settings.slack_webhook_url or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self._webhook)

    async def send(self, text: str, extra: dict[str, Any] | None = None) -> bool:
        if not self.enabled:
            return False
        payload: dict[str, Any] = {"text": text[:3500]}
        if extra:
            payload.update(extra)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(self._webhook, json=payload)
                r.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Slack notification failed: %s", exc)
            return False

    async def pipeline_started(self, pipeline_id: str, repo_name: str) -> None:
        await self.send(f":rocket: Pipeline `{pipeline_id}` started for *{repo_name}*")

    async def pipeline_blocked(self, pipeline_id: str, reason: str) -> None:
        await self.send(f":no_entry: Pipeline `{pipeline_id}` blocked: {reason}")

    async def pipeline_completed(self, pipeline_id: str, repo_name: str) -> None:
        await self.send(f":white_check_mark: Pipeline `{pipeline_id}` completed for *{repo_name}*")

    async def pipeline_failed(self, pipeline_id: str, reason: str) -> None:
        await self.send(f":x: Pipeline `{pipeline_id}` failed: {reason}")
