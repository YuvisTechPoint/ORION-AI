"""Tests for Phase 3 multi-layer code review intelligence."""

from __future__ import annotations

from app.utils.code_review_intelligence import (
    build_code_review_intelligence_report,
    evaluate_code_review_gates,
    predict_bug_probability,
)


def test_build_code_review_report_all_layers():
    report = build_code_review_intelligence_report(
        code_analysis={
            "severity": "pass",
            "issues": [{"type": "unused-import", "file": "app.py", "line": 1}],
            "warnings_count": 1,
            "analysis_mode": "heuristic",
        },
        security_scan={"highest_severity": "low", "vulnerabilities": []},
        qa_report={"verdict": "pass"},
        service_graph={"node_count": 2, "nodes": {"api": {}, "redis": {}}, "changed_services": ["api"]},
        repository_intelligence={"stack": "python"},
        change_risk_report={"final_risk": 22, "risk_level": "low", "dimensions": {"code_risk": 10}},
        stress_report={"performance_verdict": "pass", "p95_ms": 320},
        changed_files=["app/main.py"],
    )
    assert set(report["layers"]) == {
        "L0_syntax",
        "L1_static",
        "L2_semantic",
        "L3_architecture",
        "L4_security",
        "L5_performance",
        "L6_maintainability",
        "L7_production_risk",
    }
    assert report["overall_score"] >= 50
    assert report["gate_verdict"] in {"pass", "warn"}
    assert "bug_prediction" in report
    assert report["summary"]


def test_code_review_gate_fails_on_syntax():
    report = build_code_review_intelligence_report(
        code_analysis={
            "severity": "fail",
            "issues": [
                {"type": "syntax-error", "file": "bad.py", "line": 3},
                {"type": "undefined-name", "file": "bad.py", "line": 4},
            ],
            "critical_issues_count": 2,
            "warnings_count": 0,
        },
        security_scan={"highest_severity": "critical", "vulnerabilities": [{"severity": "critical"}]},
        qa_report={"verdict": "fail"},
        change_risk_report={"final_risk": 82, "risk_level": "high"},
        changed_files=["auth/middleware.py", "payments/service.py"],
    )
    gates = evaluate_code_review_gates(report)
    assert gates["gate_verdict"] == "fail"
    assert gates["violations"]


def test_bug_prediction_elevates_with_risk():
    layers = {
        "L0_syntax": {"verdict": "warn"},
        "L1_static": {"verdict": "pass"},
        "L2_semantic": {"verdict": "pass"},
    }
    prediction = predict_bug_probability(
        layers=layers,
        change_risk={"final_risk": 75},
        code={"severity": "warn"},
        security={"highest_severity": "high"},
        qa={"verdict": "pass"},
    )
    assert prediction["probability"] >= 0.35
    assert prediction["risk_band"] in {"medium", "high"}
