from services.auto_pr_service import AutoPRService


def test_fallback_report_patch_contains_actionable_details() -> None:
    service = AutoPRService(
        github_token="token",
        repo_full_name="owner/repo",
        clone_url="",
        base_branch="main",
    )

    patch = service._fallback_report_patch(
        category="security",
        issues=[
            {
                "type": "llm_call_error",
                "severity": "high",
                "fix": "retry",
            }
        ],
        run_id="abcde12345",
    )

    assert patch["file_path"].startswith("orion_reports/security_run_")
    assert "ORION Auto-PR Report" in patch["fixed_content"]
    assert "llm_call_error" in patch["fixed_content"]
    assert "high" in patch["fixed_content"]
