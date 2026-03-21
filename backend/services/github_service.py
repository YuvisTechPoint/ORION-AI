from __future__ import annotations

import httpx

from core.config import get_settings
from core.logging_config import get_logger

logger = get_logger("github_service")


class GitHubService:
    def __init__(self, github_token: str | None = None) -> None:
        settings = get_settings()
        self.github_token = github_token or settings.github_token or ""
        self.client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def delete_branch(self, repo_full_name: str, branch_name: str) -> bool:
        response = await self.client.delete(f"/repos/{repo_full_name}/git/refs/heads/{branch_name}")
        if response.status_code == 404:
            logger.info("Branch already deleted: %s/%s", repo_full_name, branch_name)
            return False
        response.raise_for_status()
        return True
