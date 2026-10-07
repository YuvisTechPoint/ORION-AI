"""Cross-stack intelligence dashboard for ORION CI/CD."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.deployment_intelligence_agent import DeploymentIntelligenceAgent
from app.agents.observability_intelligence_agent import ObservabilityIntelligenceAgent
from app.agents.performance_intelligence_agent import PerformanceIntelligenceAgent
from app.agents.repository_intelligence_agent import RepositoryIntelligenceAgent
from app.agents.test_intelligence_agent import TestIntelligenceAgent
from app.api.routes.auth import optional_auth
from app.config import settings
from app.database import get_db
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.git_service import GitService
from app.tasks.dispatch import executor_mode
from app.services.slo import compute_pipeline_slo
from app.services.slo_alert_notifier import notify_slo_alerts
from app.services.audit_trail import list_audit_events
from app.utils.audit_explorer import explore_audit_events
from app.utils.agent_mesh_intelligence import build_agent_mesh_intelligence_report
from app.utils.agent_mesh_registry import build_agent_mesh_registry
from app.utils.agent_mesh_router import route_mesh_event, route_mesh_intent
from app.utils.agent_mesh_topology import build_mesh_topology
from app.utils.agent_registry import build_agent_registry
from app.services.finops_enrichment import persist_finops_intelligence
from app.services.release_enrichment import persist_release_intelligence
from app.services.governance_enrichment import persist_ai_governance_intelligence
from app.utils.finops_intelligence import build_finops_intelligence_report, build_fleet_cost_rollup
from app.utils.finops_registry import resolve_finops_budgets
from app.utils.release_intelligence import build_release_intelligence_report, compute_dora_metrics
from app.utils.release_intelligence_registry import resolve_release_policy
from app.services.mesh_enrichment import persist_agent_mesh_intelligence, persist_agent_mesh_snapshot
from app.utils.ai_governance_intelligence import build_ai_governance_intelligence_report, build_escalation_queue
from app.utils.ai_governance_registry import build_governance_policy_catalog
from app.services.hybrid_retriever import build_retriever, index_repository
from app.services.memory_store import build_memory_store
from app.services.rag_enrichment import persist_rag_intelligence
from app.utils.devops_rag import query_devops_rag
from app.utils.rag_intelligence import build_rag_intelligence_report
from app.utils.enterprise_sso import assess_sso_readiness
from app.utils.fleet_view import build_fleet_view
from app.utils.gate_fusion import fuse_stage_results
from app.utils.error_budget import compute_error_budget
from app.utils.repository_intelligence import analyze_repository
from app.utils.security import validate_remote_clone_url
from app.utils.slo_alerts import evaluate_slo_alerts
from app.utils.test_intelligence import build_test_intelligence_report
from app.services.catalog_enrichment import persist_service_catalog, persist_service_catalog_intelligence
from app.services.cloud_enrichment import persist_cloud_intelligence
from app.utils.cloud_intelligence import build_cloud_intelligence_report
from app.utils.service_catalog import build_service_catalog, merge_fleet_catalogs
from app.utils.service_catalog_intelligence import build_service_catalog_intelligence_report
from app.utils.service_catalog_registry import build_idp_portal_catalog
from app.utils.cloud_target_registry import build_cloud_target_catalog, resolve_cloud_target
from app.utils.deployment_intelligence import build_deployment_intelligence_report
from app.utils.kubernetes_manifest import scan_kubernetes_manifests
from app.utils.observability_intelligence import build_observability_intelligence_report
from app.utils.multimodal_intelligence import build_multimodal_intelligence_report, build_route_report
from app.utils.multimodal_registry import build_multimodal_catalog_report
from app.utils.code_review_intelligence import build_code_review_intelligence_report
from app.utils.dast_scan import build_dast_report, evaluate_dast_gates
from app.utils.performance_intelligence import build_performance_intelligence_report, resolve_stress_profile

router = APIRouter(prefix="/intelligence", tags=["Intelligence"])


class RepositoryIntelRequest(BaseModel):
    repo_path: str | None = Field(default=None, max_length=4000, description="Local checkout path (non-production)")
    clone_url: str | None = Field(default=None, max_length=2000)
    branch: str = Field(default="main", max_length=200)
    repo_full_name: str | None = Field(default=None, max_length=255)
    pipeline_run_id: str | None = Field(default=None, description="Persist artifact on an existing run")
    changed_files: list[str] | None = None
    diff_text: str | None = None
    use_llm: bool = Field(default=True, description="Augment heuristics with Claude when configured")


class TestIntelRequest(BaseModel):
    repo_path: str | None = Field(default=None, max_length=4000)
    clone_url: str | None = Field(default=None, max_length=2000)
    branch: str = Field(default="main", max_length=200)
    pipeline_run_id: str | None = None
    changed_files: list[str] | None = None
    diff_text: str | None = None
    run_live_coverage: bool = Field(default=False)
    use_llm: bool = Field(default=False)


class PerformanceIntelRequest(BaseModel):
    pipeline_run_id: str | None = None
    stress_report: dict[str, Any] | None = None
    stress_profile: str | None = None
    use_llm: bool = Field(default=False)


class DastIntelRequest(BaseModel):
    target_url: str | None = None
    pipeline_run_id: str | None = None


class CodeReviewIntelRequest(BaseModel):
    pipeline_run_id: str | None = None
    code_analysis: dict[str, Any] | None = None
    security_scan: dict[str, Any] | None = None
    qa_report: dict[str, Any] | None = None
    service_graph: dict[str, Any] | None = None
    repository_intelligence: dict[str, Any] | None = None
    change_risk_report: dict[str, Any] | None = None
    stress_report: dict[str, Any] | None = None
    performance_intelligence: dict[str, Any] | None = None
    changed_files: list[str] | None = None


class DeploymentIntelRequest(BaseModel):
    pipeline_run_id: str | None = None
    deployment_info: dict[str, Any] | None = None
    progressive_delivery: dict[str, Any] | None = None
    error_budget_report: dict[str, Any] | None = None
    stress_report: dict[str, Any] | None = None
    change_risk_report: dict[str, Any] | None = None
    use_llm: bool = Field(default=False)


class ObservabilityIntelRequest(BaseModel):
    pipeline_run_id: str | None = None
    deployment_info: dict[str, Any] | None = None
    otel_trace_context: dict[str, Any] | None = None
    synthetic_monitoring_report: dict[str, Any] | None = None
    stress_report: dict[str, Any] | None = None
    error_budget_report: dict[str, Any] | None = None
    service_graph: dict[str, Any] | None = None
    monitoring_summary: dict[str, Any] | None = None
    change_risk_report: dict[str, Any] | None = None
    log_excerpt: str | None = None
    use_llm: bool = Field(default=False)


class MultimodalIntelRequest(BaseModel):
    pipeline_run_id: str | None = None
    route_text: str | None = Field(default=None, max_length=50000)
    preferred_agent: str | None = Field(default=None, max_length=100)
    persist: bool = Field(default=True)


class CloudIntelRequest(BaseModel):
    pipeline_run_id: str | None = None
    repo: str | None = Field(default=None, max_length=255)
    repo_path: str | None = Field(default=None, max_length=4000)
    environment: str | None = Field(default=None, max_length=100)
    deploy_mode: str | None = Field(default=None, max_length=50)
    persist: bool = Field(default=True)


class CatalogIntelRequest(BaseModel):
    pipeline_run_id: str | None = None
    repo: str | None = Field(default=None, max_length=255)
    repo_path: str | None = Field(default=None, max_length=4000)
    include_fleet: bool = Field(default=True)
    persist: bool = Field(default=True)


class MeshRouteRequest(BaseModel):
    intent: str = Field(default="", max_length=5000)
    preferred_agent: str | None = Field(default=None, max_length=100)
    event_id: str | None = Field(default=None, max_length=100)


class FinOpsIntelRequest(BaseModel):
    pipeline_run_id: str | None = None
    include_fleet: bool = Field(default=True)
    persist: bool = Field(default=True)


class ReleaseIntelRequest(BaseModel):
    pipeline_run_id: str | None = None
    include_fleet: bool = Field(default=True)
    persist: bool = Field(default=True)
    environment: str = Field(default="staging", max_length=64)
    deploy_mode: str = Field(default="auto", max_length=32)


class GovernanceIntelRequest(BaseModel):
    pipeline_run_id: str | None = None
    persist: bool = Field(default=True)


class MeshIntelRequest(BaseModel):
    pipeline_run_id: str | None = None
    intent: str = Field(default="", max_length=5000)
    persist: bool = Field(default=True)


class RagIntelRequest(BaseModel):
    query: str = Field(default="", max_length=5000)
    pipeline_run_id: str | None = None
    repo_path: str | None = Field(default=None, max_length=4000)
    persist: bool = Field(default=True)
    index_repo: bool = Field(default=True)


async def _artifacts_for_runs(db: AsyncSession, run_ids: list[Any]) -> dict[str, dict[str, dict[str, Any]]]:
    if not run_ids:
        return {}
    rows = (
        await db.execute(
            select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id.in_(run_ids))
        )
    ).scalars().all()
    by_run: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        rid = str(row.pipeline_run_id)
        by_run.setdefault(rid, {})[row.artifact_type] = row.content or {}
    return by_run


@router.get("/dashboard")
async def intelligence_dashboard(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    runs = (
        await db.execute(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(20))
    ).scalars().all()

    by_status: dict[str, int] = {}
    recent: list[dict[str, Any]] = []
    blockers: list[str] = []

    for run in runs:
        status = str(run.status)
        by_status[status] = by_status.get(status, 0) + 1
        recent.append(
            {
                "id": str(run.id),
                "status": status,
                "repo": run.repo_full_name,
                "branch": run.branch,
            }
        )
        if status.startswith("blocked") or status in {"failed", "rejected"}:
            arts = (
                await db.execute(
                    select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == run.id)
                )
            ).scalars().all()
            latest = {a.artifact_type: a.content or {} for a in arts}
            fused = fuse_stage_results(
                code=latest.get("code_analysis"),
                security=latest.get("security_scan"),
                qa=latest.get("qa_report"),
                stress=latest.get("stress_report"),
            )
            blockers.extend(fused.get("violations", [])[:2])
            change_risk = latest.get("change_risk_report") or {}
            if change_risk.get("final_risk") is not None and change_risk.get("risk_level") == "high":
                blockers.append(f"high change risk ({change_risk.get('final_risk')}/100)")

    total = len(runs)
    passed = sum(by_status.get(s, 0) for s in ("deployed", "approved", "monitoring"))
    llm_mode = "live" if settings.anthropic_api_key else "heuristic"
    slo = compute_pipeline_slo(runs)
    error_budget = compute_error_budget(slo, target_availability=settings.slo_target_availability)
    alerts = evaluate_slo_alerts(slo)
    background_tasks.add_task(
        notify_slo_alerts,
        "orion",
        alerts,
        webhook_url=settings.slack_webhook_url if settings.slack_enabled else "",
        enabled=settings.slo_alert_slack_enabled and settings.slack_enabled,
        cooldown_seconds=settings.slo_alert_cooldown_seconds,
    )

    arts_by_run = await _artifacts_for_runs(db, [run.id for run in runs])
    cost_total = 0.0
    budget_violations = 0
    compliance_scores: list[float] = []
    for run in runs:
        arts = arts_by_run.get(str(run.id)) or {}
        finops_intel = arts.get("finops_intelligence") or {}
        cost = finops_intel.get("cost_report") or arts.get("cost_report") or {}
        cost_total += float(cost.get("total_usd_estimate") or 0)
        if finops_intel.get("gate_verdict") in {"fail", "warn"}:
            budget_violations += 1
        comp = arts.get("compliance_report") or {}
        if comp.get("overall_score_percent") is not None:
            compliance_scores.append(float(comp["overall_score_percent"]))

    budgets = resolve_finops_budgets()
    finops = {
        "recent_runs": len(runs),
        "total_usd_estimate": round(cost_total, 4),
        "avg_cost_per_run": round(cost_total / len(runs), 4) if runs else 0.0,
        "budget_violations": budget_violations,
        "per_run_budget_usd": budgets.get("per_run_usd"),
        "monthly_budget_usd": budgets.get("monthly_usd"),
    }
    compliance_summary = {
        "avg_score_percent": round(sum(compliance_scores) / len(compliance_scores), 1) if compliance_scores else None,
        "packs_enabled": settings.compliance_pack_list,
    }

    return {
        "stack": "orion",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "deploy_mode": settings.deploy_mode,
        "executor": executor_mode(),
        "llm_mode": llm_mode,
        "pipelines": {
            "total_recent": total,
            "by_status": by_status,
            "pass_rate": round(passed / total, 2) if total else 0.0,
            "recent": recent[:8],
            "top_blockers": list(dict.fromkeys(blockers))[:6],
        },
        "slo": slo,
        "error_budget": error_budget,
        "finops": finops,
        "compliance": compliance_summary,
        "sso": assess_sso_readiness(),
        "alerts": alerts,
        "capabilities": {
            "gate_fusion": True,
            "change_risk_engine": True,
            "service_graph": True,
            "sbom": True,
            "secrets_guardian": True,
            "container_security": True,
            "iac_security": True,
            "test_intelligence": True,
            "release_passport": True,
            "release_intelligence": True,
            "release_dora": True,
            "autonomous_fix_loop": True,
            "patch_confidence": True,
            "progressive_delivery": True,
            "pr_intelligence": True,
            "developer_ux": True,
            "vscode_extension": True,
            "github_app": True,
            "full_scan_parallel": True,
            "auto_pr": bool((settings.github_token or "").strip()),
            "correlated_monitoring": True,
            "slo_slack_alerts": settings.slack_enabled and settings.slo_alert_slack_enabled,
            "incident_commander": True,
            "evidence_graph": True,
            "automated_rca": True,
            "postmortem_generator": True,
            "runbook_automation": True,
            "otel_trace_context": True,
            "error_budget_engine": True,
            "synthetic_monitoring": True,
            "chaos_engineering": True,
            "reliability_intelligence": True,
            "disaster_recovery": True,
            "dr_intelligence": True,
            "knowledge_graph": True,
            "knowledge_graph_intelligence": True,
            "autopilot": True,
            "autopilot_intelligence": True,
            "unified_risk": True,
            "unified_risk_intelligence": True,
            "policy_engine": True,
            "compliance_packs": True,
            "signed_builds": True,
            "tenant_rbac": True,
            "finops": True,
            "finops_intelligence": True,
            "finops_budgets": True,
            "audit_explorer": True,
            "fleet_view": True,
            "enterprise_sso": True,
            "enterprise_iam": True,
            "iam_intelligence": True,
            "agent_registry": True,
            "agent_mesh": True,
            "agent_mesh_router": True,
            "ai_governance": True,
            "ai_governance_escalations": True,
            "model_router": True,
            "prompt_registry": True,
            "agent_eval": True,
            "decision_ledger": True,
            "prompt_injection_firewall": True,
            "devops_rag": True,
            "rag_intelligence": True,
            "agent_memory": True,
            "memory_gateway": settings.memory_gateway_enabled,
            "platform_event_bus": settings.event_bus_enabled,
            "hybrid_retriever": True,
            "repository_intelligence": True,
            "external_scanners": True,
            "supply_chain_report": True,
            "test_intelligence": True,
            "performance_intelligence": True,
            "code_review_intelligence": True,
            "dast_scan": settings.security_zap_enabled,
            "epss_enrichment": settings.epss_enabled,
            "sbom_syft": settings.sbom_syft_enabled,
            "deployment_intelligence": True,
            "observability_intelligence": True,
            "incident_command_center": True,
            "remediation_intelligence": True,
            "policy_intelligence": True,
            "enterprise_approval": True,
            "approval_intelligence": True,
            "multimodal_expansion": True,
            "multimodal_router": True,
            "multimodal_intelligence": True,
            "cloud_intelligence": True,
            "kubernetes_manifest_scan": True,
            "service_catalog": True,
            "service_catalog_intelligence": True,
            "idp_portal": True,
            "scoped_policies": True,
            "ai_autonomy_policies": True,
            "policy_engine": settings.policy_engine,
            "opa_adapter": bool((settings.opa_url or "").strip()),
            "bandit_scanner": True,
            "pip_audit_scanner": True,
            "performance_baseline_persist": settings.performance_baseline_persist,
            "performance_baseline_gate": settings.performance_baseline_gate_enabled,
            "otel_export": settings.otel_export_enabled,
        },
    }


@router.post("/repository")
async def analyze_repository_intel(
    body: RepositoryIntelRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    """On-demand repository fingerprinting, stack detection, ownership, and license scan."""
    repo_path = (body.repo_path or "").strip()
    cleanup_run_id: uuid.UUID | None = None
    repo_name = body.repo_full_name or ""
    commit = ""

    if not repo_path:
        url = (body.clone_url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="Provide repo_path or clone_url")
        if settings.is_production and not url.startswith(("https://", "http://", "ssh://", "git@")):
            raise HTTPException(status_code=400, detail="Remote clone_url required in production")
        if url.startswith(("https://", "http://", "ssh://", "git@")):
            validate_remote_clone_url(url)
        cleanup_run_id = uuid.uuid4()
        git = GitService()
        repo_path = await git.clone_repo(url, cleanup_run_id, branch=body.branch or None)
        if not repo_name:
            repo_name = Path(url.rstrip("/\\").removesuffix(".git")).name or "repository"
    else:
        if settings.is_production:
            raise HTTPException(status_code=400, detail="repo_path is disabled in production; use clone_url")
        if not Path(repo_path).is_dir():
            raise HTTPException(status_code=400, detail=f"repo_path not found: {repo_path}")
        if not repo_name:
            repo_name = Path(repo_path).name

    pipeline_run_id: uuid.UUID | None = None
    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pipeline_run_id") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        repo_name = repo_name or run.repo_full_name
        commit = run.commit_id or commit

    try:
        if body.use_llm and settings.llm_enabled:
            client = AsyncAnthropic(api_key=settings.anthropic_api_key)
            agent = RepositoryIntelligenceAgent(
                pipeline_run_id,
                db if pipeline_run_id else None,
                client,
                repo_path=repo_path,
                repo=repo_name,
                commit=commit,
                changed_files=body.changed_files,
                diff_text=body.diff_text or "",
            )
            report = await agent.execute()
        else:
            report = analyze_repository(
                repo_path,
                repo=repo_name,
                commit=commit,
                changed_files=body.changed_files,
                diff_text=body.diff_text or "",
            )
            if pipeline_run_id:
                db.add(
                    PipelineArtifact(
                        pipeline_run_id=pipeline_run_id,
                        artifact_type="repository_intelligence",
                        content=report,
                    )
                )
                await db.commit()
    finally:
        if cleanup_run_id is not None:
            background_tasks.add_task(GitService().cleanup_repo, cleanup_run_id)

    if report.get("error"):
        raise HTTPException(status_code=400, detail=report["error"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": pipeline_run_id is not None,
        "report": report,
    }


@router.post("/tests")
async def analyze_test_intelligence(
    body: TestIntelRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    """On-demand test selection, flaky analysis, coverage regression, and mutation targets."""
    from app.utils.text_analysis import files_in_diff

    repo_path = (body.repo_path or "").strip()
    cleanup_run_id: uuid.UUID | None = None
    changed = body.changed_files or (files_in_diff(body.diff_text or "") if body.diff_text else [])

    if not repo_path:
        url = (body.clone_url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="Provide repo_path or clone_url")
        if settings.is_production and not url.startswith(("https://", "http://", "ssh://", "git@")):
            raise HTTPException(status_code=400, detail="Remote clone_url required in production")
        if url.startswith(("https://", "http://", "ssh://", "git@")):
            validate_remote_clone_url(url)
        cleanup_run_id = uuid.uuid4()
        git = GitService()
        repo_path = await git.clone_repo(url, cleanup_run_id, branch=body.branch or None)
    elif settings.is_production:
        raise HTTPException(status_code=400, detail="repo_path is disabled in production; use clone_url")
    elif not Path(repo_path).is_dir():
        raise HTTPException(status_code=400, detail=f"repo_path not found: {repo_path}")

    qa_current: dict[str, Any] | None = None
    historical: list[dict[str, Any]] = []
    pipeline_run_id: uuid.UUID | None = None
    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pipeline_run_id") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == run.id))
        ).scalars().all()
        arts = {a.artifact_type: a.content or {} for a in rows}
        qa_current = arts.get("qa_report")
        if not changed and isinstance(arts.get("metadata"), dict):
            changed = arts["metadata"].get("changed_files") or []

    try:
        if body.use_llm and settings.llm_enabled:
            client = AsyncAnthropic(api_key=settings.anthropic_api_key)
            agent = TestIntelligenceAgent(
                pipeline_run_id,
                db if pipeline_run_id else None,
                client,
                repo_path=repo_path,
                changed_files=changed,
                qa_current=qa_current,
                historical_qa=historical,
                run_live_coverage=body.run_live_coverage,
            )
            report = await agent.execute()
        else:
            report = build_test_intelligence_report(
                repo_path,
                changed_files=changed,
                qa_current=qa_current,
                historical_qa=historical,
                run_live_coverage=body.run_live_coverage,
            )
            if pipeline_run_id:
                db.add(
                    PipelineArtifact(
                        pipeline_run_id=pipeline_run_id,
                        artifact_type="test_intelligence",
                        content=report,
                    )
                )
                await db.commit()
    finally:
        if cleanup_run_id is not None:
            background_tasks.add_task(GitService().cleanup_repo, cleanup_run_id)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": pipeline_run_id is not None,
        "report": report,
    }


@router.post("/dast")
async def analyze_dast_intelligence(
    body: DastIntelRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    """Staging DAST scan — OWASP ZAP baseline when installed, heuristic probe otherwise."""
    pipeline_run_id: uuid.UUID | None = None
    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pipeline_run_id") from exc
        if await db.get(PipelineRun, pipeline_run_id) is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")

    report = build_dast_report(body.target_url)
    report["gates"] = evaluate_dast_gates(report)
    report["gate_verdict"] = report["gates"]["gate_verdict"]

    if pipeline_run_id:
        db.add(
            PipelineArtifact(
                pipeline_run_id=pipeline_run_id,
                artifact_type="dast_report",
                content=report,
            )
        )
        await db.commit()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": pipeline_run_id is not None,
        "report": report,
    }


@router.post("/code-review")
async def analyze_code_review_intelligence(
    body: CodeReviewIntelRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    """Multi-layer L0–L7 code review rollup with bug-prediction heuristics."""
    pipeline_run_id: uuid.UUID | None = None
    artifacts: dict[str, Any] = {}

    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pipeline_run_id") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == run.id))
        ).scalars().all()
        artifacts = {a.artifact_type: a.content or {} for a in rows}

    changed = body.changed_files
    if not changed and isinstance(artifacts.get("metadata"), dict):
        changed = artifacts["metadata"].get("changed_files") or []

    report = build_code_review_intelligence_report(
        code_analysis=body.code_analysis or artifacts.get("code_analysis"),
        security_scan=body.security_scan or artifacts.get("security_scan"),
        qa_report=body.qa_report or artifacts.get("qa_report"),
        service_graph=body.service_graph or artifacts.get("service_graph"),
        repository_intelligence=body.repository_intelligence or artifacts.get("repository_intelligence"),
        change_risk_report=body.change_risk_report or artifacts.get("change_risk_report"),
        stress_report=body.stress_report or artifacts.get("stress_report"),
        performance_intelligence=body.performance_intelligence or artifacts.get("performance_intelligence"),
        changed_files=changed,
    )

    if pipeline_run_id:
        db.add(
            PipelineArtifact(
                pipeline_run_id=pipeline_run_id,
                artifact_type="code_review_intelligence",
                content=report,
            )
        )
        await db.commit()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": pipeline_run_id is not None,
        "report": report,
    }


@router.post("/performance")
async def analyze_performance_intelligence(
    body: PerformanceIntelRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    """Baseline comparison and profile recommendations from a stress report."""
    stress = body.stress_report
    historical: list[dict[str, Any]] = []
    pipeline_run_id: uuid.UUID | None = None

    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pipeline_run_id") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == run.id))
        ).scalars().all()
        arts = {a.artifact_type: a.content or {} for a in rows}
        stress = stress or arts.get("stress_report")
        prior = (
            await db.execute(
                select(PipelineRun)
                .where(PipelineRun.repo_full_name == run.repo_full_name, PipelineRun.id != run.id)
                .order_by(desc(PipelineRun.created_at))
                .limit(15)
            )
        ).scalars().all()
        for prior_run in prior:
            art = (
                await db.execute(
                    select(PipelineArtifact).where(
                        PipelineArtifact.pipeline_run_id == prior_run.id,
                        PipelineArtifact.artifact_type == "stress_report",
                    )
                )
            ).scalar_one_or_none()
            if art and isinstance(art.content, dict) and not art.content.get("skipped"):
                historical.append(art.content)

    if not stress or not isinstance(stress, dict):
        raise HTTPException(status_code=400, detail="Provide stress_report or pipeline_run_id with stress artifact")

    profile = resolve_stress_profile(body.stress_profile or stress.get("stress_profile"))
    if body.use_llm and settings.llm_enabled:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        agent = PerformanceIntelligenceAgent(
            pipeline_run_id,
            db if pipeline_run_id else None,
            client,
            stress_report=stress,
            historical_stress=historical,
            profile=profile,
        )
        report = await agent.execute()
    else:
        report = build_performance_intelligence_report(stress, historical_stress=historical, profile=profile)
        if pipeline_run_id:
            db.add(
                PipelineArtifact(
                    pipeline_run_id=pipeline_run_id,
                    artifact_type="performance_intelligence",
                    content=report,
                )
            )
            await db.commit()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": pipeline_run_id is not None,
        "report": report,
    }


@router.post("/deployment")
async def analyze_deployment_intelligence(
    body: DeploymentIntelRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    """Environment registry, progressive strategy plan, and SLO rollback signals."""
    deployment_info = body.deployment_info
    progressive_delivery = body.progressive_delivery
    error_budget_report = body.error_budget_report
    stress_report = body.stress_report
    change_risk_report = body.change_risk_report
    rollback_intelligence: dict[str, Any] | None = None
    pipeline_run_id: uuid.UUID | None = None

    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pipeline_run_id") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == run.id))
        ).scalars().all()
        arts = {a.artifact_type: a.content or {} for a in rows}
        deployment_info = deployment_info or arts.get("deployment_info")
        progressive_delivery = progressive_delivery or arts.get("progressive_delivery")
        error_budget_report = error_budget_report or arts.get("error_budget_report")
        stress_report = stress_report or arts.get("stress_report")
        change_risk_report = change_risk_report or arts.get("change_risk_report")
        rollback_intelligence = arts.get("rollback_intelligence")

    if not deployment_info or not isinstance(deployment_info, dict):
        raise HTTPException(
            status_code=400,
            detail="Provide deployment_info or pipeline_run_id with deployment artifact",
        )

    if body.use_llm and settings.llm_enabled:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        agent = DeploymentIntelligenceAgent(
            pipeline_run_id,
            db if pipeline_run_id else None,
            client,
            deployment_info=deployment_info,
            progressive_delivery=progressive_delivery,
            error_budget_report=error_budget_report,
            stress_report=stress_report,
            change_risk_report=change_risk_report,
            rollback_intelligence=rollback_intelligence,
        )
        report = await agent.execute()
    else:
        report = build_deployment_intelligence_report(
            deployment_info=deployment_info,
            progressive_delivery=progressive_delivery,
            error_budget_report=error_budget_report,
            stress_report=stress_report,
            change_risk_report=change_risk_report,
            rollback_intelligence=rollback_intelligence,
        )
        if pipeline_run_id:
            db.add(
                PipelineArtifact(
                    pipeline_run_id=pipeline_run_id,
                    artifact_type="deployment_intelligence",
                    content=report,
                )
            )
            await db.commit()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": pipeline_run_id is not None,
        "report": report,
    }


@router.post("/observability")
async def analyze_observability_intelligence(
    body: ObservabilityIntelRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    """Deploy correlation, metric anomalies, log signals, and runtime service map."""
    deployment_info = body.deployment_info
    otel_trace_context = body.otel_trace_context
    synthetic_monitoring_report = body.synthetic_monitoring_report
    stress_report = body.stress_report
    error_budget_report = body.error_budget_report
    service_graph = body.service_graph
    monitoring_summary = body.monitoring_summary
    change_risk_report = body.change_risk_report
    log_excerpt = body.log_excerpt or ""
    historical_synthetic: list[dict[str, Any]] = []
    historical_stress: list[dict[str, Any]] = []
    pipeline_run_id: uuid.UUID | None = None

    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pipeline_run_id") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == run.id))
        ).scalars().all()
        arts = {a.artifact_type: a.content or {} for a in rows}
        deployment_info = deployment_info or arts.get("deployment_info")
        otel_trace_context = otel_trace_context or arts.get("otel_trace_context")
        synthetic_monitoring_report = synthetic_monitoring_report or arts.get("synthetic_monitoring_report")
        stress_report = stress_report or arts.get("stress_report")
        error_budget_report = error_budget_report or arts.get("error_budget_report")
        service_graph = service_graph or arts.get("service_graph")
        monitoring_summary = monitoring_summary or arts.get("monitoring_summary")
        change_risk_report = change_risk_report or arts.get("change_risk_report")

        prior = (
            await db.execute(
                select(PipelineRun)
                .where(PipelineRun.repo_full_name == run.repo_full_name, PipelineRun.id != run.id)
                .order_by(desc(PipelineRun.created_at))
                .limit(15)
            )
        ).scalars().all()
        for prior_run in prior:
            prior_rows = (
                await db.execute(
                    select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == prior_run.id)
                )
            ).scalars().all()
            prior_arts = {a.artifact_type: a.content or {} for a in prior_rows}
            syn = prior_arts.get("synthetic_monitoring_report")
            if isinstance(syn, dict) and syn.get("journeys"):
                historical_synthetic.append(syn)
            prior_stress = prior_arts.get("stress_report")
            if isinstance(prior_stress, dict) and not prior_stress.get("skipped"):
                historical_stress.append(prior_stress)

    if not deployment_info and not otel_trace_context and not synthetic_monitoring_report:
        raise HTTPException(
            status_code=400,
            detail="Provide pipeline_run_id or inline observability artifacts",
        )

    if body.use_llm and settings.llm_enabled:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        agent = ObservabilityIntelligenceAgent(
            pipeline_run_id,
            db if pipeline_run_id else None,
            client,
            deployment_info=deployment_info,
            otel_trace_context=otel_trace_context,
            synthetic_monitoring_report=synthetic_monitoring_report,
            stress_report=stress_report,
            error_budget_report=error_budget_report,
            service_graph=service_graph,
            monitoring_summary=monitoring_summary,
            change_risk_report=change_risk_report,
            historical_synthetic=historical_synthetic,
            historical_stress=historical_stress,
            log_excerpt=log_excerpt,
        )
        report = await agent.execute()
    else:
        report = build_observability_intelligence_report(
            deployment_info=deployment_info,
            otel_trace_context=otel_trace_context,
            synthetic_monitoring_report=synthetic_monitoring_report,
            stress_report=stress_report,
            error_budget_report=error_budget_report,
            service_graph=service_graph,
            monitoring_summary=monitoring_summary,
            change_risk_report=change_risk_report,
            historical_synthetic=historical_synthetic,
            historical_stress=historical_stress,
            log_excerpt=log_excerpt,
        )
        if pipeline_run_id:
            db.add(
                PipelineArtifact(
                    pipeline_run_id=pipeline_run_id,
                    artifact_type="observability_intelligence",
                    content=report,
                )
            )
            await db.commit()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": pipeline_run_id is not None,
        "report": report,
    }


@router.get("/multimodal/catalog")
async def multimodal_intelligence_catalog(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    report = build_multimodal_catalog_report()
    return {"generated_at": datetime.now(timezone.utc).isoformat(), **report}


@router.post("/multimodal")
async def analyze_multimodal_intelligence(
    body: MultimodalIntelRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    pipeline_run_id: uuid.UUID | None = None
    artifacts: dict[str, dict[str, Any]] = {}
    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="pipeline_run_id must be a UUID") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == pipeline_run_id))
        ).scalars().all()
        artifacts = {row.artifact_type: row.content or {} for row in rows}

    route_hint = None
    if body.route_text or body.preferred_agent:
        route_hint = build_route_report(
            artifacts=[],
            text_input=body.route_text or "",
            preferred_agent=body.preferred_agent,
        )

    report = build_multimodal_intelligence_report(artifacts=artifacts, route_hint=route_hint)
    if body.persist and pipeline_run_id is not None:
        from app.services.multimodal_enrichment import persist_multimodal_intelligence

        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        report = await persist_multimodal_intelligence(db, run, artifacts=artifacts, route_hint=route_hint)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": bool(body.persist and pipeline_run_id),
        "report": report,
    }


@router.get("/cloud/targets")
async def cloud_targets(
    repo: str | None = None,
    repo_path: str | None = None,
    environment: str | None = None,
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    catalog = build_cloud_target_catalog()
    resolved = resolve_cloud_target(
        repo=repo or "",
        repo_path=repo_path,
        environment=environment or settings.deploy_environment,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **catalog,
        "resolved": resolved,
    }


@router.post("/cloud")
async def analyze_cloud_intelligence(
    body: CloudIntelRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    pipeline_run_id: uuid.UUID | None = None
    run: PipelineRun | None = None
    artifacts: dict[str, dict[str, Any]] = {}
    repo_path = (body.repo_path or "").strip()
    repo = body.repo or ""

    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="pipeline_run_id must be a UUID") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        repo = run.repo_full_name
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == pipeline_run_id))
        ).scalars().all()
        artifacts = {row.artifact_type: row.content or {} for row in rows}

    if repo_path and not artifacts.get("kubernetes_manifest_scan"):
        k8s = scan_kubernetes_manifests(repo_path)
        artifacts["kubernetes_manifest_scan"] = k8s

    report = build_cloud_intelligence_report(
        repo=repo,
        repo_path=repo_path or None,
        environment=body.environment or settings.deploy_environment,
        deploy_mode=body.deploy_mode,
        kubernetes_manifest_scan=artifacts.get("kubernetes_manifest_scan"),
        iac_security_scan=artifacts.get("iac_security_scan"),
        container_security_scan=artifacts.get("container_security_scan"),
        dockerfile_analysis=artifacts.get("dockerfile_analysis"),
        service_graph=artifacts.get("service_graph"),
        deployment_info=artifacts.get("deployment_info"),
    )
    if body.persist and run is not None:
        report = await persist_cloud_intelligence(
            db,
            run,
            artifacts=artifacts,
            repo_path=repo_path or None,
            deploy_mode=body.deploy_mode,
            skip_if_present=False,
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": bool(body.persist and run is not None),
        "report": report,
    }


@router.get("/fleet")
async def intelligence_fleet(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    runs = (
        await db.execute(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(50))
    ).scalars().all()
    arts_by_run = await _artifacts_for_runs(db, [run.id for run in runs])
    fleet = build_fleet_view(runs, arts_by_run)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **fleet,
    }


@router.get("/catalog/idp")
async def catalog_idp_portal(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    portal = build_idp_portal_catalog()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **portal,
    }


@router.get("/catalog/services")
async def catalog_services(
    repo: str | None = None,
    repo_path: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    if repo:
        catalog = build_service_catalog(repo=repo, repo_path=repo_path)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **catalog,
        }
    runs = (
        await db.execute(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(50))
    ).scalars().all()
    arts_by_run = await _artifacts_for_runs(db, [run.id for run in runs])
    repo_catalogs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for run in runs:
        repo_name = run.repo_full_name
        if not repo_name or repo_name in seen:
            continue
        seen.add(repo_name)
        arts = arts_by_run.get(str(run.id)) or {}
        if arts.get("service_catalog"):
            repo_catalogs.append(arts["service_catalog"])
        else:
            repo_catalogs.append(
                build_service_catalog(
                    repo=repo_name,
                    service_graph=arts.get("service_graph"),
                    repository_intelligence=arts.get("repository_intelligence"),
                    cloud_intelligence=arts.get("cloud_intelligence"),
                )
            )
    fleet_catalog = merge_fleet_catalogs(repo_catalogs)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **fleet_catalog,
    }


@router.post("/catalog")
async def analyze_catalog_intelligence(
    body: CatalogIntelRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    pipeline_run_id: uuid.UUID | None = None
    run: PipelineRun | None = None
    artifacts: dict[str, dict[str, Any]] = {}
    repo_path = (body.repo_path or "").strip()
    repo = body.repo or ""
    fleet_runs: list[PipelineRun] | None = None
    fleet_artifacts: dict[str, dict[str, dict[str, Any]]] | None = None

    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="pipeline_run_id must be a UUID") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        repo = run.repo_full_name
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == pipeline_run_id))
        ).scalars().all()
        artifacts = {row.artifact_type: row.content or {} for row in rows}

    if body.include_fleet:
        fleet_runs = (
            await db.execute(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(50))
        ).scalars().all()
        fleet_artifacts = await _artifacts_for_runs(db, [r.id for r in fleet_runs])

    report = build_service_catalog_intelligence_report(
        repo=repo,
        repo_path=repo_path or None,
        artifacts=artifacts,
        fleet_runs=fleet_runs if body.include_fleet else None,
        fleet_artifacts=fleet_artifacts if body.include_fleet else None,
    )
    if body.persist and run is not None:
        report = await persist_service_catalog_intelligence(
            db,
            run,
            artifacts=artifacts,
            repo_path=repo_path or None,
            fleet_runs=fleet_runs if body.include_fleet else None,
            fleet_artifacts=fleet_artifacts if body.include_fleet else None,
            skip_if_present=False,
        )
        if not artifacts.get("service_catalog"):
            await persist_service_catalog(
                db,
                run,
                artifacts=artifacts,
                repo_path=repo_path or None,
                skip_if_present=False,
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": bool(body.persist and run is not None),
        "report": report,
    }


@router.get("/audit-explorer")
async def intelligence_audit_explorer(
    repo: str | None = None,
    action: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    runs = (
        await db.execute(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(30))
    ).scalars().all()
    audit_by_run: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        audit_by_run[str(run.id)] = await list_audit_events(db, run.id, limit=limit)
    report = explore_audit_events(
        runs,
        audit_by_run,
        repo_filter=repo,
        action_filter=action,
        limit=limit,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **report,
    }


@router.get("/agents")
async def intelligence_agents(
    mesh: bool = False,
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    if mesh:
        registry = build_agent_mesh_registry()
    else:
        registry = build_agent_registry()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **registry,
    }


@router.get("/release/policy")
async def release_policy(
    repo: str | None = None,
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **resolve_release_policy(repo or ""),
    }


@router.get("/release/dora")
async def release_dora_metrics(
    repo: str | None = None,
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    query = select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(limit)
    if repo:
        query = query.where(PipelineRun.repo_full_name == repo)
    runs = (await db.execute(query)).scalars().all()
    dora = compute_dora_metrics(runs)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": repo,
        "dora": dora,
    }


@router.get("/release")
async def release_fleet_summary(
    repo: str | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    query = select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(limit)
    if repo:
        query = query.where(PipelineRun.repo_full_name == repo)
    runs = (await db.execute(query)).scalars().all()
    arts_by_run = await _artifacts_for_runs(db, [run.id for run in runs])
    summaries: list[dict[str, Any]] = []
    for run in runs:
        arts = arts_by_run.get(str(run.id)) or {}
        intel = arts.get("release_intelligence") or {}
        passport = intel.get("release_passport") or arts.get("release_passport") or {}
        prediction = intel.get("release_prediction") or {}
        summaries.append(
            {
                "run_id": str(run.id),
                "repository": run.repo_full_name,
                "status": run.status,
                "passport_passed": passport.get("all_checks_passed"),
                "failure_probability": prediction.get("failure_probability_percent"),
                "gate_verdict": intel.get("gate_verdict"),
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": resolve_release_policy(repo or ""),
        "runs": summaries,
    }


@router.post("/release")
async def analyze_release_intelligence(
    body: ReleaseIntelRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    run: PipelineRun | None = None
    artifacts: dict[str, dict[str, Any]] = {}
    fleet_runs: list[PipelineRun] | None = None

    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="pipeline_run_id must be a UUID") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == pipeline_run_id))
        ).scalars().all()
        artifacts = {row.artifact_type: row.content or {} for row in rows}

    if body.include_fleet:
        query = select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(30)
        if run is not None:
            query = query.where(PipelineRun.repo_full_name == run.repo_full_name)
        fleet_runs = list((await db.execute(query)).scalars().all())

    if body.persist and run is not None:
        report = await persist_release_intelligence(
            db,
            run,
            artifacts=artifacts,
            deploy_mode=body.deploy_mode,
            environment=body.environment,
            fleet_runs=fleet_runs,
            skip_if_present=False,
        )
    else:
        report = build_release_intelligence_report(
            run_id=str(run.id) if run else "",
            repo=run.repo_full_name if run else "",
            branch=run.branch if run else "",
            commit=run.commit_id if run else "",
            environment=body.environment,
            deploy_mode=body.deploy_mode,
            artifacts=artifacts,
            fleet_runs=fleet_runs,
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": bool(body.persist and run is not None),
        "report": report,
    }


@router.get("/finops/budgets")
async def finops_budgets(
    repo: str | None = None,
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **resolve_finops_budgets(repo or ""),
    }


@router.get("/finops")
async def finops_fleet_summary(
    repo: str | None = None,
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    query = select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(limit)
    if repo:
        query = query.where(PipelineRun.repo_full_name == repo)
    runs = (await db.execute(query)).scalars().all()
    arts_by_run = await _artifacts_for_runs(db, [run.id for run in runs])
    costs: list[dict[str, Any]] = []
    for run in runs:
        arts = arts_by_run.get(str(run.id)) or {}
        finops = arts.get("finops_intelligence") or {}
        cost = finops.get("cost_report") or arts.get("cost_report") or {}
        if cost:
            costs.append({**cost, "repository": run.repo_full_name, "run_id": str(run.id)})
    fleet = build_fleet_cost_rollup(costs)
    budgets = resolve_finops_budgets(repo or "")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "budgets": budgets,
        "fleet": fleet,
        "runs": costs[:limit],
    }


@router.post("/finops")
async def analyze_finops_intelligence(
    body: FinOpsIntelRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    run: PipelineRun | None = None
    artifacts: dict[str, dict[str, Any]] = {}
    fleet_costs: list[dict[str, Any]] | None = None

    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="pipeline_run_id must be a UUID") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == pipeline_run_id))
        ).scalars().all()
        artifacts = {row.artifact_type: row.content or {} for row in rows}

    if body.include_fleet:
        recent = (
            await db.execute(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(30))
        ).scalars().all()
        arts_by_run = await _artifacts_for_runs(db, [r.id for r in recent])
        fleet_costs = []
        for r in recent:
            arts = arts_by_run.get(str(r.id)) or {}
            cost = (arts.get("finops_intelligence") or {}).get("cost_report") or arts.get("cost_report")
            if cost:
                fleet_costs.append({**cost, "repository": r.repo_full_name})

    if body.persist and run is not None:
        report = await persist_finops_intelligence(
            db, run, artifacts=artifacts, fleet_costs=fleet_costs, skip_if_present=False
        )
    else:
        report = build_finops_intelligence_report(
            run_id=str(run.id) if run else "",
            repo=run.repo_full_name if run else "",
            artifacts=artifacts,
            fleet_costs=fleet_costs,
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": bool(body.persist and run is not None),
        "report": report,
    }


@router.get("/governance/policy")
async def governance_policy(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **build_governance_policy_catalog(),
    }


@router.get("/governance/escalations")
async def governance_escalations(
    run_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    artifacts: dict[str, dict[str, Any]] = {}
    if run_id:
        try:
            rid = uuid.UUID(run_id)
            rows = (
                await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == rid))
            ).scalars().all()
            artifacts = {a.artifact_type: a.content or {} for a in rows}
        except ValueError:
            pass
    queue = build_escalation_queue(artifacts)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "escalations": queue,
        "count": len(queue),
        "human_review_required": bool(queue),
    }


@router.post("/governance")
async def analyze_governance_intelligence(
    body: GovernanceIntelRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    run: PipelineRun | None = None
    artifacts: dict[str, dict[str, Any]] = {}
    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="pipeline_run_id must be a UUID") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == pipeline_run_id))
        ).scalars().all()
        artifacts = {row.artifact_type: row.content or {} for row in rows}

    if body.persist and run is not None:
        report = await persist_ai_governance_intelligence(
            db, run, artifacts=artifacts, skip_if_present=False
        )
    else:
        report = build_ai_governance_intelligence_report(
            artifacts=artifacts,
            run_id=str(run.id) if run else "",
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": bool(body.persist and run is not None),
        "report": report,
    }


@router.get("/mesh/topology")
async def mesh_topology(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **build_mesh_topology(),
    }


@router.get("/mesh/agents")
async def mesh_agents(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    registry = build_agent_mesh_registry()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **registry,
    }


@router.post("/mesh/route")
async def mesh_route(body: MeshRouteRequest, _: dict = Depends(optional_auth)) -> dict[str, Any]:
    if body.event_id:
        result = route_mesh_event(body.event_id)
    else:
        result = route_mesh_intent(body.intent, preferred_agent=body.preferred_agent)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }


@router.post("/mesh")
async def analyze_mesh_intelligence(
    body: MeshIntelRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    run: PipelineRun | None = None
    artifacts: dict[str, dict[str, Any]] = {}
    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="pipeline_run_id must be a UUID") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == pipeline_run_id))
        ).scalars().all()
        artifacts = {row.artifact_type: row.content or {} for row in rows}

    if body.persist and run is not None:
        await persist_agent_mesh_snapshot(db, run, skip_if_present=False, existing=artifacts)
        report = await persist_agent_mesh_intelligence(
            db, run, artifacts=artifacts, intent=body.intent, skip_if_present=False
        )
    else:
        report = build_agent_mesh_intelligence_report(
            artifacts=artifacts,
            intent=body.intent,
            run_status=str(run.status) if run else "",
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": bool(body.persist and run is not None),
        "report": report,
    }


@router.get("/rag")
async def intelligence_rag(
    q: str = "",
    run_id: str | None = None,
    repo_path: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    artifacts: dict[str, dict[str, Any]] = {}
    scope_id = ""
    run: PipelineRun | None = None
    if run_id:
        try:
            from uuid import UUID

            rid = UUID(run_id)
            run = await db.get(PipelineRun, rid)
            if run:
                scope_id = str(run.id)
                rows = (
                    await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == rid))
                ).scalars().all()
                artifacts = {a.artifact_type: a.content or {} for a in rows}
        except ValueError:
            pass
    else:
        run = (
            await db.execute(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(1))
        ).scalar_one_or_none()
        if run:
            scope_id = str(run.id)
            rows = (
                await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == run.id))
            ).scalars().all()
            artifacts = {a.artifact_type: a.content or {} for a in rows}

    memory_store = build_memory_store()
    retriever = build_retriever()
    if repo_path and Path(repo_path).is_dir():
        index_repository(retriever, repo_path)

    report = build_rag_intelligence_report(
        query=q,
        artifacts=artifacts,
        memory_store=memory_store,
        retriever=retriever,
        scope_id=scope_id,
    )
    return {"generated_at": datetime.now(timezone.utc).isoformat(), **report}


@router.post("/rag")
async def analyze_rag_intelligence(
    body: RagIntelRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    run: PipelineRun | None = None
    artifacts: dict[str, dict[str, Any]] = {}
    repo_path = (body.repo_path or "").strip()

    if body.pipeline_run_id:
        try:
            pipeline_run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="pipeline_run_id must be a UUID") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == pipeline_run_id))
        ).scalars().all()
        artifacts = {row.artifact_type: row.content or {} for row in rows}

    memory_store = build_memory_store()
    retriever = build_retriever()
    if body.index_repo and repo_path and Path(repo_path).is_dir():
        index_repository(retriever, repo_path)

    if body.persist and run is not None:
        report = await persist_rag_intelligence(
            db,
            run,
            artifacts=artifacts,
            memory_store=memory_store,
            retriever=retriever,
            repo_path=repo_path or None,
            query=body.query,
            skip_if_present=False,
        )
    else:
        report = build_rag_intelligence_report(
            query=body.query,
            artifacts=artifacts,
            memory_store=memory_store,
            retriever=retriever,
            scope_id=str(run.id) if run else "",
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": bool(body.persist and run is not None),
        "report": report,
    }


@router.get("/memory")
async def intelligence_memory(
    agent: str | None = None,
    scope_id: str | None = None,
    limit: int = 5,
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    store = build_memory_store()
    if agent and scope_id:
        context = store.get_context(agent, scope_id, limit=limit)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "scope_id": scope_id,
            "context": context,
            "turns": len(context),
        }
    scopes = store.list_scopes(agent_name=agent, limit=limit)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "memory_enabled": settings.agent_memory_enabled,
        "scopes": scopes,
        "count": len(scopes),
    }
