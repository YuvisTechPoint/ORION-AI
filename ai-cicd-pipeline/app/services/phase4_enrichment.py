"""Phase 4 enterprise enrichment — policy, compliance, FinOps, tenant RBAC."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.compliance_packs import evaluate_compliance
from app.utils.enterprise_sso import assess_sso_readiness
from app.utils.finops import compute_pipeline_cost
from app.utils.policy_engine import evaluate_policies
from app.utils.policy_intelligence import build_policy_intelligence_report
from app.utils.policy_registry import resolve_effective_policies
from app.utils.signed_builds import signed_build_verify_options, verify_signed_build
from app.utils.tenant_rbac import resolve_tenant_context


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def run_phase4_enrichment(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
    skip_if_present: bool = False,
    user_roles: list[str] | None = None,
    include_policy: bool = False,
) -> dict[str, Any]:
    if skip_if_present and artifacts.get("compliance_report"):
        result = {
            "compliance_report": artifacts.get("compliance_report"),
            "tenant_rbac_context": artifacts.get("tenant_rbac_context"),
            "cost_report": artifacts.get("cost_report"),
            "signed_build_report": artifacts.get("signed_build_report"),
            "sso_readiness": artifacts.get("sso_readiness"),
        }
        if include_policy or artifacts.get("policy_evaluation"):
            result["policy_evaluation"] = artifacts.get("policy_evaluation")
        return result

    tenant = resolve_tenant_context(run.repo_full_name, user_roles=user_roles)
    await _save(db, run.id, "tenant_rbac_context", tenant)
    artifacts = {**artifacts, "tenant_rbac_context": tenant}

    signed = verify_signed_build(
        commit=run.commit_id,
        repo=run.repo_full_name,
        deployment_info=artifacts.get("deployment_info"),
        **signed_build_verify_options(),
    )
    await _save(db, run.id, "signed_build_report", signed)

    policy: dict[str, Any] | None = None
    if include_policy:
        policy = evaluate_policies(
            artifacts,
            unsigned_image=not signed.get("verified", True),
            strict_requirements=settings.policy_strict_requirements,
        )
        await _save(db, run.id, "policy_evaluation", policy)

    compliance = evaluate_compliance(artifacts, pack_ids=settings.compliance_pack_list)
    await _save(db, run.id, "compliance_report", compliance)

    duration = None
    created = _as_utc(run.created_at)
    completed = _as_utc(run.completed_at)
    if created and completed:
        duration = max(0.0, (completed - created).total_seconds())
    elif created:
        duration = max(0.0, (datetime.now(timezone.utc) - created).total_seconds())

    cost = compute_pipeline_cost(
        run_id=str(run.id),
        repo=run.repo_full_name,
        duration_seconds=duration,
        artifacts=artifacts,
        llm_cost_per_1k_tokens=settings.finops_llm_cost_per_1k_tokens,
        compute_cost_per_minute=settings.finops_compute_cost_per_minute,
    )
    await _save(db, run.id, "cost_report", cost)

    sso = assess_sso_readiness()
    await _save(db, run.id, "sso_readiness", sso)

    await db.commit()
    result = {
        "tenant_rbac_context": tenant,
        "signed_build_report": signed,
        "compliance_report": compliance,
        "cost_report": cost,
        "sso_readiness": sso,
    }
    if policy is not None:
        result["policy_evaluation"] = policy
    return result


def _org_from_repo(repo_full_name: str) -> str:
    return repo_full_name.split("/", 1)[0] if "/" in repo_full_name else repo_full_name


async def run_phase4_policy_gate(
    db: AsyncSession,
    run: PipelineRun,
    *,
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate scoped policies and AI autonomy rules before release."""
    signed = artifacts.get("signed_build_report") or verify_signed_build(
        commit=run.commit_id,
        repo=run.repo_full_name,
        deployment_info=artifacts.get("deployment_info"),
        **signed_build_verify_options(),
    )
    org = _org_from_repo(run.repo_full_name)
    environment = settings.deploy_environment
    policies = resolve_effective_policies(org=org, repo=run.repo_full_name, environment=environment)
    policy = evaluate_policies(
        artifacts,
        policies=policies,
        unsigned_image=not signed.get("verified", True),
        strict_requirements=settings.policy_strict_requirements,
    )
    report = build_policy_intelligence_report(
        org=org,
        repo=run.repo_full_name,
        environment=environment,
        artifacts={**artifacts, "policy_evaluation": policy},
        policy_evaluation=policy,
        unsigned_image=not signed.get("verified", True),
    )

    passed = bool(policy.get("passed", True))
    if settings.policy_ai_autonomy_enforcement_enabled:
        passed = passed and bool(report.get("ai_autonomy_policy", {}).get("passed", True))

    await _save(db, run.id, "policy_evaluation", policy)
    await _save(db, run.id, "policy_intelligence", report)
    await db.commit()

    return {
        **policy,
        "passed": passed,
        "policy_intelligence": report,
        "gate_verdict": report.get("gate_verdict"),
        "ai_autonomy_passed": report.get("ai_autonomy_policy", {}).get("passed", True),
    }
