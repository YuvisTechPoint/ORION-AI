import json
from typing import Any
from uuid import UUID

import httpx

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("slack")


def _attachment(color: str, header: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "attachments": [
            {
                "color": color,
                "blocks": [{"type": "header", "text": {"type": "plain_text", "text": header[:150]}}, *blocks],
            }
        ]
    }


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}


class SlackService:
    def __init__(self, webhook_url: str | None = None) -> None:
        self._webhook = webhook_url if webhook_url is not None else settings.slack_webhook_url

    @property
    def enabled(self) -> bool:
        if self._webhook != settings.slack_webhook_url:
            return bool(self._webhook and self._webhook.strip())
        return settings.slack_enabled

    async def _send(self, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(self._webhook, json=payload)
                r.raise_for_status()
        except Exception as exc:
            logger.warning("Slack post failed: %s", exc)

    _post = _send

    async def send_pipeline_start(
        self, run_id: UUID | str, commit_id: str, branch: str, pusher: str
    ) -> None:
        await self._send(
            _attachment(
                "#36a64f",
                "ORION pipeline started",
                [
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Run ID*\n`{run_id}`"},
                            {"type": "mrkdwn", "text": f"*Commit*\n`{commit_id[:8]}`"},
                            {"type": "mrkdwn", "text": f"*Branch*\n`{branch}`"},
                            {"type": "mrkdwn", "text": f"*Pusher*\n{pusher}"},
                        ],
                    }
                ],
            )
        )

    async def send_pipeline_blocked(
        self,
        run_id: UUID | str,
        reason: str,
        agent: str,
        details: dict[str, Any] | str,
        pr_urls: list[str] | None = None,
    ) -> None:
        detail_text = details if isinstance(details, str) else json.dumps(details, default=str)
        text = f"*Run:* `{run_id}`\n*Agent:* {agent}\n*Reason:* {reason}\n*Details:* {detail_text[:1500]}"
        if pr_urls:
            text += "\n*Fix PRs opened:*\n" + "\n".join(f"• <{u}>" for u in pr_urls)
        await self._send(_attachment("#C94040", "ORION pipeline blocked", [_section(text)]))

    async def send_pipeline_deployed(
        self, run_id: UUID | str, commit_id: str, environment: str
    ) -> None:
        await self._send(
            _attachment(
                "#2eb886",
                "ORION deployment complete",
                [
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Run ID*\n`{run_id}`"},
                            {"type": "mrkdwn", "text": f"*Commit*\n`{commit_id[:8]}`"},
                            {"type": "mrkdwn", "text": f"*Environment*\n{environment}"},
                        ],
                    }
                ],
            )
        )

    async def send_monitoring_alert(
        self, run_id: UUID | str, anomalies: list[str], recommended_action: str
    ) -> None:
        color = "#C94040" if recommended_action.startswith("rollback") else "#E8660F"
        lines = "\n".join(f"• {a}" for a in anomalies) or "• (none reported)"
        await self._send(
            _attachment(
                color,
                "ORION monitoring alert",
                [_section(f"*Run:* `{run_id}`\n*Anomalies:*\n{lines}\n*Recommended action:* {recommended_action}")],
            )
        )

    async def send_triage_alert(self, triage: dict[str, Any]) -> None:
        severity = triage.get("incident_severity", "P1")
        actions = "\n".join(
            f"{a.get('step')}. {a.get('action')}" + (f" — `{a['command']}`" if a.get("command") else "")
            for a in triage.get("immediate_actions", [])
            if isinstance(a, dict)
        )
        text = (
            f"*Severity:* {severity}  *Type:* {triage.get('incident_type')}\n"
            f"*Affected:* {', '.join(triage.get('affected_services', []))}\n"
            f"*Root cause:* {triage.get('root_cause')}\n"
            f"*Blast radius:* {triage.get('blast_radius')}\n"
            f"*Escalation reason:* {triage.get('escalation_reason')}\n"
            f"*Immediate actions:*\n{actions}"
        )
        await self._send(_attachment("#8B0000", f"ORION {severity} incident — human escalation", [_section(text)]))

    async def send_incident_p0_alert(
        self,
        *,
        incident_id: str,
        run_id: str,
        repo: str,
        branch: str,
        commit: str,
        severity: str,
        rca_summary: str,
        runbooks: list[dict[str, Any]] | None = None,
        lifecycle_status: str = "investigating",
    ) -> None:
        books = runbooks or []
        runbook_lines = "\n".join(
            f"• `{b.get('runbook_id', '?')}` — {b.get('title', b.get('name', 'runbook'))}"
            for b in books[:3]
        ) or "• (no runbook matched — check incident commander artifact)"
        text = (
            f"*Incident:* `{incident_id}`  *Status:* {lifecycle_status}\n"
            f"*Run:* `{run_id}`  *Repo:* `{repo}`  *Branch:* `{branch}`\n"
            f"*Commit:* `{commit[:8]}`  *Severity:* {severity}\n"
            f"*RCA:* {rca_summary[:1200]}\n"
            f"*Runbooks:*\n{runbook_lines}"
        )
        await self._send(
            _attachment(
                "#8B0000",
                f"ORION P0 — {incident_id} requires immediate response",
                [_section(text)],
            )
        )

    async def send_text(self, text: str) -> None:
        await self._send({"text": text})


slack_service = SlackService()
