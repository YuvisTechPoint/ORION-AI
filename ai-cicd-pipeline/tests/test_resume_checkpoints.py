from app.agents.orchestrator import _combined_from_artifacts, _has_full_scan


def test_has_full_scan_combined() -> None:
    assert _has_full_scan({"full_scan_combined": {"code_issues": {}}})


def test_combined_from_individual_artifacts() -> None:
    arts = {
        "code_analysis": {"severity": "pass"},
        "security_scan": {"highest_severity": "low"},
        "qa_report": {"verdict": "pass"},
    }
    combined = _combined_from_artifacts(arts)
    assert "code_issues" in combined
