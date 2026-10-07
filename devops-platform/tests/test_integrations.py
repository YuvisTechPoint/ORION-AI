"""Integration helpers for GitHub statuses and Slack."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.integrations import parse_repo_full_name, record_auto_pr_registry, set_commit_status, slack_notify


def test_parse_repo_full_name() -> None:
    assert parse_repo_full_name("https://github.com/octocat/Hello-World") == "octocat/Hello-World"
    assert parse_repo_full_name("git@github.com:octocat/Hello-World.git") == "octocat/Hello-World"


def test_record_auto_pr_registry() -> None:
    meta = record_auto_pr_registry({}, reason="blocked", stage="security")
    assert meta["auto_pr_registry"]["blocked_stage"] == "security"


@patch("app.services.integrations.httpx.Client")
def test_set_commit_status_noop_without_token(mock_client: MagicMock, monkeypatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "github_token", "")
    set_commit_status("octocat/Hello-World", "abc123", "pending", "running")
    mock_client.assert_not_called()


@patch("app.services.integrations.httpx.Client")
def test_slack_notify_noop_without_webhook(mock_client: MagicMock, monkeypatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "slack_webhook_url", "")
    slack_notify("hello")
    mock_client.assert_not_called()
