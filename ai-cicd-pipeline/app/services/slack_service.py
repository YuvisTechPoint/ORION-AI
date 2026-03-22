from typing import Any
from uuid import UUID

import httpx

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SlackService:
    def __init__(self) -> None:
        self._webhook = settings.slack_webhook_url

    async def _post(self, payload: dict[str, Any]) -> None:
        if not self._webhook or not self._webhook.strip():
            return
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(self._webhook, json=payload)
                r.raise_for_status()
        except Exception as exc:
            logger.warning("Slack post failed: %s", exc)

    async def send_pipeline_start(
        self,
        run_id: UUID | str,
        commit_id: str,
        branch: str,
        pusher: str,
    ) -> None:
        payload = {
            "attachments": [
                {
                    "color": "#36a64f",
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": "ORION pipeline started",
                            },
                        },
                        {
                            "type": "section",
                            "fields": [
                                {"type": "mrkdwn", "text": f"*Run ID*\n`{run_id}`"},
                                {"type": "mrkdwn", "text": f"*Commit*\n`{commit_id[:8]}`"},
                                {"type": "mrkdwn", "text": f"*Branch*\n`{branch}`"},
                                {"type": "mrkdwn", "text": f"*Pusher*\n{pusher}"},
                            ],
                        },
                    ],
                }
            ]
        }
        await self._post(payload)

    async def send_pipeline_blocked(
        self,
        run_id: UUID | str,
        reason: str,
        agent: str,
        details: str,
    ) -> None:
        payload = {
            "attachments": [
                {
                    "color": "#C94040",
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": "ORION pipeline blocked",
                            },
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*Run:* `{run_id}`\n*Agent:* {agent}\n*Reason:* {reason}\n*Details:* {details}",
                            },
                        },
                    ],
                }
            ]
        }
        await self._post(payload)

    async def send_pipeline_deployed(
        self,
        run_id: UUID | str,
        commit_id: str,
        environment: str,
    ) -> None:
        payload = {
            "attachments": [
                {
                    "color": "#2eb886",
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": "ORION deployment complete",
                            },
                        },
                        {
                            "type": "section",
                            "fields": [
                                {"type": "mrkdwn", "text": f"*Run ID*\n`{run_id}`"},
                                {
                                    "type": "mrkdwn",
                                    "text": f"*Commit*\n`{commit_id[:8]}`",
                                },
                                {
                                    "type": "mrkdwn",
                                    "text": f"*Environment*\n{environment}",
                                },
                            ],
                        },
                    ],
                }
            ]
        }
        await self._post(payload)

    async def send_monitoring_alert(
        self,
        run_id: UUID | str,
        anomalies: list[str],
        recommended_action: str,
    ) -> None:
        lines = "\n".join(f"• {a}" for a in anomalies)
        payload = {
            "attachments": [
                {
                    "color": "#E8660F",
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": "ORION monitoring alert",
                            },
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*Run:* `{run_id}`\n*Anomalies:*\n{lines}\n*Recommended action:* {recommended_action}",
                            },
                        },
                    ],
                }
            ]
        }
        await self._post(payload)


slack_service = SlackService()
