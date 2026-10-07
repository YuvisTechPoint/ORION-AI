"""Tests for Phase 6 test intelligence enhancements."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.utils.test_intelligence import (
    analyze_coverage_regression,
    build_test_intelligence_report,
    discover_test_layout,
    evaluate_test_gates,
    identify_mutation_targets,
    select_relevant_tests,
)


def test_discover_test_layout(tmp_path: Path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    layout = discover_test_layout(str(tmp_path))
    assert layout["has_tests"] is True
    assert layout["framework"] == "pytest"
    assert layout["test_file_count"] >= 1


def test_mutation_targets_flag_untested_module(tmp_path: Path):
    (tmp_path / "billing.py").write_text("def charge():\n    return 1\n", encoding="utf-8")
    report = identify_mutation_targets(["billing.py"], str(tmp_path))
    assert report["target_count"] >= 1
    assert report["targets"][0]["priority"] == "high"


def test_coverage_regression_detects_drop(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.utils.test_intelligence.settings.test_coverage_min_percent", 60.0)
    monkeypatch.setattr("app.utils.test_intelligence.settings.test_coverage_max_regression_percent", 2.0)
    result = analyze_coverage_regression(
        current_qa={"coverage": {"percent": 50.0}},
        historical_qa=[{"coverage": {"percent": 58.0}}],
    )
    assert result["verdict"] == "fail"
    assert result["violations"]


def test_build_test_intelligence_report_gate_warn(tmp_path: Path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (tmp_path / "alpha.py").write_text("def a(): pass\n", encoding="utf-8")
    (tmp_path / "beta.py").write_text("def b(): pass\n", encoding="utf-8")
    (tmp_path / "gamma.py").write_text("def c(): pass\n", encoding="utf-8")
    report = build_test_intelligence_report(str(tmp_path), changed_files=["alpha.py", "beta.py", "gamma.py"])
    assert report["gate_verdict"] in {"pass", "warn", "fail"}
    assert "coverage_regression" in report
    assert "mutation_targets" in report


def test_evaluate_test_gates_coverage_fail(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.utils.test_intelligence.settings.test_coverage_gate_enabled", True)
    report = {
        "flaky_analysis": {"flaky_count": 0},
        "coverage_regression": {"verdict": "fail", "violations": ["coverage 10% below minimum 50%"]},
        "mutation_targets": {"targets": []},
        "contract_testing": {},
    }
    gates = evaluate_test_gates(report)
    assert gates["gate_verdict"] == "fail"


def test_selection_unchanged(tmp_path: Path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_payment.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (tmp_path / "payment" / "service.py").parent.mkdir(parents=True)
    (tmp_path / "payment" / "service.py").write_text("x=1\n", encoding="utf-8")
    sel = select_relevant_tests(["payment/service.py"], str(tmp_path))
    assert sel["mode"] == "selected"
