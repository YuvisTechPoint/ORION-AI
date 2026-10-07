"""Tests for Phase 8 deployment intelligence."""

from __future__ import annotations

import pytest

from app.utils.deployment_intelligence import (
    build_deployment_intelligence_report,
    evaluate_deployment_gates,
    evaluate_slo_rollback_signals,
    plan_deployment_strategy,
)
from app.utils.environment_registry import build_environment_registry
from app.utils.progressive_delivery import run_blue_green_delivery, run_progressive_delivery


def test_environment_registry_lists_targets():
    registry = build_environment_registry()
    assert registry["count"] >= 2
    names = {env["name"] for env in registry["environments"]}
    assert "preview" in names


def test_plan_deployment_strategy_blue_green(monkeypatch):
    monkeypatch.setattr("app.utils.deployment_intelligence.settings.progressive_delivery_enabled", True)
    monkeypatch.setattr("app.utils.deployment_intelligence.settings.deployment_strategy", "blue_green")
    plan = plan_deployment_strategy(
        deployment_info={"success": True},
        progressive_delivery={"strategy": "blue_green", "passed": True},
    )
    assert plan["selected"] == "blue_green"
    assert plan["blue_green"] is True


def test_slo_rollback_signals_error_budget(monkeypatch):
    monkeypatch.setattr("app.utils.deployment_intelligence.settings.deployment_slo_gate_enabled", True)
    slo = evaluate_slo_rollback_signals(
        deployment_info={"success": True, "health_check_passed": True},
        progressive_delivery={"strategy": "canary", "passed": True},
        error_budget_report={"freeze_risky_releases": True},
        stress_report={"performance_verdict": "pass", "p95_ms": 300},
        change_risk_report={"final_risk": 20},
    )
    assert "error budget exhausted" in slo["signals"][0]
    assert slo["verdict"] in {"fail", "warn"}


def test_build_deployment_report_pass():
    report = build_deployment_intelligence_report(
        deployment_info={
            "success": True,
            "simulated": True,
            "environment": "staging",
            "health_check_passed": True,
        },
        progressive_delivery={"strategy": "canary", "passed": True, "final_traffic_percent": 100},
        error_budget_report={"error_budget_remaining_percent": 80},
        stress_report={"performance_verdict": "pass", "p95_ms": 350},
    )
    assert report["gate_verdict"] in {"pass", "warn"}
    assert report["strategy"]["selected"]
    assert report["environment_registry"]["count"] >= 2


def test_evaluate_deployment_gates_failed_deploy():
    report = {
        "deployment": {"success": False},
        "progressive_delivery": {"strategy": "canary", "passed": True},
        "slo_rollback": {"verdict": "pass", "signals": []},
    }
    gates = evaluate_deployment_gates(report)
    assert gates["gate_verdict"] == "fail"
    assert "deployment failed" in gates["violations"]


@pytest.mark.asyncio
async def test_blue_green_delivery_simulated():
    report = await run_blue_green_delivery(
        health_url="http://127.0.0.1:1/health",
        simulated=True,
        observe_seconds=0,
    )
    assert report["strategy"] == "blue_green"
    assert report["passed"] is True
    assert report["active_slot_after"] == "green"


@pytest.mark.asyncio
async def test_progressive_delivery_routes_blue_green(monkeypatch):
    monkeypatch.setattr("app.utils.progressive_delivery.settings.deployment_strategy", "blue_green")
    report = await run_progressive_delivery(
        health_url="http://127.0.0.1:1/health",
        simulated=True,
        observe_seconds=0,
        strategy="blue_green",
    )
    assert report["strategy"] == "blue_green"
    assert report["passed"] is True
