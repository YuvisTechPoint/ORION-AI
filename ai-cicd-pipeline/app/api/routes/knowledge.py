"""Knowledge graph API — unified repo/service/artifact graph and queries."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import optional_auth
from app.database import get_db
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.knowledge_graph_enrichment import persist_knowledge_graph_intelligence
from app.utils.knowledge_graph import build_knowledge_graph, query_knowledge_graph
from app.utils.knowledge_graph_intelligence import build_knowledge_graph_intelligence_report
from app.utils.knowledge_graph_registry import resolve_knowledge_graph_policy

router = APIRouter(prefix="/knowledge", tags=["Knowledge Graph"])


class KnowledgeAnalyzeRequest(BaseModel):
    pipeline_run_id: str | None = None
    query: str = ""
    persist: bool = Field(default=True)


@router.get("/policy")
async def knowledge_policy(
    repo: str = "",
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **resolve_knowledge_graph_policy(repo),
    }


@router.get("/graph")
async def knowledge_graph_query(
    q: str = Query(default="", description="Natural-language graph query"),
    run_id: str = "",
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    artifacts: dict[str, dict[str, Any]] = {}
    run: PipelineRun | None = None
    if run_id:
        try:
            pipeline_run_id = uuid.UUID(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="run_id must be a UUID") from exc
        run = await db.get(PipelineRun, pipeline_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == pipeline_run_id))
        ).scalars().all()
        artifacts = {row.artifact_type: row.content or {} for row in rows}

    graph = build_knowledge_graph(
        run_id=str(run.id) if run else "",
        repo=run.repo_full_name if run else "",
        commit=run.commit_id if run else "",
        branch=run.branch if run else "",
        artifacts=artifacts,
    )
    result = query_knowledge_graph(graph, q) if q else {"query": "", "matches": [], "paths": [], "summary": "Graph only."}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "graph": graph,
        "query": result,
    }


@router.get("/status")
async def knowledge_status(
    repo: str = "",
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    report = build_knowledge_graph_intelligence_report(repo=repo)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report": report,
    }


@router.post("/analyze")
async def analyze_knowledge_graph(
    body: KnowledgeAnalyzeRequest,
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
        report = await persist_knowledge_graph_intelligence(db, run, artifacts=artifacts, skip_if_present=False)
        if body.query:
            from app.utils.knowledge_graph import query_knowledge_graph

            report["query_result"] = query_knowledge_graph(report.get("graph") or {}, body.query)
    else:
        report = build_knowledge_graph_intelligence_report(
            run_id=str(run.id) if run else "",
            repo=run.repo_full_name if run else "",
            commit=run.commit_id if run else "",
            branch=run.branch if run else "",
            artifacts=artifacts,
            query=body.query,
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": bool(body.persist and run is not None),
        "report": report,
    }
