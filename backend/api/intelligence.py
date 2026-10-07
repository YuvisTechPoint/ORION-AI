"""Cross-stack intelligence dashboard API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends

from api.auth import optional_pipeline_auth
from api.routes import get_orchestrator
from core.config import Settings, get_settings
from core.gate_fusion import fuse_stage_results
from core.slo import compute_pipeline_slo
from core.slo_alert_notifier import notify_slo_alerts
from core.slo_alerts import evaluate_slo_alerts
from services.orchestrator import Orchestrator

router = APIRouter(prefix="/api/v1/intelligence", tags=["Intelligence"])


def _summarize_runs(runs: list[Any]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    recent: list[dict[str, Any]] = []
    blockers: list[str] = []

    for item in runs:
        status = str(getattr(item, "status", None) or item.get("status", "unknown"))
        by_status[status] = by_status.get(status, 0) + 1
        pid = getattr(item, "pipeline_id", None) or item.get("pipeline_id") or item.get("id")
        stage = getattr(item, "current_stage", None) or item.get("current_stage", "")
        recent.append({"id": str(pid), "status": status, "stage": stage})
        if status in {"blocked", "blocked_with_prs_sent", "failed"}:
            art = getattr(item, "artifacts", None) or item.get("artifacts") or {}
            if isinstance(art, dict):
                fused = fuse_stage_results(
                    code=art.get("code_analysis"),
                    security=art.get("security"),
                    qa=art.get("qa"),
                    stress=art.get("stress"),
                )
                blockers.extend(fused.get("violations", [])[:2])

    total = len(runs)
    passed = sum(by_status.get(s, 0) for s in ("completed", "COMPLETED", "deployed"))
    return {
        "total_recent": total,
        "by_status": by_status,
        "pass_rate": round(passed / total, 2) if total else 0.0,
        "recent": recent[:8],
        "top_blockers": list(dict.fromkeys(blockers))[:6],
    }


@router.get("/dashboard")
def intelligence_dashboard(
    background_tasks: BackgroundTasks,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    settings: Settings = Depends(get_settings),
    _auth: dict = Depends(optional_pipeline_auth),
) -> dict[str, Any]:
    runs = orchestrator.list_pipelines(limit=20)
    summary = _summarize_runs(runs)
    slo = compute_pipeline_slo(runs)
    alerts = evaluate_slo_alerts(slo)
    background_tasks.add_task(
        notify_slo_alerts,
        "canonical",
        alerts,
        webhook_url=settings.slack_webhook_url,
        enabled=settings.slo_alert_slack_enabled,
        cooldown_seconds=settings.slo_alert_cooldown_seconds,
    )
    return {
        "stack": "canonical",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "retriever_backend": settings.retriever_backend,
        "agent_memory_enabled": settings.agent_memory_enabled,
        "pipelines": summary,
        "slo": slo,
        "alerts": alerts,
        "capabilities": {
            "gate_fusion": True,
            "hybrid_retriever": settings.retriever_backend in {"hybrid", "files", "chunk"},
            "correlated_monitoring": True,
            "slo_slack_alerts": bool(settings.slack_webhook_url) and settings.slo_alert_slack_enabled,
            "policy_engine": "heuristic",
            "bandit_scanner": settings.security_scanners_enabled,
            "pip_audit_scanner": settings.security_scanners_enabled,
            "secrets_guardian": False,
            "performance_baseline_persist": False,
            "performance_baseline_gate": False,
            "otel_export": False,
        },
    }
