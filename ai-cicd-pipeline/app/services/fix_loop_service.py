"""Autonomous fix loop: sandbox verify → patch confidence → registry update."""

from __future__ import annotations

from typing import Any

from app.services.auto_pr_service import IssueBundle
from app.utils.agent_sandbox import AgentSandbox
from app.utils.patch_confidence import compute_patch_confidence


def run_fix_loop(
    repo_path: str,
    bundles: list[IssueBundle],
    *,
    security_passed: bool = True,
    qa_verdict: str = "pass",
) -> dict[str, Any]:
    """Verify AI patches in isolated sandbox and score confidence per bundle."""
    bundle_reports: list[dict[str, Any]] = []
    all_patches: list[dict[str, Any]] = []
    sandbox_passed = True

    for bundle in bundles:
        patches = bundle.changed_patches
        all_patches.extend(patches)
        if not patches:
            bundle_reports.append({"category": bundle.category, "skipped": True})
            continue

        with AgentSandbox() as sandbox:
            result = sandbox.verify_patches(repo_path, patches)
            sandbox_data = result.to_dict()
        if not sandbox_data.get("passed"):
            sandbox_passed = False

        confidence = compute_patch_confidence(
            sandbox=sandbox_data,
            patches=patches,
            security_passed=security_passed,
            qa_verdict=qa_verdict,
        )
        bundle_reports.append(
            {
                "category": bundle.category,
                "branch": bundle.branch_name,
                "pr_number": bundle.pr_number,
                "sandbox": sandbox_data,
                "patch_confidence": confidence,
            }
        )

    aggregate = compute_patch_confidence(
        sandbox={"passed": sandbox_passed},
        patches=all_patches,
        security_passed=security_passed,
        qa_verdict=qa_verdict,
    )

    return {
        "bundles": bundle_reports,
        "aggregate_confidence": aggregate,
        "summary": aggregate.get("summary"),
        "analysis_mode": "heuristic",
    }
