"""Policy-as-code API — catalog, effective rules, and evaluation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import optional_auth
from app.config import settings
from app.database import get_db
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.policy_enrichment import persist_policy_intelligence, _org_from_repo
from app.utils.policy_engine import DEFAULT_POLICIES
from app.utils.policy_intelligence import build_policy_intelligence_report
from app.utils.policy_registry import build_policy_registry_report, resolve_effective_policies
from app.utils.signed_builds import verify_signed_build

router = APIRouter(prefix="/policies", tags=["Policies"])


class PolicyEvaluateRequest(BaseModel):
    pipeline_run_id: str | None = None
    repo: str | None = None
    environment: str | None = None
    persist: bool = Field(default=True)


@router.get("/catalog")
async def policies_catalog(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "defaults": DEFAULT_POLICIES,
        "enforcement_enabled": settings.policy_enforcement_enabled,
        "strict_requirements": settings.policy_strict_requirements,
        "compliance_packs": settings.compliance_pack_list,
        "config_keys": [
            "POLICY_ORG_RULES_JSON",
            "POLICY_REPO_RULES_JSON",
            "POLICY_ENV_RULES_JSON",
            "POLICY_AI_AUTONOMY_MAX_LEVEL",
            "POLICY_ENFORCEMENT_ENABLED",
        ],
    }


@router.get("/effective")
async def policies_effective(
    repo: str,
    environment: str | None = None,
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    org = _org_from_repo(repo)
    env = environment or settings.deploy_environment
    registry = build_policy_registry_report(org=org, repo=repo, environment=env)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **registry,
        "effective_policies": resolve_effective_policies(org=org, repo=repo, environment=env),
    }


@router.post("/evaluate")
async def policies_evaluate(
    body: PolicyEvaluateRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(optional_auth),
) -> dict[str, Any]:
    artifacts: dict[str, dict[str, Any]] = {}
    run: PipelineRun | None = None
    repo = body.repo
    environment = body.environment or settings.deploy_environment

    if body.pipeline_run_id:
        try:
            run_id = uuid.UUID(body.pipeline_run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pipeline_run_id") from exc
        run = await db.get(PipelineRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")
        rows = (
            await db.execute(select(PipelineArtifact).where(PipelineArtifact.pipeline_run_id == run.id))
        ).scalars().all()
        artifacts = {a.artifact_type: a.content or {} for a in rows}
        repo = run.repo_full_name

    if not repo:
        raise HTTPException(status_code=400, detail="Provide pipeline_run_id or repo")

    org = _org_from_repo(repo)
    signed = artifacts.get("signed_build_report") or verify_signed_build(
        commit=(run.commit_id if run else ""),
        repo=repo,
        deployment_info=artifacts.get("deployment_info"),
        require_signature=settings.require_signed_builds,
        simulated=not settings.require_signed_builds,
    )

    if body.persist and run is not None:
        report = await persist_policy_intelligence(db, run, artifacts=artifacts)
    else:
        report = build_policy_intelligence_report(
            org=org,
            repo=repo,
            environment=environment,
            artifacts=artifacts,
            unsigned_image=not signed.get("verified", True),
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persisted": body.persist and run is not None,
        "report": report,
    }
