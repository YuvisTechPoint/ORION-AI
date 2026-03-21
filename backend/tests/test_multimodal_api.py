from __future__ import annotations

from fastapi.testclient import TestClient

from agents.multimodal.dockerfile_agent import DockerfileAgent
from agents.multimodal.github_log_agent import GitHubLogAgent
from agents.multimodal.log_analysis_agent import LogAnalysisAgent
from agents.multimodal.production_triage_agent import ProductionTriageAgent
from main import app


def test_multimodal_analyze_routes_to_log_agent(monkeypatch) -> None:
    def _fake_execute(self):
        return {"log_type": "build_error", "summary": "ok"}

    monkeypatch.setattr(LogAnalysisAgent, "execute", _fake_execute)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/multimodal/analyze",
            data={"agent_type": "log_analysis", "log_type": "build_error"},
            files=[("files", ("build.log", b"error line", "text/plain"))],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_type"] == "log_analysis"
    assert payload["result"]["log_type"] == "build_error"


def test_multimodal_analyze_routes_to_github_agent(monkeypatch) -> None:
    def _fake_execute(self):
        return {"workflow_name": "ci", "summary": "parsed"}

    monkeypatch.setattr(GitHubLogAgent, "execute", _fake_execute)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/multimodal/analyze",
            data={"agent_type": "github_actions"},
            files=[("files", ("logs.zip", b"PK\x03\x04", "application/zip"))],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_type"] == "github_actions"
    assert payload["result"]["workflow_name"] == "ci"


def test_multimodal_analyze_routes_to_docker_agent(monkeypatch) -> None:
    def _fake_execute(self):
        return {"security_score": 88, "auto_pr_triggered": False}

    monkeypatch.setattr(DockerfileAgent, "execute", _fake_execute)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/multimodal/analyze",
            data={"agent_type": "docker"},
            files=[("files", ("Dockerfile", b"FROM python:3.11", "text/plain"))],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_type"] == "docker"
    assert payload["result"]["security_score"] == 88


def test_multimodal_analyze_unsupported_agent_type() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/multimodal/analyze",
            data={"agent_type": "unknown"},
            files=[("files", ("a.txt", b"x", "text/plain"))],
        )

    assert response.status_code == 400
    assert "Unsupported agent_type" in response.json()["detail"]


def test_multimodal_triage_escalation_sends_slack(monkeypatch) -> None:
    def _fake_execute(self):
        return {
            "incident_severity": "P1",
            "incident_type": "outage",
            "affected_services": ["api"],
            "root_cause": "db down",
            "blast_radius": "global",
            "time_to_resolve_estimate_minutes": 45,
            "immediate_actions": [{"step": 1, "action": "restart", "command": "systemctl restart api", "expected_outcome": "service up"}],
            "rollback_steps": ["rollback release"],
            "post_incident_tasks": ["postmortem"],
            "monitoring_checks": ["error rate"],
            "summary": "critical outage",
            "escalate_to_human": True,
            "escalation_reason": "P1",
        }

    monkeypatch.setattr(ProductionTriageAgent, "execute", _fake_execute)
    monkeypatch.setattr("api.multimodal._send_triage_slack_alert", lambda *_args, **_kwargs: True)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/multimodal/triage",
            files=[("files", ("incident.log", b"fatal", "text/plain"))],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_type"] == "production_triage"
    assert payload["slack_sent"] is True
    assert payload["result"]["escalate_to_human"] is True
