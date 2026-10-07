"""Phase 1 P0 enrichment scans — service graph, SBOM, supply-chain, test intel."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.container_security import scan_container_security
from app.utils.iac_security import scan_iac_security
from app.utils.kubernetes_manifest import scan_kubernetes_manifests
from app.utils.release_passport import build_release_passport
from app.utils.sbom import generate_sbom
from app.utils.secrets_guardian import scan_secrets
from app.utils.service_catalog import build_service_catalog
from app.utils.service_graph import build_service_graph
from app.utils.artifact_summaries import summarize_artifact
from app.utils.repository_intelligence import analyze_repository
from app.utils.supply_chain_report import build_supply_chain_report
from app.utils.test_intelligence import build_test_intelligence_report


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(
        PipelineArtifact(
            pipeline_run_id=run_id,
            artifact_type=artifact_type,
            content=content,
        )
    )


async def run_phase1_enrichment(
    db: AsyncSession,
    run: PipelineRun,
    *,
    repo_path: str,
    diff_text: str,
    changed_files: list[str] | None,
    skip_if_present: bool,
    existing: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Run P0 supply-chain and intelligence scans; persist artifacts."""
    outputs: dict[str, Any] = {}

    if skip_if_present and existing.get("service_graph"):
        return existing

    repo_intel = analyze_repository(
        repo_path,
        repo=run.repo_full_name,
        commit=run.commit_id,
        changed_files=changed_files or [],
        diff_text=diff_text,
    )
    repo_intel["summary"] = summarize_artifact("repository_intelligence", repo_intel)
    await _save(db, run.id, "repository_intelligence", repo_intel)
    outputs["repository_intelligence"] = repo_intel

    graph = build_service_graph(repo_path, changed_files=changed_files or [])
    await _save(db, run.id, "service_graph", graph)
    outputs["service_graph"] = graph

    if settings.service_catalog_scan_enabled and not (skip_if_present and existing.get("service_catalog")):
        catalog = build_service_catalog(
            repo=run.repo_full_name,
            repo_path=repo_path,
            service_graph=graph,
            repository_intelligence=repo_intel,
        )
        catalog["summary"] = summarize_artifact("service_catalog", catalog)
        await _save(db, run.id, "service_catalog", catalog)
        outputs["service_catalog"] = catalog

    sbom = generate_sbom(repo_path, commit=run.commit_id, repo=run.repo_full_name)
    await _save(db, run.id, "sbom", sbom)
    outputs["sbom"] = sbom

    secrets = scan_secrets(repo_path, changed_files=changed_files)
    await _save(db, run.id, "secrets_scan", secrets)
    outputs["secrets_scan"] = secrets

    container = scan_container_security(repo_path)
    await _save(db, run.id, "container_security_scan", container)
    outputs["container_security_scan"] = container

    iac = scan_iac_security(repo_path, changed_files=changed_files)
    await _save(db, run.id, "iac_security_scan", iac)
    outputs["iac_security_scan"] = iac

    if settings.kubernetes_manifest_scan_enabled:
        k8s = scan_kubernetes_manifests(repo_path, changed_files=changed_files)
        k8s["summary"] = summarize_artifact("kubernetes_manifest_scan", k8s)
        await _save(db, run.id, "kubernetes_manifest_scan", k8s)
        outputs["kubernetes_manifest_scan"] = k8s

    flaky_hist: list[dict[str, Any]] = []
    qa_current = existing.get("qa_report") or {}
    if qa_current:
        prior_runs = (
            await db.execute(
                select(PipelineRun)
                .where(PipelineRun.repo_full_name == run.repo_full_name, PipelineRun.id != run.id)
                .order_by(desc(PipelineRun.created_at))
                .limit(10)
            )
        ).scalars().all()
        for prior in prior_runs:
            art = (
                await db.execute(
                    select(PipelineArtifact).where(
                        PipelineArtifact.pipeline_run_id == prior.id,
                        PipelineArtifact.artifact_type == "qa_report",
                    )
                )
            ).scalar_one_or_none()
            if art and isinstance(art.content, dict):
                flaky_hist.append(art.content)

    test_intel = build_test_intelligence_report(
        repo_path,
        changed_files=changed_files or [],
        qa_current=qa_current or None,
        historical_qa=flaky_hist,
        contract_report=existing.get("contract_test_report"),
        test_generation=existing.get("test_generation_report"),
    )
    test_intel["summary"] = summarize_artifact("test_intelligence", test_intel)
    await _save(db, run.id, "test_intelligence", test_intel)
    outputs["test_intelligence"] = test_intel

    supply = build_supply_chain_report(
        repo_path,
        sbom=sbom,
        secrets_scan=outputs.get("secrets_scan"),
        container_scan=outputs.get("container_security_scan"),
        iac_scan=outputs.get("iac_security_scan"),
        security_scan=existing.get("security_scan"),
    )
    supply["summary"] = summarize_artifact("supply_chain_report", supply)
    await _save(db, run.id, "supply_chain_report", supply)
    outputs["supply_chain_report"] = supply

    await db.commit()
    return outputs


async def persist_release_passport(
    db: AsyncSession,
    run: PipelineRun,
    artifacts: dict[str, dict[str, Any]],
    *,
    deploy_mode: str,
    environment: str,
) -> dict[str, Any]:
    passport = build_release_passport(
        run_id=str(run.id),
        repo=run.repo_full_name,
        branch=run.branch,
        commit=run.commit_id,
        artifacts=artifacts,
        deploy_mode=deploy_mode,
        environment=environment,
    )
    await _save(db, run.id, "release_passport", passport)
    await db.commit()
    return passport
