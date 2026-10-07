import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import AgentInput
from app.agents.monitoring import MonitoringAgent
from app.auth import optional_auth
from app.config import get_settings
from app.database import get_db
from app.database_sync import SyncSessionLocal
from app.models import AgentLog, PipelineRun, PipelineStatus, StageResult
from app.orchestrator.dispatch import dispatch_pipeline, executor_mode, redis_available
from app.services.audit_trail import append_audit_async, list_audit_events
from app.utils.text_analysis import classify_log_type, sanitize_for_agent
from app.schemas import (
    AgentLogOut,
    HealthResponse,
    LogAnalyzeRequest,
    LogAnalyzeResponse,
    PipelineDetailResponse,
    PipelineListItem,
    PipelineStatusLight,
    PipelineTriggerRequest,
    PipelineTriggerResponse,
    StageResultOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["pipelines"])

RETRYABLE_STATUSES = frozenset(
    {PipelineStatus.BLOCKED, PipelineStatus.FAILED, PipelineStatus.CANCELLED}
)
RESUMABLE_STATUSES = frozenset({PipelineStatus.FAILED, PipelineStatus.CANCELLED})

api_key_header = APIKeyHeader(name="X-Deployment-Key", auto_error=False)


async def optional_deploy_key(
    x_deployment_key: str | None = Security(api_key_header),
) -> str | None:
    return x_deployment_key


@router.post("/pipeline/trigger", response_model=PipelineTriggerResponse)
async def trigger_pipeline(
    body: PipelineTriggerRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> PipelineTriggerResponse:
    settings = get_settings()
    if body.deployment_api_key and body.deployment_api_key != settings.deployment_api_key:
        raise HTTPException(status_code=403, detail="Invalid deployment API key")

    p = PipelineRun(
        id=uuid4(),
        repo_url=body.repo_url,
        commit_sha="",
        status=PipelineStatus.PENDING,
        metadata_json={
            "repo_url": body.repo_url,
            "correlation_id": getattr(request.state, "correlation_id", None),
            "trace_id": getattr(request.state, "trace_id", None),
        },
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)

    executor = dispatch_pipeline(str(p.id))
    return PipelineTriggerResponse(pipeline_id=p.id, status=p.status, executor=executor)


@router.get("/pipelines", response_model=list[PipelineListItem])
async def list_pipelines(db: AsyncSession = Depends(get_db)) -> list[PipelineListItem]:
    res = await db.execute(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(20))
    rows = res.scalars().all()
    return [
        PipelineListItem(
            id=r.id,
            repo_url=r.repo_url,
            status=r.status,
            created_at=r.created_at,
            correlation_id=(r.metadata_json or {}).get("correlation_id") if isinstance(r.metadata_json, dict) else None,
        )
        for r in rows
    ]


@router.get("/pipeline/{pipeline_id}", response_model=PipelineDetailResponse)
async def get_pipeline(pipeline_id: UUID, db: AsyncSession = Depends(get_db)) -> PipelineDetailResponse:
    p = await db.get(PipelineRun, pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="pipeline not found")

    logs_res = await db.execute(select(AgentLog).where(AgentLog.pipeline_id == pipeline_id).order_by(AgentLog.timestamp))
    logs = logs_res.scalars().all()
    sr_res = await db.execute(select(StageResult).where(StageResult.pipeline_id == pipeline_id))
    srs = sr_res.scalars().all()

    return PipelineDetailResponse(
        id=p.id,
        repo_url=p.repo_url,
        commit_sha=p.commit_sha,
        status=p.status,
        created_at=p.created_at,
        updated_at=p.updated_at,
        metadata_json=p.metadata_json,
        logs=[
            AgentLogOut(
                id=x.id,
                stage=x.stage,
                level=x.level,
                message=x.message,
                timestamp=x.timestamp,
                artifact_json=x.artifact_json,
            )
            for x in logs
        ],
        stage_results=[
            StageResultOut(
                id=x.id,
                stage=x.stage,
                passed=x.passed,
                output_json=x.output_json,
                created_at=x.created_at,
            )
            for x in srs
        ],
    )


@router.get("/pipeline/{pipeline_id}/status", response_model=PipelineStatusLight)
async def get_pipeline_status(pipeline_id: UUID, db: AsyncSession = Depends(get_db)) -> PipelineStatusLight:
    p = await db.get(PipelineRun, pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="pipeline not found")
    current = p.status.value if hasattr(p.status, "value") else str(p.status)
    return PipelineStatusLight(id=p.id, status=p.status, current_stage=current)


@router.get("/pipeline/{pipeline_id}/audit")
async def get_pipeline_audit(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict:
    p = await db.get(PipelineRun, pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="pipeline not found")
    events = list_audit_events(p)
    return {"pipeline_id": str(pipeline_id), "events": events, "total": len(events)}


@router.post("/pipeline/{pipeline_id}/retry")
async def retry_pipeline(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(optional_auth),
) -> dict:
    p = await db.get(PipelineRun, pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="pipeline not found")
    if p.status not in RETRYABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Run in status '{p.status.value}' cannot be retried; "
                "only BLOCKED, FAILED or CANCELLED runs can."
            ),
        )
    meta = dict(p.metadata_json or {})
    meta.pop("cancelled", None)
    meta.pop("resume", None)
    p.metadata_json = meta
    p.status = PipelineStatus.PENDING
    await db.commit()
    await append_audit_async(
        db,
        pipeline_id,
        action="pipeline.retry",
        user=user,
        outcome="pending",
        details={"mode": "full"},
    )
    executor = dispatch_pipeline(str(p.id))
    return {"ok": True, "status": "retrying", "pipeline_id": str(p.id), "executor": executor}


@router.post("/pipeline/{pipeline_id}/resume")
async def resume_pipeline(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(optional_auth),
) -> dict:
    p = await db.get(PipelineRun, pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="pipeline not found")
    if p.status not in RESUMABLE_STATUSES:
        raise HTTPException(status_code=409, detail="Only FAILED or CANCELLED runs can be resumed")
    sr = await db.execute(select(StageResult).where(StageResult.pipeline_id == pipeline_id))
    stages = {row.stage for row in sr.scalars().all()}
    if not stages.intersection({"code_analysis", "security", "qa", "stress"}):
        raise HTTPException(status_code=409, detail="No stage checkpoints found; use retry instead")
    meta = dict(p.metadata_json or {})
    meta["resume"] = True
    meta.pop("cancelled", None)
    p.metadata_json = meta
    p.status = PipelineStatus.PENDING
    await db.commit()
    await append_audit_async(
        db,
        pipeline_id,
        action="pipeline.resume",
        user=user,
        outcome="pending",
        details={"checkpoints": sorted(stages)},
    )
    executor = dispatch_pipeline(str(p.id), resume=True)
    return {"ok": True, "status": "resuming", "pipeline_id": str(p.id), "executor": executor, "resume": True}


@router.post("/pipeline/{pipeline_id}/logs/analyze", response_model=LogAnalyzeResponse)
async def analyze_logs(
    pipeline_id: UUID,
    body: LogAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> LogAnalyzeResponse:
    from app.utils.gate_fusion import correlate_logs_with_gates, fuse_stage_results

    sanitized = sanitize_for_agent(body.log_text)
    detected_log_type = classify_log_type(sanitized)

    sr = await db.execute(select(StageResult).where(StageResult.pipeline_id == pipeline_id))
    stages = {row.stage: row.output_json or {} for row in sr.scalars().all()}
    gate = fuse_stage_results(
        code=stages.get("code_analysis"),
        security=stages.get("security"),
        qa=stages.get("qa"),
        stress=stages.get("stress"),
    )
    correlation = correlate_logs_with_gates(sanitized, gate)

    sync = SyncSessionLocal()
    try:
        mon = MonitoringAgent(sync)
        out = mon.run(
            AgentInput(
                pipeline_id=pipeline_id,
                stage_name="MONITORING",
                context={
                    "log_text": sanitized,
                    "detected_log_type": detected_log_type,
                    "gate_fusion": gate,
                    "gate_correlation": correlation,
                },
            )
        )
        art = out.artifacts.get("monitoring") or {}
        alerts = list(art.get("alerts", []))
        if correlation.get("correlation_hints"):
            alerts = list(dict.fromkeys([*alerts, *correlation["correlation_hints"]]))
        return LogAnalyzeResponse(
            summary=out.summary,
            anomalies=art.get("anomalies", []),
            alerts=alerts,
            health_status=art.get("health_status", "unknown"),
            detected_log_type=detected_log_type,
            gate_correlation=correlation or None,
            raw_artifact={**art, "gate_fusion": gate},
        )
    finally:
        sync.close()


@router.post("/pipeline/{pipeline_id}/deploy")
async def trigger_deployment_manual(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    deploy_key: str | None = Depends(optional_deploy_key),
    _: dict = Depends(optional_auth),
) -> dict:
    settings = get_settings()
    if deploy_key != settings.deployment_api_key:
        raise HTTPException(status_code=403, detail="Invalid deployment key")
    p = await db.get(PipelineRun, pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="pipeline not found")
    executor = dispatch_pipeline(str(p.id))
    return {"ok": True, "queued": str(p.id), "executor": executor}


@router.post("/pipeline/{pipeline_id}/cancel")
async def cancel_pipeline(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(optional_auth),
) -> dict:
    p = await db.get(PipelineRun, pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="pipeline not found")
    meta = dict(p.metadata_json or {})
    meta["cancelled"] = True
    p.metadata_json = meta
    p.status = PipelineStatus.CANCELLED
    await db.commit()
    await append_audit_async(
        db,
        pipeline_id,
        action="pipeline.cancel",
        user=user,
        outcome="cancelled",
        details={},
    )
    return {"ok": True, "status": p.status.value, "pipeline_id": str(p.id)}
