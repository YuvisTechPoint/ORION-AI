from fastapi.testclient import TestClient

from main import create_app


def test_intelligence_dashboard_endpoint() -> None:
    client = TestClient(create_app())
    res = client.get("/api/v1/intelligence/dashboard")
    assert res.status_code == 200
    body = res.json()
    assert body["stack"] == "canonical"
    assert "pipelines" in body
    assert body["capabilities"]["gate_fusion"] is True
