"""Tests for Phase 23 Advanced Command Hub operations center."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from hub.federation.intelligence_fanout import fanout_intelligence
from hub.federation.models import StackIntelligenceSnapshot, UnifiedPipelineRun
from hub.federation.operations_center import build_operations_center
from hub.server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_operations_center_endpoint(client):
    fake_report = {
        "generated_at": "2026-10-07T00:00:00+00:00",
        "active_pipelines": 2,
        "blocked_pipelines": 1,
        "incidents_open": 0,
        "summary": "Operations Center: 2 active pipeline(s), 1 blocked, 0 open incident(s), fleet risk repo=—.",
        "slo_summary": {"avg_pass_rate": 0.8},
        "top_blockers": ["[orion] blocked_tests"],
        "alerts": [],
        "fleet": {},
        "stack_intelligence": [],
        "service_grid": [],
    }

    with patch("hub.server.build_operations_center", new=AsyncMock(return_value=type("R", (), {"model_dump": lambda self: fake_report})())):
        resp = client.get("/api/v1/control-plane/operations")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_pipelines"] == 2
    assert body["blocked_pipelines"] == 1


@pytest.mark.asyncio
async def test_fanout_intelligence_merges_stacks():
    dashboards = {
        "http://127.0.0.1:8001/api/v1/intelligence/dashboard": (
            200,
            {
                "pipelines": {"pass_rate": 0.9, "top_blockers": ["blocked_security"]},
                "slo": {"success_rate": 0.9},
                "alerts": [{"code": "slo_success_low"}],
            },
        ),
    }

    async def fake_fetch(url, **kwargs):
        return dashboards.get(url, (404, {}))

    with patch("hub.federation.intelligence_fanout.fetch_json", new=AsyncMock(side_effect=fake_fetch)):
        with patch(
            "hub.federation.intelligence_fanout.stack_entries",
            return_value=[
                {
                    "id": "orion",
                    "title": "ORION",
                    "intelligence": "http://127.0.0.1:8001/api/v1/intelligence/dashboard",
                }
            ],
        ):
            snaps = await fanout_intelligence()
    assert len(snaps) == 1
    assert snaps[0].available is True
    assert snaps[0].pass_rate == 0.9
    assert "blocked_security" in snaps[0].top_blockers


@pytest.mark.asyncio
async def test_build_operations_center_counts():
    pipelines = type(
        "P",
        (),
        {
            "items": [
                UnifiedPipelineRun(
                    id="orion:a",
                    stack="orion",
                    native_id="a",
                    repository="acme/a",
                    status="running_qa",
                ),
                UnifiedPipelineRun(
                    id="orion:b",
                    stack="orion",
                    native_id="b",
                    repository="acme/b",
                    status="blocked_tests",
                ),
                UnifiedPipelineRun(
                    id="orion:c",
                    stack="orion",
                    native_id="c",
                    repository="acme/c",
                    status="deployed",
                ),
            ]
        },
    )()
    health = type("H", (), {"stacks": []})()
    snapshots = [
        StackIntelligenceSnapshot(
            stack="orion",
            title="ORION",
            available=True,
            pass_rate=0.75,
            top_blockers=["blocked_tests"],
            alerts=[{"code": "slo_blocked_high", "stack": "orion"}],
        )
    ]

    with patch("hub.federation.operations_center.health_matrix", new=AsyncMock(return_value=health)):
        with patch("hub.federation.operations_center.federated_list_pipelines", new=AsyncMock(return_value=pipelines)):
            with patch("hub.federation.operations_center.fanout_intelligence", new=AsyncMock(return_value=snapshots)):
                with patch("hub.federation.operations_center.fetch_orion_fleet", new=AsyncMock(return_value={"highest_risk_repo": "acme/b"})):
                    with patch("hub.federation.operations_center.fetch_orion_incidents", new=AsyncMock(return_value=[])):
                        with patch(
                            "hub.federation.operations_center.fetch_orion_platform_events",
                            new=AsyncMock(return_value={"available": True, "count": 1, "events": [{"event_type": "pipeline.completed"}]}),
                        ):
                            report = await build_operations_center(correlation_id="cid-1")

    assert report.active_pipelines == 1
    assert report.blocked_pipelines == 1
    assert report.deployed_recent == 1
    assert report.slo_summary["avg_pass_rate"] == 0.75
    assert any("orion" in b for b in report.top_blockers)
    assert report.policy_panel.get("stacks")
    assert report.security_panel.get("stacks") is not None
    assert "performance" in report.performance_panel or report.performance_panel.get("stacks") is not None
    assert report.platform_events.get("count") == 1
    assert report.memory_panel.get("stacks") is not None


def test_platform_events_endpoint(client):
    fake = {"available": True, "count": 2, "events": [{"event_type": "pipeline.started"}]}
    with patch("hub.server.fetch_orion_platform_events", new=AsyncMock(return_value=fake)):
        resp = client.get("/api/v1/control-plane/platform-events?limit=10")
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


def test_platform_events_stream(client):
    tick = 0

    async def fake_fetch(**_kwargs):
        nonlocal tick
        tick += 1
        if tick == 1:
            return {
                "available": True,
                "events": [{"event_id": "e1", "event_type": "pipeline.started", "correlation_id": "c1"}],
            }
        return {
            "available": True,
            "events": [
                {"event_id": "e1", "event_type": "pipeline.started", "correlation_id": "c1"},
                {"event_id": "e2", "event_type": "pipeline.completed", "correlation_id": "c1"},
            ],
        }

    with patch("hub.server.fetch_orion_platform_events", new=AsyncMock(side_effect=fake_fetch)):
        with patch("hub.server.asyncio.sleep", new=AsyncMock()):
            with client.stream(
                "GET",
                "/api/v1/control-plane/platform-events/stream?max_ticks=2",
            ) as resp:
                assert resp.status_code == 200
                body = "".join(resp.iter_text())
    assert "pipeline.started" in body
    assert "pipeline.completed" in body
    assert '"kind": "complete"' in body or '"kind":"complete"' in body.replace(" ", "")


def test_ops_panels_from_capabilities():
    from hub.federation.operations_center import _ops_panels
    from hub.federation.models import StackIntelligenceSnapshot

    snaps = [
        StackIntelligenceSnapshot(
            stack="orion",
            title="ORION",
            available=True,
            capabilities={
                "policy_engine": "hybrid",
                "opa_adapter": True,
                "bandit_scanner": True,
                "pip_audit_scanner": True,
                "performance_baseline_persist": True,
                "memory_gateway": True,
                "platform_event_bus": True,
            },
        )
    ]
    panels = _ops_panels(snaps, {"highest_risk_repo": "acme/api", "avg_risk_score": 42})
    assert panels["policy"]["opa_enabled"] is True
    assert panels["security"]["real_sast"] is True
    assert panels["performance"]["baseline_persist"] is True
    assert panels["memory"]["gateway_enabled"] is True
