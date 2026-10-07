"""GitHub commit statuses and Slack alerts for devops-platform pipelines."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def parse_repo_full_name(repo_url: str) -> str | None:
    url = (repo_url or "").strip().rstrip("/")
    if not url:
        return None
    if url.startswith("git@"):
        part = url.split(":", 1)[-1].removesuffix(".git")
        return part if "/" in part else None
    parsed = urlparse(url if "://" in url else f"https://{url}")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parsed.netloc.endswith("github.com"):
        return f"{parts[0]}/{parts[1].removesuffix('.git')}"
    return None


def set_commit_status(
    repo_full_name: str | None,
    commit_sha: str | None,
    state: str,
    description: str,
    *,
    context: str = "orion-devops-platform/pipeline",
) -> None:
    settings = get_settings()
    token = (settings.github_token or "").strip()
    if not token or not repo_full_name or not commit_sha:
        return
    if state not in {"pending", "success", "failure", "error"}:
        return
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(
                f"https://api.github.com/repos/{repo_full_name}/statuses/{commit_sha}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                json={"state": state, "description": description[:140], "context": context},
            )
            r.raise_for_status()
    except Exception as exc:
        logger.warning("GitHub commit status failed: %s", exc)


def slack_notify(text: str, fields: dict[str, Any] | None = None) -> None:
    settings = get_settings()
    webhook = (getattr(settings, "slack_webhook_url", "") or "").strip()
    if not webhook:
        return
    payload: dict[str, Any] = {"text": text[:3500]}
    if fields:
        payload["fields"] = fields
    try:
        with httpx.Client(timeout=15.0) as client:
            client.post(webhook, json=payload)
    except Exception as exc:
        logger.warning("Slack notification failed: %s", exc)


def record_auto_pr_registry(metadata: dict[str, Any], *, reason: str, stage: str) -> dict[str, Any]:
    """Persist Auto-PR intent when blocked; full Auto-PR runs on ORION/canonical stacks."""
    meta = dict(metadata)
    meta["auto_pr_registry"] = {
        "branches": [],
        "reason": reason,
        "blocked_stage": stage,
        "delegate": "Use ORION CI/CD or canonical console for LLM Auto-PR generation",
    }
    return meta
