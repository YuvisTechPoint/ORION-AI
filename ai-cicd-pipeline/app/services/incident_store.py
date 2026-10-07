"""Query and mutate incident records stored in pipeline artifacts."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.incident_intelligence import build_incident_intelligence_report
from app.utils.incident_lifecycle import transition_lifecycle


async def list_incidents(
    db: AsyncSession,
    *,
    limit: int = 50,
    status: str | None = None,
    severity: str | None = None,
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(PipelineArtifact, PipelineRun)
            .join(PipelineRun, PipelineRun.id == PipelineArtifact.pipeline_run_id)
            .where(PipelineArtifact.artifact_type == "incident_commander_report")
            .order_by(desc(PipelineArtifact.created_at))
            .limit(limit * 3)
        )
    ).all()

    incidents: list[dict[str, Any]] = []
    for artifact, run in rows:
        content = artifact.content if isinstance(artifact.content, dict) else {}
        incident_id = content.get("incident_id")
        if not incident_id:
            continue
        lifecycle = content.get("lifecycle") or {}
        entry = {
            "incident_id": incident_id,
            "run_id": str(run.id),
            "repo": run.repo_full_name,
            "branch": run.branch,
            "commit": run.commit_id,
            "severity": content.get("severity"),
            "status": lifecycle.get("status") or content.get("status"),
            "summary": content.get("summary"),
            "opened_at": lifecycle.get("opened_at"),
            "updated_at": lifecycle.get("updated_at"),
            "artifact_id": str(artifact.id),
        }
        if status and entry["status"] != status:
            continue
        if severity and str(entry["severity"]).upper() != severity.upper():
            continue
        incidents.append(entry)
        if len(incidents) >= limit:
            break
    return incidents


async def get_incident(
    db: AsyncSession,
    incident_id: str,
) -> dict[str, Any] | None:
    rows = (
        await db.execute(
            select(PipelineArtifact, PipelineRun)
            .join(PipelineRun, PipelineRun.id == PipelineArtifact.pipeline_run_id)
            .where(
                PipelineArtifact.artifact_type == "incident_commander_report",
            )
            .order_by(desc(PipelineArtifact.created_at))
            .limit(200)
        )
    ).all()
    for artifact, run in rows:
        content = artifact.content if isinstance(artifact.content, dict) else {}
        if content.get("incident_id") != incident_id:
            continue
        intel_row = (
            await db.execute(
                select(PipelineArtifact).where(
                    PipelineArtifact.pipeline_run_id == run.id,
                    PipelineArtifact.artifact_type == "incident_intelligence",
                )
            )
        ).scalar_one_or_none()
        intel = intel_row.content if intel_row and isinstance(intel_row.content, dict) else None
        return {
            "incident_id": incident_id,
            "run_id": str(run.id),
            "repo": run.repo_full_name,
            "branch": run.branch,
            "commit": run.commit_id,
            "commander": content,
            "intelligence": intel,
        }
    return None


async def transition_incident_status(
    db: AsyncSession,
    incident_id: str,
    new_status: str,
    *,
    note: str = "",
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(PipelineArtifact, PipelineRun)
            .join(PipelineRun, PipelineRun.id == PipelineArtifact.pipeline_run_id)
            .where(PipelineArtifact.artifact_type == "incident_commander_report")
            .order_by(desc(PipelineArtifact.created_at))
            .limit(200)
        )
    ).all()
    for artifact, run in rows:
        content = dict(artifact.content or {})
        if content.get("incident_id") != incident_id:
            continue

        lifecycle = content.get("lifecycle") or {}
        content["lifecycle"] = transition_lifecycle(lifecycle, new_status, note=note)
        content["status"] = content["lifecycle"]["status"]
        artifact.content = content

        intel_report = build_incident_intelligence_report(
            content,
            run_id=str(run.id),
            repo=run.repo_full_name,
            branch=run.branch,
            commit=run.commit_id,
            slack_notified=bool((content.get("notifications") or {}).get("slack_p0_sent")),
        )
        intel_row = (
            await db.execute(
                select(PipelineArtifact).where(
                    PipelineArtifact.pipeline_run_id == run.id,
                    PipelineArtifact.artifact_type == "incident_intelligence",
                )
            )
        ).scalar_one_or_none()
        if intel_row:
            intel_row.content = intel_report
        else:
            db.add(
                PipelineArtifact(
                    pipeline_run_id=run.id,
                    artifact_type="incident_intelligence",
                    content=intel_report,
                )
            )

        await db.commit()
        return {
            "incident_id": incident_id,
            "run_id": str(run.id),
            "lifecycle": content["lifecycle"],
            "intelligence": intel_report,
        }

    raise LookupError(f"Incident not found: {incident_id}")
