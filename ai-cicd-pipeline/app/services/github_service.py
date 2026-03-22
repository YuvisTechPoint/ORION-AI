from typing import Any
from urllib.parse import quote

import httpx

from app.config import settings


class GitHubService:
    def __init__(self, token: str | None = None) -> None:
        self.token = token or settings.github_token
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0, headers=self._headers())
        return self._client

    async def set_commit_status(
        self,
        repo_full_name: str,
        commit_sha: str,
        state: str,
        description: str,
        context: str = "ai-cicd-pipeline/pipeline",
    ) -> dict[str, Any]:
        client = await self._get_client()
        url = f"https://api.github.com/repos/{repo_full_name}/statuses/{commit_sha}"
        payload = {"state": state, "description": description, "context": context}
        r = await client.post(url, json=payload)
        r.raise_for_status()
        return r.json()

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
        url = f"https://api.github.com/repos/{repo_full_name}/check-runs"
        body: dict[str, Any] = {
            "name": name,
            "head_sha": commit_sha,
            "status": status,
        }
        if conclusion is not None:
            body["conclusion"] = conclusion
        if output is not None:
            body["output"] = output
        r = await client.post(url, json=body)
        r.raise_for_status()
        return r.json()

    async def delete_branch(self, repo_full_name: str, branch_name: str) -> None:
        client = await self._get_client()
        enc = quote(branch_name, safe="")
        url = f"https://api.github.com/repos/{repo_full_name}/git/refs/heads/{enc}"
        r = await client.delete(url)
        if r.status_code == 404:
            return
        r.raise_for_status()

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


github_service = GitHubService()
