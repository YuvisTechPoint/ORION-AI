from typing import Any
from urllib.parse import quote

import httpx

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("github_service")


class GitHubService:
    def __init__(self, token: str | None = None) -> None:
        raw = token if token is not None else (settings.github_token if settings.github_enabled else "")
        self.token = (raw or "").strip()
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = self.token
        if not token:
            return headers
        if token.startswith(("gho_", "github_pat_")):
            headers["Authorization"] = f"Bearer {token}"
        else:
            headers["Authorization"] = f"token {token}"
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url="https://api.github.com", timeout=60.0, headers=self._headers()
            )
        return self._client

    async def set_commit_status(
        self,
        repo_full_name: str,
        commit_sha: str,
        state: str,
        description: str,
        context: str = "ai-cicd-pipeline/pipeline",
    ) -> dict[str, Any]:
        if state not in ("pending", "success", "failure", "error"):
            raise ValueError(f"invalid commit status state: {state}")
        client = await self._get_client()
        r = await client.post(
            f"/repos/{repo_full_name}/statuses/{commit_sha}",
            json={"state": state, "description": description[:140], "context": context},
        )
        r.raise_for_status()
        return r.json()

    async def safe_commit_status(
        self, repo_full_name: str, commit_sha: str, state: str, description: str
    ) -> None:
        """Best-effort status update: GitHub outages must never fail the pipeline."""
        if not self.enabled:
            return
        try:
            await self.set_commit_status(repo_full_name, commit_sha, state, description)
        except Exception as exc:
            logger.warning("commit status %s for %s failed: %s", state, commit_sha[:8], exc)

    async def create_check_run(
        self,
        repo_full_name: str,
        commit_sha: str,
        name: str,
        status: str,
        conclusion: str | None = None,
        output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = await self._get_client()
        body: dict[str, Any] = {"name": name, "head_sha": commit_sha, "status": status}
        if conclusion is not None:
            body["conclusion"] = conclusion
        if output is not None:
            body["output"] = output
        r = await client.post(f"/repos/{repo_full_name}/check-runs", json=body)
        r.raise_for_status()
        return r.json()

    async def delete_branch(self, repo_full_name: str, branch_name: str) -> bool:
        """Delete a branch; returns False if it no longer exists (404)."""
        client = await self._get_client()
        r = await client.delete(f"/repos/{repo_full_name}/git/refs/heads/{quote(branch_name, safe='/')}")
        if r.status_code in (404, 422):
            logger.info("branch %s already gone in %s", branch_name, repo_full_name)
            return False
        r.raise_for_status()
        logger.info("deleted branch %s in %s", branch_name, repo_full_name)
        return True

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def find_pull_requests_for_commit(self, repo_full_name: str, commit_sha: str) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        client = await self._get_client()
        r = await client.get(f"/repos/{repo_full_name}/commits/{commit_sha}/pulls")
        if r.status_code >= 400:
            return []
        data = r.json()
        return data if isinstance(data, list) else []

    async def create_issue_comment(self, repo_full_name: str, issue_number: int, body: str) -> dict[str, Any]:
        client = await self._get_client()
        r = await client.post(
            f"/repos/{repo_full_name}/issues/{issue_number}/comments",
            json={"body": body[:65536]},
        )
        r.raise_for_status()
        return r.json()

    async def create_commit_comment(
        self, repo_full_name: str, commit_sha: str, body: str
    ) -> dict[str, Any]:
        client = await self._get_client()
        r = await client.post(
            f"/repos/{repo_full_name}/commits/{commit_sha}/comments",
            json={"body": body[:65536]},
        )
        r.raise_for_status()
        return r.json()


github_service = GitHubService()
