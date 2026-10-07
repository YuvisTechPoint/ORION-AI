"""Tests for Phase 11 autonomous remediation intelligence."""

from __future__ import annotations

from app.utils.patch_confidence import compute_patch_confidence
from app.utils.remediation_intelligence import (
    build_remediation_intelligence_report,
    classify_achieved_level,
    evaluate_remediation_gates,
)
from app.utils.remediation_levels import list_remediation_levels, level_rank


def test_remediation_levels_catalog():
    levels = list_remediation_levels()
    assert len(levels) >= 7
    assert level_rank("L4") == 4


def test_classify_l0_from_diagnostics_only():
    result = classify_achieved_level(
        diagnostics={"remediation_steps": ["Fix tests"], "operator_actions": ["retry"]},
        run_status="blocked_tests",
    )
    assert result["achieved_level"] in {"L0", "L1"}


def test_classify_l3_with_fix_loop():
    fix_loop = {
        "bundles": [
            {
                "category": "code-quality",
                "sandbox": {"passed": True},
                "patch_confidence": {"patch_confidence": 88, "action": "review_required"},
            }
        ],
        "aggregate_confidence": {"patch_confidence": 88, "action": "review_required", "checks": {"unit_tests": True}},
    }
    result = classify_achieved_level(fix_loop_report=fix_loop, patch_confidence=fix_loop["aggregate_confidence"])
    assert level_rank(result["achieved_level"]) >= 3


def test_build_remediation_report_blocked_run():
    report = build_remediation_intelligence_report(
        run={
            "id": "abc12345-0000-0000-0000-000000000000",
            "status": "blocked_code",
            "error_message": "pylint errors",
            "repo_full_name": "org/app",
            "branch": "main",
            "commit_id": "deadbeef",
        },
        artifacts={
            "code_analysis": {"severity": "fail", "summary": "3 errors"},
        },
    )
    assert report["autonomy"]["achieved_level"]
    assert report["explain"]["headline"]
    assert report["recommend"]["remediation_steps"]
    assert report["gate_verdict"] in {"pass", "warn", "fail"}


def test_evaluate_remediation_gates_reject():
    report = {
        "patch": {"aggregate_confidence": {"action": "reject", "checks": {"unit_tests": False}}},
        "auto_pr": {"count": 0},
        "autonomy": {"achieved_level": "L2"},
    }
    gates = evaluate_remediation_gates(report)
    assert gates["gate_verdict"] == "fail"


def test_patch_confidence_auto_pr_threshold():
    confidence = compute_patch_confidence(
        sandbox={"passed": True, "applied_files": ["a.py"]},
        patches=[{"fixed_content": "x=1\n"}],
        security_passed=True,
    )
    assert confidence["action"] in {"auto_pr", "review_required"}
