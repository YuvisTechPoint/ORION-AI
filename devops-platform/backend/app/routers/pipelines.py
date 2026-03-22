import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import AgentInput
from app.agents.monitoring import MonitoringAgent
from app.config import get_settings
from app.database import get_db
from app.database_sync import SyncSessionLocal
from app.models import AgentLog, PipelineRun, PipelineStatus, StageResult
from app.orchestrator.pipeline_runner import run_pipeline
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

api_key_header = APIKeyHeader(name="X-Deployment-Key", auto_error=False)


async def optional_deploy_key(
    x_deployment_key: str | None = Security(api_key_header),
) -> str | None:
    return x_deployment_key


@router.post("/pipeline/trigger", response_model=PipelineTriggerResponse)
async def trigger_pipeline(
    body: PipelineTriggerRequest,
    db: AsyncSession = Depends(get_db),
) -> PipelineTriggerResponse:
    settings = get_settings()
    if body.deployment_api_key and body.deployment_api_key != settings.deployment_api_key:
        raise HTTPException(status_code=403, detail="Invalid deployment API key")

    p = PipelineRun(
        id=uuid4(),
        repo_url=body.repo_url,
        commit_sha="",
        status=PipelineStatus.PENDING,
        metadata_json={"repo_url": body.repo_url},
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)

    run_pipeline.delay(str(p.id))
    return PipelineTriggerResponse(pipeline_id=p.id, status=p.status)


@router.get("/pipelines", response_model=list[PipelineListItem])
async def list_pipelines(db: AsyncSession = Depends(get_db)) -> list[PipelineListItem]:
    res = await db.execute(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(20))
    rows = res.scalars().all()
    return [
        PipelineListItem(id=r.id, repo_url=r.repo_url, status=r.status, created_at=r.created_at) for r in rows
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


@router.post("/pipeline/{pipeline_id}/logs/analyze", response_model=LogAnalyzeResponse)
async def analyze_logs(pipeline_id: UUID, body: LogAnalyzeRequest) -> LogAnalyzeResponse:
    sync = SyncSessionLocal()
    try:
        mon = MonitoringAgent(sync)
        out = mon.run(
            AgentInput(
                pipeline_id=pipeline_id,
                stage_name="MONITORING",
                context={"log_text": body.log_text},
            )
        )
        art = out.artifacts.get("monitoring") or {}
        return LogAnalyzeResponse(
            summary=out.summary,
            anomalies=art.get("anomalies", []),
            alerts=art.get("alerts", []),
            health_status=art.get("health_status", "unknown"),
            raw_artifact=art,
        )
    finally:
        sync.close()


@router.post("/pipeline/{pipeline_id}/deploy")
async def trigger_deployment_manual(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    deploy_key: str | None = Depends(optional_deploy_key),
) -> dict:
    settings = get_settings()
    if deploy_key != settings.deployment_api_key:
        raise HTTPException(status_code=403, detail="Invalid deployment key")
    p = await db.get(PipelineRun, pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="pipeline not found")
    run_pipeline.delay(str(p.id))
    return {"ok": True, "queued": str(p.id)}
