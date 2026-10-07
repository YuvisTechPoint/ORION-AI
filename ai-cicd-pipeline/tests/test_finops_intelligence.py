"""Tests for Phase 20 FinOps intelligence."""

from __future__ import annotations

import json

from app.utils.finops_intelligence import (
    build_finops_intelligence_report,
    build_fleet_cost_rollup,
    evaluate_finops_gates,
)
from app.utils.finops_registry import resolve_finops_budgets


def test_resolve_finops_budgets_defaults():
    budgets = resolve_finops_budgets("acme/payments")
    assert budgets["per_run_usd"] > 0
    assert budgets["monthly_usd"] > 0
    assert budgets["organization"] == "acme"


def test_budget_json_override(monkeypatch):
    monkeypatch.setattr(
        "app.utils.finops_registry.settings.finops_budget_json",
        json.dumps({"acme/payments": {"per_run_usd": 2.5, "monthly_usd": 200.0}}),
    )
    budgets = resolve_finops_budgets("acme/payments")
    assert budgets["per_run_usd"] == 2.5
    assert budgets["monthly_usd"] == 200.0


def test_fleet_cost_rollup():
    fleet = build_fleet_cost_rollup(
        [
            {"repository": "org/a", "total_usd_estimate": 1.2},
            {"repository": "org/b", "total_usd_estimate": 0.8},
            {"repository": "org/a", "total_usd_estimate": 0.5},
        ]
    )
    assert fleet["run_count"] == 3
    assert fleet["total_usd"] == 2.5
    assert fleet["by_repository"]["org/a"] == 1.7


def test_build_finops_report():
    report = build_finops_intelligence_report(
        run_id="run-1",
        repo="org/api",
        duration_seconds=90,
        artifacts={
            "cost_report": {
                "total_usd_estimate": 1.25,
                "breakdown": {"llm_usd": 0.9, "compute_usd": 0.35},
            },
            "code_analysis": {"tokens_used": 3000, "analysis_mode": "llm"},
            "ai_cost_optimization": {"potential_savings_percent": 12},
        },
    )
    assert report["cost_report"]["total_usd_estimate"] == 1.25
    assert report["token_total"] == 3000
    assert report["gate_verdict"] in {"pass", "warn", "fail"}
    assert "FinOps" in report["summary"]


def test_finops_gate_fail_per_run(monkeypatch):
    monkeypatch.setattr("app.utils.finops_intelligence.settings.finops_gate_enabled", True)
    monkeypatch.setattr("app.utils.finops_intelligence.settings.finops_budget_usd_per_run", 1.0)
    gates = evaluate_finops_gates(run_cost_usd=2.5, fleet_month_usd=2.5, budgets={"per_run_usd": 1.0, "monthly_usd": 100.0})
    assert gates["gate_verdict"] == "fail"
    assert gates["violations"]


def test_finops_gate_warn_when_disabled(monkeypatch):
    monkeypatch.setattr("app.utils.finops_intelligence.settings.finops_gate_enabled", False)
    gates = evaluate_finops_gates(run_cost_usd=9.0, fleet_month_usd=9.0, budgets={"per_run_usd": 1.0, "monthly_usd": 100.0})
    assert gates["gate_verdict"] == "warn"


def test_token_breakdown_in_report():
    report = build_finops_intelligence_report(
        artifacts={
            "security_scan": {"tokens_used": 1200, "agent_model": "claude-sonnet"},
            "qa_report": {"tokens_used": 800},
        },
    )
    assert report["token_total"] == 2000
    assert len(report["token_breakdown"]) == 2
