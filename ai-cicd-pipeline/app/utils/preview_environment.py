"""Ephemeral preview environment metadata for PR branches."""

from __future__ import annotations

from typing import Any

from app.config import settings


def build_preview_environment(
    *,
    run_id: str,
    branch: str,
    pr_number: int | None = None,
    simulated: bool = True,
) -> dict[str, Any]:
    slug = f"pr-{pr_number}" if pr_number else branch.replace("/", "-")[:40]
    url = settings.preview_base_url.format(pr=slug, run=run_id[:8], branch=slug)

    return {
        "preview_url": url,
        "branch": branch,
        "pr_number": pr_number,
        "simulated": simulated,
        "lifecycle": "ephemeral",
        "summary": f"Preview environment {'simulated' if simulated else 'deployed'} at {url}",
    }
