"""Persist performance intelligence after stress testing."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.performance_baseline_store import get_baseline, upsert_baseline
from app.utils.artifact_summaries import summarize_artifact
from app.utils.performance_intelligence import build_performance_intelligence_report, resolve_stress_profile


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def persist_performance_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    stress_report: dict[str, Any],
    skip_if_present: bool = False,
    existing: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if skip_if_present and (existing or {}).get("performance_intelligence"):
        return existing["performance_intelligence"]  # type: ignore[index]

    prior = (
        await db.execute(
            select(PipelineRun)
            .where(PipelineRun.repo_full_name == run.repo_full_name, PipelineRun.id != run.id)
            .order_by(desc(PipelineRun.created_at))
            .limit(15)
        )
    ).scalars().all()
    historical: list[dict[str, Any]] = []
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

    profile = resolve_stress_profile(stress_report.get("stress_profile"))
    stored = None
    if settings.performance_baseline_persist:
        stored = await get_baseline(
            db,
            repo_full_name=run.repo_full_name,
            profile=profile.get("name", "standard"),
            environment=settings.deploy_environment,
        )

    report = build_performance_intelligence_report(
        stress_report,
        historical_stress=historical,
        stored_baseline=stored,
        profile=profile,
    )
    report["summary"] = summarize_artifact("performance_intelligence", report)
    await _save(db, run.id, "performance_intelligence", report)

    if settings.performance_baseline_persist and not stress_report.get("skipped"):
        baseline_update = await upsert_baseline(
            db,
            repo_full_name=run.repo_full_name,
            stress_report=stress_report,
            profile=profile.get("name", "standard"),
            environment=settings.deploy_environment,
            run_id=run.id,
        )
        report["baseline_persist"] = baseline_update

    await db.commit()
    return report
