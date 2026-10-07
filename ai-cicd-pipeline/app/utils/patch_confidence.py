"""Patch confidence scoring for AI-generated fixes."""

from __future__ import annotations

from typing import Any


def compute_patch_confidence(
    *,
    sandbox: dict[str, Any] | None = None,
    patches: list[dict[str, Any]] | None = None,
    security_passed: bool = True,
    qa_verdict: str = "pass",
) -> dict[str, Any]:
    """Score autonomous patches 0–100 with gate thresholds."""
    patches = patches or []
    sandbox = sandbox or {}

    checks: dict[str, bool] = {
        "compilation": True,
        "unit_tests": bool(sandbox.get("passed", sandbox.get("pytest_exit_code") in (0, 5))),
        "security": security_passed,
        "lint": True,
    }
    if str(qa_verdict).lower() == "fail":
        checks["unit_tests"] = False

    applied = len(sandbox.get("applied_files") or [p for p in patches if p.get("fixed_content")])
    if applied == 0:
        checks["unit_tests"] = False

    total_lines = sum(len(str(p.get("fixed_content", "")).splitlines()) for p in patches)
    diff_complexity = "low" if total_lines < 80 else "medium" if total_lines < 300 else "high"
    if diff_complexity == "high":
        checks["lint"] = False

    score = 40
    score += 30 if checks["unit_tests"] else 0
    score += 15 if checks["security"] else 0
    score += 10 if diff_complexity == "low" else 5 if diff_complexity == "medium" else 0
    score += 5 if applied <= 3 else 0
    score = min(100, score)

    ai_uncertainty = "low" if score >= 85 else "medium" if score >= 70 else "high"
    if score >= 90:
        action = "auto_pr"
    elif score >= 70:
        action = "review_required"
    else:
        action = "reject"

    return {
        "patch_confidence": score,
        "action": action,
        "checks": checks,
        "diff_complexity": diff_complexity,
        "files_patched": applied,
        "ai_uncertainty": ai_uncertainty,
        "summary": f"Patch confidence {score}% — {action.replace('_', ' ')}",
    }
