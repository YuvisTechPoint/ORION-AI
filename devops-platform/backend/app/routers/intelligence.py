"""Intelligence dashboard for devops-platform."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.deployment import resolved_deploy_mode
from app.auth import expected_api_key
from app.config import get_settings
from app.database import get_db
from app.models import PipelineRun, StageResult
from app.orchestrator.dispatch import executor_mode, redis_available
from app.utils.gate_fusion import fuse_stage_results
from app.utils.slo import compute_pipeline_slo
from app.utils.slo_alerts import evaluate_slo_alerts
from app.services.slo_alert_notifier import notify_slo_alerts

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


@router.get("/dashboard")
async def dashboard(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = get_settings()
    res = await db.execute(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(20))
    runs = res.scalars().all()
    by_status: dict[str, int] = {}
    recent: list[dict] = []
    blockers: list[str] = []

    for run in runs:
        st = run.status.value if hasattr(run.status, "value") else str(run.status)
        by_status[st] = by_status.get(st, 0) + 1
        recent.append({"id": str(run.id), "status": st, "repo_url": run.repo_url})
        if st in {"BLOCKED", "FAILED"}:
            sr = await db.execute(select(StageResult).where(StageResult.pipeline_id == run.id))
            stages = {row.stage: row.output_json or {} for row in sr.scalars().all()}
            fused = fuse_stage_results(
                code=stages.get("code_analysis"),
                security=stages.get("security"),
                qa=stages.get("qa"),
                stress=stages.get("stress"),
            )
            blockers.extend(fused.get("violations", [])[:2])

    total = len(runs)
    passed = by_status.get("COMPLETED", 0)
    slo = compute_pipeline_slo(runs)
    alerts = evaluate_slo_alerts(slo)
    background_tasks.add_task(
        notify_slo_alerts,
        "devops-platform",
        alerts,
        webhook_url=settings.slack_webhook_url,
        enabled=settings.slo_alert_slack_enabled,
        cooldown_seconds=settings.slo_alert_cooldown_seconds,
    )
    return {
        "stack": "devops-platform",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "deploy_mode": resolved_deploy_mode(),
        "executor": executor_mode(),
        "redis_available": redis_available(),
        "api_require_auth": settings.api_require_auth,
        "api_key_configured": bool(expected_api_key()),
        "pipelines": {
            "total_recent": total,
            "by_status": by_status,
            "pass_rate": round(passed / total, 2) if total else 0.0,
            "recent": recent[:8],
            "top_blockers": list(dict.fromkeys(blockers))[:6],
        },
        "slo": slo,
        "alerts": alerts,
        "capabilities": {
            "gate_fusion": True,
            "approval_agent": True,
            "orion_multimodal_proxy": True,
            "github_statuses": bool(settings.github_token),
            "slack_alerts": bool(settings.slack_webhook_url),
            "slo_slack_alerts": bool(settings.slack_webhook_url) and settings.slo_alert_slack_enabled,
        },
    }
