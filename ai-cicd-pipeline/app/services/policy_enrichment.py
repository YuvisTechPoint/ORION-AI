"""Persist policy intelligence after policy gate evaluation."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.artifact_summaries import summarize_artifact
from app.utils.policy_intelligence import build_policy_intelligence_report
from app.utils.signed_builds import signed_build_verify_options, verify_signed_build


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


def _org_from_repo(repo_full_name: str) -> str:
    return repo_full_name.split("/", 1)[0] if "/" in repo_full_name else repo_full_name


async def persist_policy_intelligence(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    policy_evaluation: dict[str, Any] | None = None,
    skip_if_present: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("policy_intelligence"):
        return artifacts["policy_intelligence"]

    signed = artifacts.get("signed_build_report") or verify_signed_build(
        commit=run.commit_id,
        repo=run.repo_full_name,
        deployment_info=artifacts.get("deployment_info"),
        **signed_build_verify_options(),
    )

    report = build_policy_intelligence_report(
        org=_org_from_repo(run.repo_full_name),
        repo=run.repo_full_name,
        environment=settings.deploy_environment,
        artifacts=artifacts,
        policy_evaluation=policy_evaluation,
        unsigned_image=not signed.get("verified", True),
    )
    report["summary"] = summarize_artifact("policy_intelligence", report)
    await _save(db, run.id, "policy_intelligence", report)
    await db.commit()
    return report
