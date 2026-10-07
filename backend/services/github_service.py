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

    @property
    def enabled(self) -> bool:
        return bool(self.github_token.strip())

    @staticmethod
    def parse_repo_full_name(repo_url: str) -> str | None:
        url = (repo_url or "").strip().rstrip("/")
        if not url:
            return None
        if url.startswith("git@"):
            # git@github.com:owner/repo.git
            part = url.split(":", 1)[-1].removesuffix(".git")
            return part if "/" in part else None
        if "github.com" in url:
            path = url.split("github.com/", 1)[-1].split("/")
            if len(path) >= 2:
                return f"{path[0]}/{path[1].removesuffix('.git')}"
        return None

    async def set_commit_status(
        self,
        repo_full_name: str,
        commit_sha: str,
        state: str,
        description: str,
        context: str = "orion-canonical/pipeline",
    ) -> None:
        if state not in {"pending", "success", "failure", "error"}:
            raise ValueError(f"invalid commit status state: {state}")
        r = await self.client.post(
            f"/repos/{repo_full_name}/statuses/{commit_sha}",
            json={"state": state, "description": description[:140], "context": context},
        )
        r.raise_for_status()

    async def safe_commit_status(
        self,
        repo_full_name: str | None,
        commit_sha: str | None,
        state: str,
        description: str,
    ) -> None:
        if not self.enabled or not repo_full_name or not commit_sha:
            return
        try:
            await self.set_commit_status(repo_full_name, commit_sha, state, description)
        except Exception as exc:
            logger.warning("commit status %s failed: %s", state, exc)

    async def close(self) -> None:
        await self.client.aclose()

    async def delete_branch(self, repo_full_name: str, branch_name: str) -> bool:
        response = await self.client.delete(f"/repos/{repo_full_name}/git/refs/heads/{branch_name}")
        if response.status_code == 404:
            logger.info("Branch already deleted: %s/%s", repo_full_name, branch_name)
            return False
        response.raise_for_status()
        return True
