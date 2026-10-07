"""Tests for /api/v1/tools text analysis endpoints."""

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_text_analyze_classify_log() -> None:
    response = client.post(
        "/api/v1/tools/text-analyze",
        json={
            "text": "ERROR connection timed out after 30s",
            "operations": ["metrics", "classify_log", "errors"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["log_type"] == "server_timeout"
    assert body["metrics"]["error_lines"] >= 1


def test_text_analyze_rejects_unknown_operation() -> None:
    response = client.post(
        "/api/v1/tools/text-analyze",
        json={"text": "hello", "operations": ["not_real"]},
    )
    assert response.status_code == 422


def test_text_sanitize_redacts_secrets() -> None:
    response = client.post(
        "/api/v1/tools/text-sanitize",
        json={"text": "api_key=supersecretvalue123456"},
    )
    assert response.status_code == 200
    assert "REDACTED" in response.json()["sanitized"]


def test_text_compare_similarity() -> None:
    response = client.post(
        "/api/v1/tools/text-compare",
        json={"left": "hello world", "right": "hello world"},
    )
    assert response.status_code == 200
    assert response.json()["similarity"] == 1.0
