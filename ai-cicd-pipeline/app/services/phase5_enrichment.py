"""Phase 5 AI platform enrichment — governance, routing, eval, RAG."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.agent_eval import evaluate_agents
from app.utils.agent_permissions import build_permissions_report
from app.utils.agent_registry import build_agent_registry
from app.utils.ai_cost_optimizer import optimize_ai_cost
from app.utils.decision_ledger import build_decision_ledger
from app.services.hybrid_retriever import Retriever
from app.services.memory_store import MemoryStore
from app.services.finops_enrichment import persist_finops_intelligence
from app.services.governance_enrichment import persist_ai_governance_intelligence
from app.services.mesh_enrichment import persist_agent_mesh_intelligence, persist_agent_mesh_snapshot
from app.services.rag_enrichment import persist_rag_intelligence
from app.utils.model_router import build_model_routing_plan
from app.utils.prompt_registry import build_prompt_registry_snapshot
from app.utils.sandbox_policy import build_sandbox_policy_report


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def run_phase5_enrichment(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    skip_if_present: bool = False,
    memory_store: MemoryStore | None = None,
    retriever: Retriever | None = None,
    repo_path: str | None = None,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("agent_registry_snapshot"):
        return {
            "agent_registry_snapshot": artifacts.get("agent_registry_snapshot"),
            "decision_ledger": artifacts.get("decision_ledger"),
        }

    registry = build_agent_registry()
    await _save(db, run.id, "agent_registry_snapshot", registry)

    agent_names = [a["name"] for a in registry.get("agents", []) if a.get("kind") == "pipeline"]
    permissions = build_permissions_report(agents_used=agent_names[:8])
    await _save(db, run.id, "agent_permissions_report", permissions)

    sandbox = build_sandbox_policy_report(fix_loop=artifacts.get("fix_loop_report"))
    await _save(db, run.id, "sandbox_policy_report", sandbox)

    routing = build_model_routing_plan(artifacts)
    await _save(db, run.id, "model_routing_plan", routing)

    prompts = build_prompt_registry_snapshot(agents=agent_names[:8])
    await _save(db, run.id, "prompt_registry_snapshot", prompts)

    agent_eval = evaluate_agents(artifacts, min_score=settings.agent_eval_min_score)
    await _save(db, run.id, "agent_eval_report", agent_eval)
    artifacts = {**artifacts, "agent_eval_report": agent_eval}

    cost_opt = optimize_ai_cost(
        cost_report=artifacts.get("cost_report"),
        model_plan=routing,
        artifacts=artifacts,
    )
    await _save(db, run.id, "ai_cost_optimization", cost_opt)

    ledger = build_decision_ledger(run_id=str(run.id), artifacts=artifacts)
    await _save(db, run.id, "decision_ledger", ledger)

    rag_intel = await persist_rag_intelligence(
        db,
        run,
        artifacts=artifacts,
        memory_store=memory_store,
        retriever=retriever,
        repo_path=repo_path,
        skip_if_present=skip_if_present,
    )
    rag = rag_intel.get("rag") or {}
    artifacts = {**artifacts, "rag_intelligence": rag_intel, "devops_rag_context": rag}

    mesh_snapshot = await persist_agent_mesh_snapshot(
        db, run, skip_if_present=skip_if_present, existing=artifacts
    )
    mesh_intel = await persist_agent_mesh_intelligence(
        db, run, artifacts=artifacts, skip_if_present=skip_if_present
    )
    artifacts = {
        **artifacts,
        "agent_mesh_snapshot": mesh_snapshot,
        "agent_mesh_intelligence": mesh_intel,
        "model_routing_plan": routing,
        "prompt_registry_snapshot": prompts,
        "ai_cost_optimization": cost_opt,
        "decision_ledger": ledger,
    }
    governance_intel = await persist_ai_governance_intelligence(
        db,
        run,
        artifacts=artifacts,
        agent_names=agent_names,
        skip_if_present=skip_if_present,
    )
    artifacts = {**artifacts, "ai_governance_intelligence": governance_intel}
    finops_intel = await persist_finops_intelligence(
        db,
        run,
        artifacts=artifacts,
        skip_if_present=skip_if_present,
    )

    await db.commit()
    return {
        "agent_registry_snapshot": registry,
        "agent_permissions_report": permissions,
        "sandbox_policy_report": sandbox,
        "model_routing_plan": routing,
        "prompt_registry_snapshot": prompts,
        "agent_eval_report": agent_eval,
        "ai_cost_optimization": cost_opt,
        "decision_ledger": ledger,
        "devops_rag_context": rag,
        "rag_intelligence": rag_intel,
        "agent_mesh_snapshot": mesh_snapshot,
        "agent_mesh_intelligence": mesh_intel,
        "ai_governance_intelligence": governance_intel,
        "finops_intelligence": finops_intel,
    }
