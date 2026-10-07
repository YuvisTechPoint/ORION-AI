"""Start a canonical pipeline from a GitHub push webhook (archive download)."""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import httpx

from core.config import Settings
from core.zip_utils import UnsafeZipError, safe_extract_zip
from models.schemas import SubmitCodeRequest
from services.orchestrator import Orchestrator


async def start_github_push_pipeline(
    orchestrator: Orchestrator,
    settings: Settings,
    *,
    repo_full_name: str,
    branch: str,
    github_token: str | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, str]:
    owner, repo_name = repo_full_name.split("/", 1)
    token = (github_token or settings.github_token or "").strip()
    headers = {"User-Agent": "devops-agent/0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
        zip_url = f"https://api.github.com/repos/{owner}/{repo_name}/zipball/{branch}"
        resp = await client.get(zip_url, timeout=30.0)
        if resp.status_code != 200:
            raise ValueError(f"Failed to download repo archive: HTTP {resp.status_code}")

    if len(resp.content) > 50 * 1024 * 1024:
        raise ValueError("Downloaded archive exceeds 50 MB limit")

    with tempfile.TemporaryDirectory(prefix="github_push_") as tmpdir:
        tmp = Path(tmpdir)
        archive_path = tmp / "repo.zip"
        archive_path.write_bytes(resp.content)
        try:
            safe_extract_zip(archive_path, tmp)
        except (zipfile.BadZipFile, UnsafeZipError) as exc:
            raise ValueError(f"Invalid or unsafe zip archive: {exc}") from exc

        repo_files: dict[str, str] = {}
        primary_code = ""
        for path in tmp.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(tmp).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            repo_files[rel] = text
            if not primary_code and rel.endswith(".py"):
                primary_code = text

        request = SubmitCodeRequest(
            repo_name=repo_name,
            code=primary_code,
            diff="",
            config_text="",
            repo_files=repo_files,
            repo_full_name=repo_full_name,
            clone_url=f"https://github.com/{repo_full_name}.git",
            branch=branch,
        )
        state = await orchestrator.submit_code(
            request,
            github_token=token or None,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

    return {
        "pipeline_id": state.pipeline_id,
        "status": state.status,
        "current_stage": state.current_stage,
        "correlation_id": state.correlation_id,
    }
