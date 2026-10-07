from fastapi.testclient import TestClient

from main import create_app


def test_runtime_navigation_endpoint() -> None:
    client = TestClient(create_app())
    res = client.get("/api/v1/runtime/navigation")
    assert res.status_code == 200
    body = res.json()
    assert body["active_stack"] == "canonical"
    ids = {s["id"] for s in body["stacks"]}
    assert "hub" in ids and "orion" in ids and "platform" in ids
