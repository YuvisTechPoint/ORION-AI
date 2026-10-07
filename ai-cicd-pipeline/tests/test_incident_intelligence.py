"""Tests for Phase 10 AI Incident Command Center."""

from __future__ import annotations

import pytest

from app.utils.incident_commander import run_incident_commander
from app.utils.incident_intelligence import build_incident_intelligence_report, evaluate_incident_gates
from app.utils.incident_lifecycle import initial_lifecycle, transition_lifecycle


def test_initial_lifecycle_p1_investigating():
    lifecycle = initial_lifecycle(severity="P1", source="monitoring")
    assert lifecycle["status"] == "investigating"
    assert lifecycle["severity"] == "P1"


def test_transition_lifecycle_to_mitigated():
    lifecycle = initial_lifecycle(severity="P1")
    updated = transition_lifecycle(lifecycle, "mitigated", note="rolled back traffic")
    assert updated["status"] == "mitigated"
    assert len(updated["history"]) >= 2


def test_transition_invalid_raises():
    lifecycle = initial_lifecycle(severity="P3")
    with pytest.raises(ValueError):
        transition_lifecycle(lifecycle, "resolved")


def test_build_incident_intelligence_report():
    commander = run_incident_commander(
        run_id="abc12345-0000-0000-0000-000000000000",
        repo="org/app",
        branch="main",
        commit="cafebabe",
        artifacts={"deployment_info": {"image_tag": "v1"}},
        metrics={"health_status_code": 503, "error_count": 12},
        log_excerpt="health check failed",
    )
    report = build_incident_intelligence_report(
        commander,
        run_id="abc12345-0000-0000-0000-000000000000",
        repo="org/app",
        branch="main",
        commit="cafebabe",
        slack_notified=True,
    )
    assert report["incident_id"] == commander["incident_id"]
    assert report["lifecycle"]["status"] == "investigating"
    assert report["notifications"]["slack_p0_sent"] is True
    assert report["rca"]["primary_hypothesis"]


def test_evaluate_incident_gates_p1_warn():
    report = {
        "severity": "P1",
        "lifecycle": {"status": "investigating"},
        "rca": {"primary_hypothesis": {"confidence": 0.88}},
        "runbooks": {"runbooks": [{"runbook_id": "REDIS-004"}]},
    }
    gates = evaluate_incident_gates(report)
    assert gates["gate_verdict"] == "warn"
