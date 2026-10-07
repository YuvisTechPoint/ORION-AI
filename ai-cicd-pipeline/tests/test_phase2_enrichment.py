"""Phase 2 autonomous engineering unit tests."""

from app.services.fix_loop_service import run_fix_loop
from app.services.auto_pr_service import IssueBundle
from app.services.github_service import GitHubService
from app.services.pr_intelligence import build_pr_review_comment, post_pr_intelligence
from app.utils.contract_testing import analyze_contract_changes
from app.utils.patch_confidence import compute_patch_confidence
from app.utils.preview_environment import build_preview_environment
from app.utils.progressive_delivery import run_blue_green_delivery, run_progressive_delivery
from app.utils.rollback_intelligence import assess_rollback
from app.utils.test_generation import suggest_tests_for_changes
import pytest


def test_patch_confidence_auto_pr_threshold() -> None:
    report = compute_patch_confidence(
        sandbox={"passed": True, "applied_files": ["a.py"]},
        patches=[{"fixed_content": "x=1\n"}],
        security_passed=True,
    )
    assert report["patch_confidence"] >= 70
    assert report["action"] in {"auto_pr", "review_required"}


def test_contract_testing_no_specs(tmp_path) -> None:
    report = analyze_contract_changes(str(tmp_path), changed_files=["README.md"])
    assert report["verdict"] == "pass"


def test_test_generation_suggestions(tmp_path) -> None:
    mod = tmp_path / "payment"
    mod.mkdir()
    (mod / "service.py").write_text("def calculate_tax(x):\n    return x * 0.1\n", encoding="utf-8")
    report = suggest_tests_for_changes(["payment/service.py"], str(tmp_path))
    assert report["functions_analyzed"] >= 1


def test_preview_environment_url() -> None:
    preview = build_preview_environment(run_id="abc12345-0000-0000-0000-000000000000", branch="feature/x", pr_number=42)
    assert "pr-42" in preview["preview_url"]


@pytest.mark.asyncio
async def test_progressive_delivery_simulated() -> None:
    report = await run_progressive_delivery(health_url="http://127.0.0.1:1/health", simulated=True, observe_seconds=0)
    assert report["passed"] is True
    assert report["final_traffic_percent"] == 100
    assert report["strategy"] == "canary"


@pytest.mark.asyncio
async def test_blue_green_delivery_simulated() -> None:
    report = await run_blue_green_delivery(health_url="http://127.0.0.1:1/health", simulated=True, observe_seconds=0)
    assert report["strategy"] == "blue_green"
    assert report["active_slot_after"] == "green"


def test_rollback_intelligence_high_confidence() -> None:
    report = assess_rollback(
        metrics={"health_status_code": 503, "error_count": 50, "response_time_ms": 3000, "sample_size": 100},
        change_risk={"final_risk": 70},
    )
    assert report["recommend_rollback"] is True
    assert report["rollback_confidence"] >= 0.75


@pytest.mark.asyncio
async def test_pr_intelligence_skips_without_github_token() -> None:
    gh = GitHubService(token="")
    result = await post_pr_intelligence(
        gh,
        repo_full_name="acme/demo",
        commit_sha="a" * 40,
        artifacts={},
    )
    assert result["posted"] is False
    assert result["reason"] == "github_disabled"


def test_github_service_omits_auth_header_without_token() -> None:
    gh = GitHubService(token="")
    assert gh.enabled is False
    assert "Authorization" not in gh._headers()


def test_pr_review_comment_includes_risk() -> None:
    body = build_pr_review_comment(
        {
            "change_risk_report": {"final_risk": 64, "risk_level": "high"},
            "qa_report": {"verdict": "pass", "test_summary": {"passed": 10, "total": 10}},
            "security_scan": {"highest_severity": "low"},
        }
    )
    assert "ORION REVIEW" in body
    assert "64/100" in body


def test_fix_loop_empty_bundles(tmp_path) -> None:
    report = run_fix_loop(str(tmp_path), [])
    assert "aggregate_confidence" in report
