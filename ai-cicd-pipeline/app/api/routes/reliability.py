"""Reliability API — chaos experiments, synthetic checks, and intelligence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import optional_auth
from app.database import get_db
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.reliability_enrichment import persist_reliability_intelligence
from app.services.slo import compute_pipeline_slo
from app.utils.chaos_engineering import run_chaos_experiment, run_chaos_suite
from app.utils.reliability_intelligence import build_reliability_intelligence_report
from app.utils.reliability_registry import list_chaos_experiments, resolve_reliability_policy
from app.utils.synthetic_monitoring import run_synthetic_checks

router = APIRouter(prefix="/reliability", tags=["Reliability"])


class ReliabilityAnalyzeRequest(BaseModel):
    pipeline_run_id: str | None = None
    persist: bool = Field(default=True)


@router.get("/policy")
async def reliability_policy(
    repo: str = "",
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **resolve_reliability_policy(repo),
    }


@router.get("/experiments")
async def reliability_experiments(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiments": list_chaos_experiments(),
    }


@router.get("/chaos")
async def reliability_chaos_suite(
    repo: str = "",
    simulated: bool = True,
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    policy = resolve_reliability_policy(repo)
    use_simulated = simulated if simulated is not None else policy.get("simulated", True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chaos_report": run_chaos_suite(
            simulated=use_simulated,
            experiment_names=policy.get("experiment_names"),
        ),
    }


@router.get("/status")
async def reliability_status(
    repo: str = "",
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    policy = resolve_reliability_policy(repo)
    chaos = run_chaos_suite(
        simulated=policy.get("simulated", True),
        experiment_names=policy.get("experiment_names"),
    )
    synthetic = await run_synthetic_checks(simulated=not policy.get("live_chaos_enabled", False))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": policy,
        "chaos_report": chaos,
        "synthetic_monitoring": synthetic,
    }


@router.post("/analyze")
async def analyze_reliability(
    body: ReliabilityAnalyzeRequest,
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
        report = await persist_reliability_intelligence(db, run, artifacts=artifacts, skip_if_present=False)
    else:
        slo = None
        if run:
            recent = list(
                (
                    await db.execute(
                        select(PipelineRun)
                        .where(PipelineRun.repo_full_name == run.repo_full_name)
                        .order_by(desc(PipelineRun.created_at))
                        .limit(20)
                    )
                ).scalars().all()
            )
            slo = compute_pipeline_slo(recent or [run])
        report = await build_reliability_intelligence_report(
            run_id=str(run.id) if run else "",
            repo=run.repo_full_name if run else "",
            artifacts=artifacts,
            slo=slo,
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": bool(body.persist and run is not None),
        "report": report,
    }


@router.post("/chaos/{experiment_name}")
async def run_single_chaos_experiment(
    experiment_name: str,
    simulated: bool = True,
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "result": run_chaos_experiment(experiment=experiment_name, simulated=simulated),
    }
