"""Persist enterprise approval state on pipeline runs."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.approval_workflow import resolve_approval_workflow
from app.utils.approval_intelligence import build_approval_intelligence_report
from app.utils.artifact_summaries import summarize_artifact
from app.utils.enterprise_approval import (
    build_simulated_signoffs,
    initialize_enterprise_approval,
    record_signoff,
)


def _org_from_repo(repo_full_name: str) -> str:
    return repo_full_name.split("/", 1)[0] if "/" in repo_full_name else repo_full_name


def _committer_from_artifacts(artifacts: dict[str, dict[str, Any]], run: PipelineRun) -> str:
    meta = artifacts.get("metadata") or {}
    return str(meta.get("pusher") or meta.get("author") or run.branch or "unknown")


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def init_enterprise_approval(
    db: AsyncSession,
    run: PipelineRun,
    *,
    automated_approval: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    org = _org_from_repo(run.repo_full_name)
    change_risk = artifacts.get("change_risk_report") or {}
    workflow = resolve_approval_workflow(
        org=org,
        repo=run.repo_full_name,
        environment=settings.deploy_environment,
        change_risk_score=change_risk.get("final_risk"),
    )
    committer = _committer_from_artifacts(artifacts, run)
    simulated = build_simulated_signoffs(workflow, committer=committer)
    enterprise = initialize_enterprise_approval(
        run_id=str(run.id),
        repo=run.repo_full_name,
        commit=run.commit_id,
        committer=committer,
        automated_approval=automated_approval,
        workflow=workflow,
        simulated_signoffs=simulated,
    )
    intel = build_approval_intelligence_report(
        org=org,
        repo=run.repo_full_name,
        environment=settings.deploy_environment,
        commit=run.commit_id,
        committer=committer,
        automated_approval=automated_approval,
        enterprise_approval=enterprise,
        change_risk_score=change_risk.get("final_risk"),
    )
    intel["summary"] = summarize_artifact("approval_intelligence", intel)
    await _save(db, run.id, "enterprise_approval", enterprise)
    await _save(db, run.id, "approval_intelligence", intel)
    await db.commit()
    return enterprise


def enterprise_approval_ready(record: dict[str, Any]) -> bool:
    return bool(record.get("ready_for_deploy"))


async def add_enterprise_signoff(
    db: AsyncSession,
    run: PipelineRun,
    *,
    approver: str,
    role: str,
    comment: str = "",
    token: str | None = None,
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    record = dict(artifacts.get("enterprise_approval") or {})
    if not record:
        raise LookupError("Enterprise approval record not initialized for this run")

    updated = record_signoff(record, approver=approver, role=role, comment=comment, token=token)
    automated = artifacts.get("approval") or {}
    org = _org_from_repo(run.repo_full_name)
    change_risk = artifacts.get("change_risk_report") or {}
    intel = build_approval_intelligence_report(
        org=org,
        repo=run.repo_full_name,
        environment=settings.deploy_environment,
        commit=run.commit_id,
        committer=updated.get("committer") or _committer_from_artifacts(artifacts, run),
        automated_approval=automated,
        enterprise_approval=updated,
        change_risk_score=change_risk.get("final_risk"),
    )
    intel["summary"] = summarize_artifact("approval_intelligence", intel)
    await _save(db, run.id, "enterprise_approval", updated)
    await _save(db, run.id, "approval_intelligence", intel)
    await db.commit()
    return updated
