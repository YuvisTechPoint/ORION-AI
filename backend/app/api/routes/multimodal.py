from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import List

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.config import settings
from app.api.routes.auth import require_auth
from app.agents.multimodal.git_log_agent import GitLogAgent
from app.agents.multimodal.payment_agent import PaymentAgent

router = APIRouter(prefix="/multimodal", tags=["Multimodal Analysis"])


def _detect_gh_executable() -> str | None:
    for env_key in ("ORION_GH_PATH", "GH_PATH"):
        candidate = (os.getenv(env_key) or "").strip()
        if candidate and Path(candidate).exists():
            return candidate

    which_value = shutil.which("gh")
    if which_value:
        return which_value

    windows_candidates = [
        Path(os.getenv("ProgramFiles", "")) / "GitHub CLI" / "gh.exe",
        Path(os.getenv("ProgramFiles(x86)", "")) / "GitHub CLI" / "gh.exe",
        Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "GitHub CLI" / "gh.exe",
    ]
    for candidate in windows_candidates:
        if str(candidate) and candidate.exists():
            return str(candidate)

    return None


async def _run_gh_command(args: list[str], context: str) -> str:
    gh_executable = _detect_gh_executable()
    if not gh_executable:
        raise HTTPException(status_code=400, detail="GitHub CLI is not installed on the backend host")

    cmd = [gh_executable, *args]

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            cmd,
            text=True,
            capture_output=True,
            check=False,
        )

    result = await asyncio.to_thread(_run)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise HTTPException(status_code=400, detail=f"{context}: {detail}")
    return result.stdout or ""


def _format_commit_rows(commits: list[dict], repo_full_name: str) -> str:
    lines = [f"repo={repo_full_name}", "source=gh_cli_commits", ""]
    for commit in commits:
        sha = str(commit.get("sha", ""))
        commit_data = commit.get("commit", {}) if isinstance(commit.get("commit"), dict) else {}
        author_data = commit_data.get("author", {}) if isinstance(commit_data.get("author"), dict) else {}
        message = str(commit_data.get("message", "")).strip()
        authored_at = str(author_data.get("date", ""))
        author_name = str(author_data.get("name", "unknown"))
        lines.append(f"- sha={sha}")
        lines.append(f"  author={author_name}")
        lines.append(f"  date={authored_at}")
        lines.append(f"  message={message}")
    return "\n".join(lines).strip() + "\n"


async def _collect_gh_cli_logs(
    repo_full_name: str,
    pr_number: int | None,
    commit_sha: str,
    branch: str,
    log_limit: int,
) -> str:
    await _run_gh_command(["auth", "status", "--hostname", "github.com"], "GitHub CLI is not authenticated")
    await _run_gh_command(["repo", "view", repo_full_name], f"GitHub CLI cannot access repository {repo_full_name}")

    parts: list[str] = [f"repo={repo_full_name}", "source=gh_cli", ""]

    if pr_number is not None:
        pr_json = await _run_gh_command(
            [
                "pr",
                "view",
                str(pr_number),
                "--repo",
                repo_full_name,
                "--json",
                "number,title,body,headRefName,baseRefName,author,state,commits",
            ],
            f"Failed to fetch PR #{pr_number}",
        )
        pr_data = json.loads(pr_json or "{}")
        parts.append(f"pr_number={pr_data.get('number', pr_number)}")
        parts.append(f"pr_title={pr_data.get('title', '')}")
        parts.append(f"pr_state={pr_data.get('state', '')}")
        parts.append(f"head_ref={pr_data.get('headRefName', '')}")
        parts.append(f"base_ref={pr_data.get('baseRefName', '')}")
        author = pr_data.get("author", {}) if isinstance(pr_data.get("author"), dict) else {}
        parts.append(f"author={author.get('login', 'unknown')}")
        parts.append("")
        commits = pr_data.get("commits", []) if isinstance(pr_data.get("commits"), list) else []
        for commit in commits:
            if not isinstance(commit, dict):
                continue
            parts.append(f"- sha={commit.get('oid', '')}")
            parts.append(f"  message={commit.get('messageHeadline', '')}")
            parts.append(f"  authored_at={commit.get('authoredDate', '')}")
        parts.append("")

    if commit_sha:
        commit_json = await _run_gh_command(
            ["api", f"repos/{repo_full_name}/commits/{commit_sha}"],
            f"Failed to fetch commit {commit_sha}",
        )
        commit_payload = json.loads(commit_json or "{}")
        commit_block = _format_commit_rows([commit_payload], repo_full_name)
        parts.append("single_commit_details=")
        parts.append(commit_block)

    if branch:
        branch_json = await _run_gh_command(
            ["api", f"repos/{repo_full_name}/commits?sha={branch}&per_page={log_limit}"],
            f"Failed to fetch commits for branch {branch}",
        )
    else:
        branch_json = await _run_gh_command(
            ["api", f"repos/{repo_full_name}/commits?per_page={log_limit}"],
            "Failed to fetch recent commits",
        )

    branch_commits = json.loads(branch_json or "[]")
    if isinstance(branch_commits, list):
        parts.append(f"recent_commits_limit={log_limit}")
        parts.append(_format_commit_rows(branch_commits, repo_full_name))

    return "\n".join(parts).strip() + "\n"


def _detect_artifact_type(filename: str, content_type: str) -> str:
    name = filename.lower()
    ctype = (content_type or "").lower()

    if ctype in {"image/png", "image/jpeg", "image/jpg"}:
        return "image"
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".csv") or ctype in {"text/csv", "application/csv"}:
        return "csv"
    if name.endswith(".log") or name.endswith(".txt"):
        return "log"
    return "text"


@router.post("/git-logs")
async def analyze_git_logs(
    request: Request,
    files: List[UploadFile] = File(default=[]),
    text_input: str = Form(default=""),
    use_gh_cli: bool = Form(default=False),
    repo_full_name: str = Form(default=""),
    pr_number: int | None = Form(default=None),
    commit_sha: str = Form(default=""),
    branch: str = Form(default="main"),
    log_limit: int = Form(default=30),
    user: dict = Depends(require_auth),
) -> dict:
    # Read uploaded files into artifacts
    artifacts: list[dict] = []
    for file in files:
        filename = file.filename or "uploaded_file"
        content_type = file.content_type or "application/octet-stream"
        raw = await file.read()
        artifact_type = _detect_artifact_type(filename, content_type)
        artifacts.append(
            {
                "type": artifact_type,
                "content": raw,
                "filename": filename,
                "mime_type": content_type,
            }
        )

    if text_input:
        artifacts.append(
            {
                "type": "text",
                "content": text_input,
                "filename": "user_input.txt",
                "mime_type": "text/plain",
            }
        )

    if use_gh_cli:
        repo = repo_full_name.strip()
        if not repo:
            raise HTTPException(status_code=400, detail="repo_full_name is required when use_gh_cli=true")

        safe_limit = max(1, min(log_limit, 100))
        gh_log_text = await _collect_gh_cli_logs(
            repo_full_name=repo,
            pr_number=pr_number,
            commit_sha=commit_sha.strip(),
            branch=branch.strip(),
            log_limit=safe_limit,
        )
        artifacts.append(
            {
                "type": "text",
                "content": gh_log_text,
                "filename": "gh_cli_git_logs.txt",
                "mime_type": "text/plain",
            }
        )

    if not artifacts:
        raise HTTPException(status_code=400, detail="Provide at least one log file or paste log text")

    provider = (settings.llm_provider or "openai").strip().lower()
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key) if provider != "huggingface" else None
    agent = GitLogAgent(anthropic_client=anthropic_client, artifacts=artifacts)
    result = await agent.execute()

    analyzed_by = user.get("username") or user.get("github_username") or "unknown"

    return {
        "status": "success",
        "agent": "git_log_analysis",
        "analyzed_by": analyzed_by,
        "result": result,
    }


@router.post("/payment")
async def analyze_payment(
    request: Request,
    files: List[UploadFile] = File(default=[]),
    text_input: str = Form(default=""),
    user: dict = Depends(require_auth),
) -> dict:
    artifacts: list[dict] = []
    for file in files:
        filename = file.filename or "uploaded_file"
        content_type = file.content_type or "application/octet-stream"
        raw = await file.read()

        name_lower = filename.lower()
        ctype_lower = content_type.lower()

        if name_lower.endswith(".csv") or ctype_lower in {"text/csv", "application/csv"}:
            artifact_type = "csv"
        elif name_lower.endswith(".pdf") or ctype_lower == "application/pdf":
            artifact_type = "pdf"
        elif ctype_lower in {"image/png", "image/jpeg", "image/jpg"}:
            artifact_type = "image"
        elif name_lower.endswith(".json") or ctype_lower == "application/json":
            artifact_type = "text"
        else:
            artifact_type = "text"

        artifacts.append(
            {
                "type": artifact_type,
                "content": raw,
                "filename": filename,
                "mime_type": content_type,
            }
        )

    if text_input:
        artifacts.append(
            {
                "type": "text",
                "content": text_input,
                "filename": "user_input.txt",
                "mime_type": "text/plain",
            }
        )

    if not artifacts:
        raise HTTPException(status_code=400, detail="Provide at least one log file or paste log text")

    provider = (settings.llm_provider or "openai").strip().lower()
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key) if provider != "huggingface" else None
    agent = PaymentAgent(anthropic_client=anthropic_client, artifacts=artifacts)
    result = await agent.execute()

    analyzed_by = user.get("username") or user.get("github_username") or "unknown"

    return {
        "status": "success",
        "agent": "payment_analysis",
        "analyzed_by": analyzed_by,
        "result": result,
    }
