"""Phase 2 autonomous engineering enrichment scans."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.contract_testing import analyze_contract_changes
from app.utils.preview_environment import build_preview_environment
from app.utils.test_generation import suggest_tests_for_changes


async def _save(db: AsyncSession, run_id: uuid.UUID, artifact_type: str, content: dict[str, Any]) -> None:
    db.add(PipelineArtifact(pipeline_run_id=run_id, artifact_type=artifact_type, content=content))


async def run_phase2_enrichment(
    db: AsyncSession,
    run: PipelineRun,
    *,
    repo_path: str,
    changed_files: list[str],
    skip_if_present: bool,
    existing: dict[str, dict[str, Any]],
    pr_number: int | None = None,
) -> dict[str, Any]:
    if skip_if_present and existing.get("contract_test_report"):
        return existing

    contract = analyze_contract_changes(repo_path, changed_files)
    await _save(db, run.id, "contract_test_report", contract)

    test_gen = suggest_tests_for_changes(changed_files, repo_path)
    await _save(db, run.id, "test_generation_report", test_gen)

    preview = build_preview_environment(
        run_id=str(run.id),
        branch=run.branch,
        pr_number=pr_number,
        simulated=True,
    )
    await _save(db, run.id, "preview_environment", preview)

    await db.commit()
    return {
        "contract_test_report": contract,
        "test_generation_report": test_gen,
        "preview_environment": preview,
    }
