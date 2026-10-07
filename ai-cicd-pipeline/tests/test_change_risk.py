from app.utils.change_risk import analyze_changed_paths, compute_change_risk


def test_readme_only_low_risk() -> None:
    report = compute_change_risk(changed_files=["README.md"])
    assert report["final_risk"] < 15
    assert report["blast_radius_analysis"]["low_risk_docs_only"] is True


def test_payment_auth_paths_high_blast_radius() -> None:
    paths = analyze_changed_paths(["auth/middleware.py", "payments/service.py", "database/migrations/001.sql"])
    assert paths["blast_radius_level"] in {"medium", "high"}
    assert "authentication" in paths["critical_categories"]
    assert "payments" in paths["critical_categories"]
    assert "database_schema" in paths["critical_categories"]


def test_security_fail_elevates_final_risk() -> None:
    report = compute_change_risk(
        changed_files=["payments/service.py"],
        security={"highest_severity": "critical", "passed": False},
        code={"severity": "pass"},
        qa={"passed": True, "verdict": "pass"},
    )
    assert report["dimensions"]["security_risk"] >= 75
    assert report["final_risk"] >= 35
    assert report["risk_level"] in {"medium", "high"}


def test_gate_fusion_fail_recommendation() -> None:
    report = compute_change_risk(
        changed_files=["app/main.py"],
        code={"severity": "fail"},
        security={"highest_severity": "low", "passed": True},
        qa={"passed": True},
    )
    assert report["gate_fusion_verdict"] == "fail"
    assert any("gate fusion failed" in r for r in report["recommendations"])
