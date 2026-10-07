"""Persist incident intelligence and dispatch P0 Slack notifications."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.slack_service import SlackService
from app.utils.artifact_summaries import summarize_artifact
from app.utils.incident_intelligence import build_incident_intelligence_report


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def notify_incident_p0(
    commander: dict[str, Any],
    run: PipelineRun,
    *,
    slack: SlackService | None = None,
) -> bool:
    if str(commander.get("severity", "")).upper() != "P1":
        return False
    if not settings.incident_p0_slack_enabled or not settings.slack_enabled:
        return False

    svc = slack or SlackService()
    rca = commander.get("rca") or {}
    runbooks = commander.get("runbooks") or {}
    await svc.send_incident_p0_alert(
        incident_id=str(commander.get("incident_id") or ""),
        run_id=str(run.id),
        repo=run.repo_full_name,
        branch=run.branch,
        commit=run.commit_id,
        severity=str(commander.get("severity") or "P1"),
        rca_summary=str(rca.get("summary") or commander.get("summary") or ""),
        runbooks=runbooks.get("runbooks") or [],
        lifecycle_status=(commander.get("lifecycle") or {}).get("status") or "investigating",
    )
    return True


async def persist_incident_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    commander: dict[str, Any],
    *,
    slack_notified: bool = False,
    skip_if_present: bool = False,
    existing_artifacts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    existing = existing_artifacts or {}
    if skip_if_present and existing.get("incident_intelligence"):
        return existing["incident_intelligence"]

    report = build_incident_intelligence_report(
        commander,
        run_id=str(run.id),
        repo=run.repo_full_name,
        branch=run.branch,
        commit=run.commit_id,
        slack_notified=slack_notified,
    )
    report["summary"] = summarize_artifact("incident_intelligence", report)
    await _save(db, run.id, "incident_intelligence", report)
    return report
