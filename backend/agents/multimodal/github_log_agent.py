from __future__ import annotations

import io
import zipfile
from typing import Any

import httpx

from agents.multimodal.base_multimodal_agent import BaseMultimodalAgent


class GitHubLogAgent(BaseMultimodalAgent):
    def __init__(self, llm_client: Any, artifacts: list[dict[str, Any]]) -> None:
        super().__init__(llm_client=llm_client, name="github_log_multimodal", artifacts=artifacts)

    def _expand_zip_artifacts(self) -> None:
        expanded: list[dict[str, Any]] = []
        for artifact in self.artifacts:
            expanded.append(artifact)
            mime_type = str(artifact.get("mime_type", ""))
            if mime_type != "application/zip":
                continue

            raw_content = artifact.get("content", b"")
            if isinstance(raw_content, str):
                raw_bytes = raw_content.encode("utf-8", errors="ignore")
            elif isinstance(raw_content, (bytes, bytearray)):
                raw_bytes = bytes(raw_content)
            else:
                raw_bytes = b""

            try:
                with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
                    for name in archive.namelist():
                        if not name.lower().endswith(".txt"):
                            continue
                        with archive.open(name) as member:
                            text_content = member.read().decode("utf-8", errors="ignore")
                        expanded.append(
                            {
                                "type": "text",
                                "content": text_content,
                                "filename": name,
                                "mime_type": "text/plain",
                            }
                        )
            except zipfile.BadZipFile:
                continue

        self.artifacts = expanded

    def execute(self) -> dict[str, Any]:
        self._expand_zip_artifacts()
        system_prompt = (
            "You are a GitHub Actions expert. Analyze the provided CI/CD workflow log files. "
            "Identify failed steps, error messages, flaky tests, network failures, rate limit hits, and authentication errors. "
            "Return ONLY valid JSON: "
            "{\"workflow_name\": string, \"failed_steps\": [{\"step_name\": string, \"error_type\": \"build\"|\"test\"|\"network\"|\"auth\"|\"rate_limit\"|\"timeout\"|\"unknown\", \"error_message\": string, \"line_number\": int, \"fix\": string}], "
            "\"total_duration_seconds\": int, \"slowest_steps\": [{\"step\": string, \"duration_seconds\": int}], "
            "\"flaky_indicators\": [string], \"annotations\": [string], \"can_be_retried\": bool, "
            "\"retry_strategy\": string, \"root_cause\": string, \"summary\": string}"
        )
        text_prompt = "Analyze uploaded GitHub Actions logs and return exactly the requested JSON schema."
        raw, _ = self._call_claude_multimodal(system_prompt=system_prompt, text_prompt=text_prompt, max_tokens=3000)
        return self._parse_json(raw)

    async def fetch_run_logs(self, repo_full_name: str, run_id: int, github_token: str) -> bytes:
        url = f"https://api.github.com/repos/{repo_full_name}/actions/runs/{run_id}/logs"
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github+json",
        }
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.content
