"""OPA policy adapter tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.utils.opa_adapter import evaluate_policies_opa, opa_available


def test_opa_available_when_url_set(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "opa_url", "http://127.0.0.1:8181")
    assert opa_available() is True


def test_opa_returns_none_without_url(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "opa_url", "")
    assert evaluate_policies_opa({}) is None


def test_opa_pass_response(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "opa_url", "http://127.0.0.1:8181")
    monkeypatch.setattr(settings, "opa_policy_package", "orion/pipeline")
    monkeypatch.setattr(settings, "opa_timeout_seconds", 2.0)
    monkeypatch.setattr(settings, "opa_fail_closed", True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"result": {"allow": True, "violations": []}}

    with patch("app.utils.opa_adapter.httpx.Client") as client_cls:
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.return_value = mock_resp
        client_cls.return_value = client

        result = evaluate_policies_opa({"security_scan": {"highest_severity": "low"}})

    assert result is not None
    assert result["passed"] is True
    assert result["engine"] == "opa"
