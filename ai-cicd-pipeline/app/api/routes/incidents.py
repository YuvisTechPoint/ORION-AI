"""Incident Command Center API — lifecycle, commander bundle, and on-demand analysis."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.incident_enrichment import persist_incident_intelligence
from app.api.routes.auth import optional_auth
from app.config import settings
from app.database import get_db
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.incident_store import get_incident, list_incidents, transition_incident_status
from app.services.phase3_enrichment import run_phase3_incident_response
from app.utils.incident_intelligence import build_incident_intelligence_report

router = APIRouter(prefix="/incidents", tags=["Incidents"])


class IncidentTransitionRequest(BaseModel):
    status: str = Field(..., description="investigating | mitigated | resolved | closed")
    note: str = Field(default="", max_length=2000)


class IncidentTriggerRequest(BaseModel):
    pipeline_run_id: str
    log_excerpt: str | None = None
    metrics: dict[str, Any] | None = None
    notify_slack: bool = Field(default=True)


class IncidentIntelRequest(BaseModel):
    pipeline_run_id: str | None = None
    incident_id: str | None = None
    use_llm: bool = Field(default=False)


@router.get("")
async def incidents_list(
    limit: int = 50,
    status: str | None = None,
    severity: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    items = await list_incidents(db, limit=limit, status=status, severity=severity)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "items": items,
    }


@router.get("/{incident_id}")
async def incidents_get(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    record = await get_incident(db, incident_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"generated_at": datetime.now(timezone.utc).isoformat(), **record}


@router.post("/{incident_id}/transition")
async def incidents_transition(
    incident_id: str,
    body: IncidentTransitionRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    try:
        result = await transition_incident_status(
            db,
            incident_id,
            body.status,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"generated_at": datetime.now(timezone.utc).isoformat(), **result}


@router.post("/trigger")
async def incidents_trigger(
    body: IncidentTriggerRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    """Run incident commander bundle for a pipeline run (same path as MonitoringAgent escalation)."""
    try:
        run_id = uuid.UUID(body.pipeline_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid pipeline_run_id") from exc

    run = await db.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    rows = (
        await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == run.id))
    ).scalars().all()
    artifacts = {a.artifact_type: a.content or {} for a in rows}

    commander = await run_phase3_incident_response(
        db,
        run,
        artifacts=artifacts,
        metrics=body.metrics,
        log_excerpt=body.log_excerpt or "",
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "incident_id": commander.get("incident_id"),
        "commander": commander,
    }


@router.post("/analyze")
async def incidents_analyze(
    body: IncidentIntelRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    """Build or refresh incident_intelligence report from stored commander artifacts."""
    commander: dict[str, Any] | None = None
    run: PipelineRun | None = None

    if body.incident_id:
        record = await get_incident(db, body.incident_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        commander = record.get("commander") or {}
        run = await db.get(PipelineRun, uuid.UUID(record["run_id"]))
    elif body.pipeline_run_id:
        try:
            run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pipeline_run_id") from exc
        run = await db.get(PipelineRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        row = (
            await db.execute(
                select(PipelineArtifact).where(
                    PipelineArtifact.pipeline_run_id == run.id,
                    PipelineArtifact.artifact_type == "incident_commander_report",
                )
            )
        ).scalar_one_or_none()
        commander = (row.content or {}) if row else None
    else:
        raise HTTPException(status_code=400, detail="Provide incident_id or pipeline_run_id")

    if not commander or not run:
        raise HTTPException(status_code=404, detail="Incident commander report not found")

    if body.use_llm and settings.llm_enabled:
        report = build_incident_intelligence_report(
            commander,
            run_id=str(run.id),
            repo=run.repo_full_name,
            branch=run.branch,
            commit=run.commit_id,
            slack_notified=bool((commander.get("notifications") or {}).get("slack_p0_sent")),
        )
        db.add(
            PipelineArtifact(
                pipeline_run_id=run.id,
                artifact_type="incident_intelligence",
                content=report,
            )
        )
        await db.commit()
    else:
        report = await persist_incident_intelligence(db, run, commander)
        await db.commit()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "incident_id": commander.get("incident_id"),
        "report": report,
    }
