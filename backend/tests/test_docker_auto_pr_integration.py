from __future__ import annotations

import httpx
import pytest
from urllib.parse import unquote

from services.auto_pr_service import AutoPRService


@pytest.mark.asyncio
async def test_open_dockerfile_remediation_pr_mocks_github_branch_and_pr_calls() -> None:
    calls: list[tuple[str, str]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append((request.method, f"{path}?{request.url.query.decode()}" if request.url.query else path))

        if request.method == "GET" and path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "base-sha"}}, request=request)

        if request.method == "POST" and path.endswith("/git/refs"):
            return httpx.Response(201, json={"ref": "ok"}, request=request)

        if request.method == "GET" and path.endswith("/contents/Dockerfile"):
            return httpx.Response(200, json={"sha": "file-sha"}, request=request)

        if request.method == "PUT" and path.endswith("/contents/Dockerfile"):
            payload = request.read().decode("utf-8")
            assert "optimized_dockerfile" not in payload
            return httpx.Response(200, json={"commit": {"sha": "commit-sha"}}, request=request)

        if request.method == "POST" and path.endswith("/pulls"):
            return httpx.Response(201, json={"number": 77}, request=request)

        return httpx.Response(404, json={"message": "unexpected request"}, request=request)

    service = AutoPRService(
        github_token="token-123",
        repo_full_name="owner/repo",
        clone_url="",
        base_branch="main",
    )
    service.client = httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(_handler),
        headers={
            "Authorization": "token token-123",
            "Accept": "application/vnd.github.v3+json",
        },
    )

    result = await service.open_dockerfile_remediation_pr(
        analysis_result={
            "dockerfile_issues": [
                {
                    "line": 3,
                    "issue_type": "security",
                    "severity": "critical",
                    "description": "Base image is outdated",
                }
            ],
            "optimized_dockerfile": "FROM python:3.12-slim\nWORKDIR /app\n",
            "summary": "Use supported base image",
        },
        target_file_path="Dockerfile",
        run_id="run-abcdef123",
    )

    await service.close()

    assert result["queued"] is True
    assert result["pr_number"] == 77
    assert result["branch_name"].startswith("orion/dockerfile-fixes-")
    assert service.created_branches == [result["branch_name"]]

    methods_and_paths = [
        "GET /repos/owner/repo/git/ref/heads/main",
        "POST /repos/owner/repo/git/refs",
        "GET /repos/owner/repo/contents/Dockerfile?ref=" + result["branch_name"],
        "PUT /repos/owner/repo/contents/Dockerfile",
        "POST /repos/owner/repo/pulls",
    ]
    observed = [f"{method} {unquote(path)}" for method, path in calls]
    for expected in methods_and_paths:
        assert expected in observed
