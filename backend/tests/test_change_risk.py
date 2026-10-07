from core.change_risk import compute_change_risk


def test_canonical_change_risk_from_repo_files() -> None:
    report = compute_change_risk(
        changed_files=["auth/login.py", "requirements.txt"],
        code={"severity": "pass"},
        security={"highest_severity": "low", "passed": True},
        qa={"passed": True},
    )
    assert report["dimensions"]["blast_radius"] >= 10
    assert "authentication" in report["blast_radius_analysis"]["critical_categories"]
