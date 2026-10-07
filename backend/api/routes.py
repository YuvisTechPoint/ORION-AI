import asyncio
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi import File, UploadFile, Form, Query
from fastapi import Request
import hashlib
import hmac
import zipfile
import tempfile
from pathlib import Path
from starlette.websockets import WebSocketState
from starlette.responses import JSONResponse
import httpx
import re

from agents.multimodal.github_log_agent import GitHubLogAgent
from agents.multimodal.payment_agent import PaymentAgent
from core.config import Settings, get_settings
from core.llm_client import LLMClient
from core.zip_utils import UnsafeZipError, safe_extract_zip
from models.schemas import (
    AnalyzeLogsRequest,
    HealthResponse,
    MonitoringResult,
    PipelineState,
    RuntimeConfigResponse,
    SubmitCodeRequest,
    SubmitCodeResponse,
    TriggerDeploymentRequest,
    PipelineListItem,
)
from services.orchestrator import Orchestrator
from services.auth import AuthService
from api.auth import optional_pipeline_auth
from services.preflight import preflight_report
from services.github_service import GitHubService
from services.github_push_pipeline import start_github_push_pipeline
from core.db import SessionLocal
from services.webhook_ledger import find_delivery, record_delivery

router = APIRouter()
LOGGER = logging.getLogger(__name__)
_ORCHESTRATOR: Orchestrator | None = None
_BACKGROUND_PIPELINE_TASKS: set[asyncio.Task] = set()


def _detect_payment_integration(repo_files: dict[str, str]) -> bool:
    payment_markers = [
        "stripe",
        "razorpay",
        "paypal",
        "paytm",
        "braintree",
        "square",
        "checkout",
        "payment",
        "transaction",
        "billing",
        "invoice",
    ]
    for rel_path, content in repo_files.items():
        haystack = f"{rel_path}\n{content}".lower()
        if any(marker in haystack for marker in payment_markers):
            return True
    return False


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


def _extract_issue_lines(text: str, limit: int = 20) -> list[str]:
    lines = [line.strip() for line in (text or "").splitlines()]
    markers = ("error", "failed", "failure", "fatal", "traceback", "exception")
    selected: list[str] = []
    for line in lines:
        if any(marker in line.lower() for marker in markers):
            selected.append(line)
        if len(selected) >= limit:
            break
    return selected


def _build_multimodal_mode_result(mode: str, content: str, metadata: dict[str, str] | None = None) -> dict:
    issues = _extract_issue_lines(content)
    severity = "high" if issues else "low"
    return {
        "mode": mode,
        "issues_found": len(issues),
        "severity": severity,
        "issues": issues,
        "summary": f"{mode} analyzer found {len(issues)} potential issue lines",
        "metadata": metadata or {},
    }


def _extract_multimodal_structured_issues(agent_result: dict[str, object]) -> list[str]:
    issues: list[str] = []

    failed_steps = agent_result.get("failed_steps", [])
    if isinstance(failed_steps, list):
        for step in failed_steps:
            if isinstance(step, dict):
                msg = str(step.get("error_message", "")).strip()
                if msg:
                    issues.append(msg)

    error_patterns = agent_result.get("error_patterns", [])
    if isinstance(error_patterns, list):
        for pattern in error_patterns:
            if isinstance(pattern, dict):
                msg = str(pattern.get("pattern", "")).strip()
                if msg:
                    issues.append(msg)

    webhook_failures = agent_result.get("webhook_failures", [])
    if isinstance(webhook_failures, list):
        for failure in webhook_failures:
            if isinstance(failure, dict):
                msg = str(failure.get("failure_reason", "")).strip()
                if msg:
                    issues.append(msg)

    build_errors = agent_result.get("build_errors", [])
    if isinstance(build_errors, list):
        for error in build_errors:
            if isinstance(error, dict):
                msg = str(error.get("error_message", "")).strip()
                if msg:
                    issues.append(msg)

    anomaly_list = agent_result.get("anomalies", [])
    if isinstance(anomaly_list, list):
        for anomaly in anomaly_list:
            msg = str(anomaly).strip()
            if msg:
                issues.append(msg)

    return issues[:20]


def _build_multimodal_result_from_agent(
    mode: str,
    agent_result: dict[str, object],
    metadata: dict[str, str] | None = None,
) -> dict:
    issues = _extract_multimodal_structured_issues(agent_result)
    raw_severity = str(agent_result.get("severity", "")).lower()
    severity = raw_severity if raw_severity in {"low", "medium", "high", "critical"} else ("high" if issues else "low")
    summary = str(agent_result.get("summary", "")).strip() or f"{mode} analyzer completed"
    return {
        "mode": mode,
        "issues_found": len(issues),
        "severity": severity,
        "issues": issues,
        "summary": summary,
        "metadata": metadata or {},
        "agent_result": agent_result,
    }


async def _run_submit_multimodal_modes(
    selected_modes: list[str],
    multimodal_text: str,
    repo_files: dict[str, str],
    repo_full_name: str,
    selected_branch: str,
    settings: Settings,
) -> tuple[list[dict], list[dict]]:
    multimodal_inputs: list[dict] = []
    multimodal_results: list[dict] = []
    timeout = max(5, int(settings.multimodal_timeout_seconds))
    llm_client = LLMClient(settings)

    for mode in selected_modes:
        if mode in {"git_logs", "github", "github_actions", "github_log"}:
            logs = multimodal_text
            metadata: dict[str, str] = {"source": "pasted"}
            if not logs.strip():
                try:
                    logs, metadata = await asyncio.wait_for(
                        _fetch_github_workflow_logs_via_gh(repo_full_name, selected_branch),
                        timeout=timeout,
                    )
                except Exception as exc:  # noqa: BLE001
                    logs = f"git log fetch failed: {exc}"
                    metadata = {"source": "error"}
            artifacts = [
                {
                    "type": "log",
                    "content": logs,
                    "filename": "git_logs.txt",
                    "mime_type": "text/plain",
                }
            ]
            agent = GitHubLogAgent(llm_client=llm_client, artifacts=artifacts)

            def _run_git() -> dict:
                return agent.execute()

            try:
                agent_result = await asyncio.wait_for(asyncio.to_thread(_run_git), timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                agent_result = {"summary": f"git log analysis failed: {exc}", "severity": "medium"}
            multimodal_inputs.append({"modality": "log", "content": logs[:8000], "name": "git_logs"})
            multimodal_results.append(_build_multimodal_result_from_agent("git_logs", agent_result, metadata))

        elif mode == "payment":
            if not _detect_payment_integration(repo_files) and not multimodal_text.strip():
                raise HTTPException(
                    status_code=400,
                    detail="Selected Payment Analyzer, but this repository does not appear to have payment integration.",
                )
            combined = multimodal_text or "\n".join(list(repo_files.values())[:5])[:20000]
            artifacts = [
                {
                    "type": "text",
                    "content": combined,
                    "filename": "payment_context.txt",
                    "mime_type": "text/plain",
                }
            ]
            agent = PaymentAgent(llm_client=llm_client, artifacts=artifacts)

            def _run_pay() -> dict:
                return agent.execute()

            try:
                agent_result = await asyncio.wait_for(asyncio.to_thread(_run_pay), timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                agent_result = {"summary": f"payment analysis failed: {exc}", "severity": "medium"}
            multimodal_inputs.append({"modality": "log", "content": combined[:8000], "name": "payment"})
            multimodal_results.append(_build_multimodal_result_from_agent("payment", agent_result, {}))

    return multimodal_inputs, multimodal_results


async def _fetch_github_workflow_logs_via_gh(repo_full_name: str, branch: str, limit: int = 1) -> tuple[str, dict[str, str]]:
    await _run_gh_command(["auth", "status", "--hostname", "github.com"], "GitHub CLI is not authenticated")

    branch_name = branch.strip() or "main"
    list_output = await _run_gh_command(
        [
            "run",
            "list",
            "--repo",
            repo_full_name,
            "--branch",
            branch_name,
            "--limit",
            str(max(1, min(limit, 10))),
            "--json",
            "databaseId,displayTitle,workflowName,status,conclusion,headBranch,url,createdAt",
        ],
        f"Failed listing workflow runs for {repo_full_name}",
    )
    runs = json.loads(list_output or "[]")
    if not isinstance(runs, list):
        runs = []

    # Fallback: some repos only have runs on PR refs or a different default branch.
    # In that case, use the latest repo-level run instead of failing submit.
    source_scope = f"branch:{branch_name}"
    if not runs:
        fallback_output = await _run_gh_command(
            [
                "run",
                "list",
                "--repo",
                repo_full_name,
                "--limit",
                str(max(1, min(limit, 10))),
                "--json",
                "databaseId,displayTitle,workflowName,status,conclusion,headBranch,url,createdAt",
            ],
            f"Failed listing fallback workflow runs for {repo_full_name}",
        )
        fallback_runs = json.loads(fallback_output or "[]")
        if isinstance(fallback_runs, list) and fallback_runs:
            runs = fallback_runs
            source_scope = "repo:latest"

    if not runs:
        soft_log = (
            f"No GitHub Actions workflow runs found for {repo_full_name}. "
            f"Checked branch={branch_name} and repo-level recent runs. "
            "Proceeding without workflow log context.\n"
        )
        return soft_log, {
            "repo_full_name": repo_full_name,
            "branch": branch_name,
            "run_id": "",
            "status": "not_found",
            "conclusion": "",
            "workflow": "",
            "url": "",
            "source_scope": source_scope,
        }

    latest = runs[0] if isinstance(runs[0], dict) else {}
    run_id = latest.get("databaseId")
    if not run_id:
        soft_log = (
            f"GitHub Actions run metadata was present but missing databaseId for {repo_full_name}. "
            "Proceeding without workflow log context.\n"
        )
        return soft_log, {
            "repo_full_name": repo_full_name,
            "branch": branch_name,
            "run_id": "",
            "status": "invalid_run_metadata",
            "conclusion": "",
            "workflow": "",
            "url": "",
            "source_scope": source_scope,
        }

    run_status = str(latest.get("status", "")).strip().lower()
    if run_status in {"queued", "in_progress", "waiting", "requested", "pending"}:
        soft_log = (
            f"Workflow run {run_id} is currently {run_status or 'in_progress'}. "
            "Logs will be available after completion; proceeding with partial context.\n"
        )
        return soft_log, {
            "repo_full_name": repo_full_name,
            "branch": branch_name,
            "run_id": str(run_id),
            "status": str(latest.get("status", "")),
            "conclusion": str(latest.get("conclusion", "")),
            "workflow": str(latest.get("workflowName", "")),
            "url": str(latest.get("url", "")),
            "source_scope": source_scope,
        }

    try:
        logs_text = await _run_gh_command(
            ["run", "view", str(run_id), "--repo", repo_full_name, "--log"],
            f"Failed fetching workflow logs for run {run_id}",
        )
    except HTTPException as exc:
        detail_text = str(exc.detail).lower()
        in_progress_markers = (
            "is still in progress",
            "logs will be available when it is complete",
            "run is in progress",
        )
        if any(marker in detail_text for marker in in_progress_markers):
            soft_log = (
                f"Workflow run {run_id} is still in progress. "
                "Logs are not yet available; proceeding with partial context.\n"
            )
            return soft_log, {
                "repo_full_name": repo_full_name,
                "branch": branch_name,
                "run_id": str(run_id),
                "status": str(latest.get("status", "in_progress")),
                "conclusion": str(latest.get("conclusion", "")),
                "workflow": str(latest.get("workflowName", "")),
                "url": str(latest.get("url", "")),
                "source_scope": source_scope,
            }
        raise
    metadata = {
        "repo_full_name": repo_full_name,
        "branch": branch_name,
        "run_id": str(run_id),
        "status": str(latest.get("status", "")),
        "conclusion": str(latest.get("conclusion", "")),
        "workflow": str(latest.get("workflowName", "")),
        "url": str(latest.get("url", "")),
        "source_scope": source_scope,
    }
    return logs_text, metadata


async def get_validated_github_payload(
    request: Request,
    settings: Settings,
    x_hub_signature_256: str | None,
) -> dict:
    if not x_hub_signature_256:
        raise HTTPException(status_code=401, detail="Missing GitHub signature header")
    secret = (settings.github_webhook_secret or settings.github_token or "").strip()
    if not secret:
        raise HTTPException(status_code=500, detail="GitHub webhook secret not configured")

    body = await request.body()
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    if not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid GitHub signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")
    return payload


def get_orchestrator(settings: Settings = Depends(get_settings)) -> Orchestrator:
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        _ORCHESTRATOR = Orchestrator(settings)
    else:
        _ORCHESTRATOR.settings = settings
    return _ORCHESTRATOR


@router.post("/submit-code", response_model=SubmitCodeResponse)
async def submit_code(
    request: SubmitCodeRequest,
    http_request: Request,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> SubmitCodeResponse:
    session_token = http_request.session.get("github_token") if hasattr(http_request, "session") else None
    state = await orchestrator.submit_code(
        request,
        github_token=session_token,
        correlation_id=getattr(http_request.state, "correlation_id", None),
        trace_id=getattr(http_request.state, "trace_id", None),
    )
    return SubmitCodeResponse(
        pipeline_id=state.pipeline_id,
        current_stage=state.current_stage,
        status=state.status,
    )


@router.post("/submit-archive", response_model=SubmitCodeResponse)
async def submit_archive(
    repo_name: str = Form(...),
    archive: UploadFile = File(...),
    code_entry: str | None = Form(default=None),
    force_real: bool = Query(default=True),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> SubmitCodeResponse:
    """Accept a zip archive of a small project (code + tests) and run the pipeline.

    Warning: when `force_real` is true this will run `pytest` from the uploaded
    project in a temporary directory. This executes user code — run only in a
    trusted environment or inside proper sandboxing.
    """
    if archive.content_type not in ("application/zip", "application/x-zip-compressed", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Only zip archives are supported")

    with tempfile.TemporaryDirectory(prefix="upload_repo_") as tmpdir:
        tmp = Path(tmpdir)
        archive_path = tmp / "upload.zip"
        contents = await archive.read()
        if len(contents) > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Archive exceeds 50 MB limit")
        archive_path.write_bytes(contents)
        try:
            safe_extract_zip(archive_path, tmp)
        except (zipfile.BadZipFile, UnsafeZipError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid or unsafe zip archive: {exc}") from exc

        # Build repo_files mapping for text files only
        repo_files: dict[str, str] = {}
        primary_code = None
        for path in tmp.rglob("*"):
            if path.is_file():
                rel = path.relative_to(tmp).as_posix()
                try:
                    text = path.read_text(encoding="utf-8")
                except Exception:
                    continue
                repo_files[rel] = text
                if code_entry and rel == code_entry:
                    primary_code = text
        if not primary_code:
            # fallback: pick first .py file
            for p, content in repo_files.items():
                if p.endswith(".py"):
                    primary_code = content
                    break

        if primary_code is None:
            primary_code = ""

        from models.schemas import SubmitCodeRequest as SCR

        request = SCR(repo_name=repo_name, code=primary_code, diff="", config_text="", repo_files=repo_files)

        # Optionally force real QA mode for this orchestrator instance
        original_qa_mode = orchestrator.settings.qa_mode
        try:
            if force_real:
                orchestrator.settings.qa_mode = "real"

            state = await orchestrator.submit_code(request)
        finally:
            orchestrator.settings.qa_mode = original_qa_mode

    return SubmitCodeResponse(pipeline_id=state.pipeline_id, current_stage=state.current_stage, status=state.status)


@router.post("/submit-github", response_model=SubmitCodeResponse)
async def submit_github(
    http_request: Request,
    repo_url: str = Form(...),
    branch: str | None = Form(default="main"),
    code_entry: str | None = Form(default=None),
    enable_auto_pr: bool = Form(default=False),
    multimodal_modes: str = Form(default=""),
    multimodal_text: str = Form(default=""),
    force_real: bool = Query(default=True),
    wait: bool = Query(default=True),
    orchestrator: Orchestrator = Depends(get_orchestrator),
    settings: Settings = Depends(get_settings),
) -> SubmitCodeResponse:
    """Fetch a public GitHub repository archive and run the pipeline.

    This downloads the branch zip from GitHub, extracts it, and behaves like
    `/submit-archive`. The `repo_url` should be a public GitHub repo URL such
    as `https://github.com/owner/repo` or `https://github.com/owner/repo.git`.
    """
    session_token = http_request.session.get("github_token") if hasattr(http_request, "session") else None
    # Prefer the logged-in user's OAuth token so permissions match the active user.
    effective_github_token = session_token or settings.github_token
    requested_enable_auto_pr = enable_auto_pr

    # Explicitly reject PR/commit/compare URLs in v1 so behavior is predictable.
    lowered = repo_url.lower()
    if any(segment in lowered for segment in ["/pull/", "/pulls/", "/commit/", "/compare/"]):
        raise HTTPException(
            status_code=400,
            detail=(
                "Pull request and commit URLs are not supported yet. "
                "Please submit a repository root URL such as https://github.com/owner/repo."
            ),
        )

    # Extract owner/repo from the provided URL (support several common forms)
    # Examples supported:
    #  - https://github.com/owner/repo
    #  - https://github.com/owner/repo.git
    #  - git@github.com:owner/repo.git
    #  - github.com/owner/repo
    m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?(?:$|/)", repo_url)
    if not m:
        raise HTTPException(status_code=400, detail="repo_url must point to a public GitHub repository (format: github.com/owner/repo)")
    owner = m.group(1)
    repo_name = m.group(2)
    headers = {"User-Agent": "devops-agent/0.1"}
    if effective_github_token:
        headers["Authorization"] = f"Bearer {effective_github_token}"

    selected_branch: str | None = None
    resp: httpx.Response | None = None

    async with (
        httpx.AsyncClient(follow_redirects=True, headers=headers) as client,
        httpx.AsyncClient(follow_redirects=True, headers={"User-Agent": "devops-agent/0.1"}) as public_client,
    ):
        try:
            repo_meta = await client.get(f"https://api.github.com/repos/{owner}/{repo_name}", timeout=20.0)
            if repo_meta.status_code != 200:
                # Retry metadata without auth so a stale token does not block public repos.
                repo_meta = await public_client.get(f"https://api.github.com/repos/{owner}/{repo_name}", timeout=20.0)
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to fetch repository metadata: {exc}",
            )

        if repo_meta.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Failed to fetch repository metadata: HTTP {repo_meta.status_code}. "
                    "Verify the repository exists and your token has access."
                ),
            )

        repo_meta_json = repo_meta.json()
        default_branch = str(repo_meta_json.get("default_branch") or "").strip()
        if not default_branch:
            raise HTTPException(status_code=400, detail="Repository metadata missing default_branch")

        # Prefer explicit branch from the request when provided, otherwise fall back to the repository default.
        selected_branch = (branch or default_branch or "").strip() or default_branch
        zip_url = f"https://api.github.com/repos/{owner}/{repo_name}/zipball/{selected_branch}"

        try:
            resp = await client.get(zip_url, timeout=30.0)
            if resp.status_code in {401, 403}:
                resp = await public_client.get(zip_url, timeout=30.0)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=400, detail=f"Failed to download repo archive: {exc}")

        if resp.status_code == 404 and selected_branch != default_branch:
            selected_branch = default_branch
            zip_url = f"https://api.github.com/repos/{owner}/{repo_name}/zipball/{selected_branch}"
            try:
                resp = await public_client.get(zip_url, timeout=30.0)
            except httpx.RequestError as exc:
                raise HTTPException(status_code=400, detail=f"Failed to download repo archive: {exc}")

        if resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Failed to download repo archive: HTTP {resp.status_code}. "
                    f"Branch used: {selected_branch}. "
                    "If the repository is private, login with GitHub or configure GITHUB_TOKEN with access."
                ),
            )

        # Keep the user's auto-PR choice; orchestrator will attempt PR creation
        # with available tokens and emit explicit failures if permissions are missing.
        if requested_enable_auto_pr:
            enable_auto_pr = True

        with tempfile.TemporaryDirectory(prefix="github_repo_") as tmpdir:
            tmp = Path(tmpdir)
            archive_path = tmp / "repo.zip"
            archive_path.write_bytes(resp.content)
            if len(resp.content) > 50 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Downloaded archive exceeds 50 MB limit")
            try:
                safe_extract_zip(archive_path, tmp)
            except (zipfile.BadZipFile, UnsafeZipError) as exc:
                raise HTTPException(status_code=400, detail=f"Invalid or unsafe zip archive: {exc}") from exc

            # Build repo_files mapping for text files only
            repo_files: dict[str, str] = {}
            primary_code = None
            for path in tmp.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(tmp).as_posix()
                    try:
                        text = path.read_text(encoding="utf-8")
                    except Exception:
                        continue
                    repo_files[rel] = text
                    if code_entry and rel == code_entry:
                        primary_code = text
            if not primary_code:
                # fallback: pick first .py file
                for p, content in repo_files.items():
                    if p.endswith(".py"):
                        primary_code = content
                        break

            if primary_code is None:
                primary_code = ""

            from models.schemas import SubmitCodeRequest as SCR

            multimodal_inputs: list[dict] = []
            multimodal_results: list[dict] = []
            selected_modes = [m.strip().lower() for m in multimodal_modes.split(",") if m.strip()]
            selected_modes = list(dict.fromkeys(selected_modes))
            if selected_modes:
                multimodal_inputs, multimodal_results = await _run_submit_multimodal_modes(
                    selected_modes=selected_modes,
                    multimodal_text=multimodal_text,
                    repo_files=repo_files,
                    repo_full_name=f"{owner}/{repo_name}",
                    selected_branch=selected_branch or "main",
                    settings=settings,
                )

            request = SCR(
                repo_name=repo_name,
                code=primary_code,
                diff="",
                config_text="",
                repo_files=repo_files,
                multimodal_inputs=multimodal_inputs,
                multimodal_results=multimodal_results,
                enable_auto_pr=enable_auto_pr,
                repo_full_name=f"{owner}/{repo_name}",
                clone_url=repo_url,
                branch=selected_branch,
            )

            # Optionally force real QA mode for this orchestrator instance
            original_qa_mode = orchestrator.settings.qa_mode
            try:
                if force_real:
                    orchestrator.settings.qa_mode = "real"

                if wait:
                    state = await orchestrator.submit_code(request, github_token=session_token)
                else:
                    from models.schemas import PipelineState as PS

                    chosen_qa = "real" if force_real else original_qa_mode
                    state = PS(repo_name=repo_name, status="running", current_stage="dev")
                    orchestrator.state_store.upsert(state)

                    async def _run_pipeline(seed: PS) -> None:
                        previous_qa = orchestrator.settings.qa_mode
                        orchestrator.settings.qa_mode = chosen_qa
                        try:
                            await orchestrator.submit_code(
                                request,
                                github_token=session_token,
                                existing_state=seed,
                            )
                        except Exception as exc:  # noqa: BLE001
                            LOGGER.exception("Background pipeline failed id=%s", seed.pipeline_id)
                            seed.status = "failed"
                            seed.current_stage = "failed"
                            seed.history.append(
                                {
                                    "stage": "failed",
                                    "message": f"Background pipeline failed: {exc}",
                                }
                            )
                            orchestrator.state_store.upsert(seed)
                        finally:
                            orchestrator.settings.qa_mode = previous_qa

                    task = asyncio.create_task(_run_pipeline(state))
                    _BACKGROUND_PIPELINE_TASKS.add(task)
                    task.add_done_callback(_BACKGROUND_PIPELINE_TASKS.discard)
            finally:
                orchestrator.settings.qa_mode = original_qa_mode

    return SubmitCodeResponse(pipeline_id=state.pipeline_id, current_stage=state.current_stage, status=state.status)


@router.get("/pipeline-status/{pipeline_id}", response_model=PipelineState)
def pipeline_status(
    pipeline_id: str,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> PipelineState:
    state = orchestrator.get_status(pipeline_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return state


def _auto_pr_urls(state: PipelineState) -> list[str]:
    registry = state.artifacts.get("auto_pr_registry", {}) if isinstance(state.artifacts, dict) else {}
    urls: list[str] = []
    if not isinstance(registry, dict):
        return urls
    for item in registry.get("branches", []) or []:
        if isinstance(item, dict) and item.get("pr_url"):
            urls.append(str(item["pr_url"]))
        elif isinstance(item, dict) and item.get("pr_number"):
            urls.append(f"PR #{item['pr_number']}")
    return urls


@router.get("/pipelines", response_model=list[PipelineListItem])
def list_pipelines(
    limit: int = Query(default=20, ge=1, le=100),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> list[PipelineListItem]:
    items: list[PipelineListItem] = []
    for item in orchestrator.list_pipelines(limit=limit):
        items.append(
            PipelineListItem(
                pipeline_id=item.pipeline_id,
                repo_name=item.repo_name,
                current_stage=item.current_stage,
                status=item.status,
                created_at=item.created_at,
                updated_at=item.updated_at,
                correlation_id=item.correlation_id,
                auto_pr_urls=_auto_pr_urls(item),
            )
        )
    return items


@router.post("/pipelines/{pipeline_id}/cancel", response_model=PipelineState)
def cancel_pipeline(
    pipeline_id: str,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    auth: dict = Depends(optional_pipeline_auth),
) -> PipelineState:
    state = orchestrator.request_cancel(pipeline_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    actor = str(auth.get("github_username") or auth.get("user_id") or "anonymous")
    roles = list(auth.get("roles") or [])
    orchestrator._append_audit_event(
        state,
        action="pipeline.cancel",
        actor=actor,
        roles=roles,
        outcome="cancelled",
        details={},
    )
    orchestrator.state_store.upsert(state)
    return state


RETRYABLE_PIPELINE_STATUSES = frozenset({"blocked", "blocked_with_prs_sent", "failed", "cancelled"})
RESUMABLE_PIPELINE_STATUSES = RETRYABLE_PIPELINE_STATUSES | frozenset({"cancelling", "running"})


@router.post("/pipelines/{pipeline_id}/retry", response_model=PipelineState)
async def retry_pipeline(
    pipeline_id: str,
    http_request: Request,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    auth: dict = Depends(optional_pipeline_auth),
) -> PipelineState:
    state = orchestrator.get_status(pipeline_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    if state.status not in RETRYABLE_PIPELINE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Run in status '{state.status}' cannot be retried; only blocked, failed or cancelled runs can.",
        )
    if not isinstance(state.artifacts.get("submit_request"), dict):
        raise HTTPException(
            status_code=409,
            detail="No submit snapshot stored for this pipeline; submit code again to enable retry.",
        )

    session_token = http_request.session.get("github_token") if hasattr(http_request, "session") else None
    actor = str(auth.get("github_username") or auth.get("user_id") or "anonymous")
    roles = list(auth.get("roles") or [])
    orchestrator._append_audit_event(
        state,
        action="pipeline.retry",
        actor=actor,
        roles=roles,
        outcome="running",
        details={"mode": "full"},
    )
    state.cancelled = False
    state.status = "running"
    state.current_stage = "dev"
    orchestrator.state_store.upsert(state)

    async def _run_retry() -> None:
        try:
            await orchestrator.retry_pipeline(pipeline_id, github_token=session_token)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Background pipeline retry failed id=%s", pipeline_id)
            failed = orchestrator.get_status(pipeline_id)
            if failed is not None:
                failed.status = "failed"
                failed.current_stage = "failed"
                failed.history.append(
                    {
                        "stage": "failed",
                        "message": f"Pipeline retry failed: {exc}",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                orchestrator.state_store.upsert(failed)

    task = asyncio.create_task(_run_retry())
    _BACKGROUND_PIPELINE_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_PIPELINE_TASKS.discard)
    return state


@router.post("/pipelines/{pipeline_id}/resume", response_model=PipelineState)
async def resume_pipeline(
    pipeline_id: str,
    http_request: Request,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    auth: dict = Depends(optional_pipeline_auth),
) -> PipelineState:
    state = orchestrator.get_status(pipeline_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    if state.status not in RESUMABLE_PIPELINE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Run in status '{state.status}' cannot be resumed.",
        )
    if not isinstance(state.artifacts.get("full_scan_combined"), dict):
        raise HTTPException(
            status_code=409,
            detail="No checkpoint stored for this pipeline; use retry for a full restart.",
        )
    if not isinstance(state.artifacts.get("submit_request"), dict):
        raise HTTPException(status_code=409, detail="No submit snapshot stored for this pipeline.")

    session_token = http_request.session.get("github_token") if hasattr(http_request, "session") else None
    actor = str(auth.get("github_username") or auth.get("user_id") or "anonymous")
    roles = list(auth.get("roles") or [])
    orchestrator._append_audit_event(
        state,
        action="pipeline.resume",
        actor=actor,
        roles=roles,
        outcome="running",
        details={"mode": "checkpoint"},
    )
    state.cancelled = False
    state.status = "running"
    orchestrator.state_store.upsert(state)

    async def _run_resume() -> None:
        try:
            await orchestrator.resume_pipeline(pipeline_id, github_token=session_token)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Background pipeline resume failed id=%s", pipeline_id)
            failed = orchestrator.get_status(pipeline_id)
            if failed is not None:
                failed.status = "failed"
                failed.current_stage = "failed"
                failed.history.append(
                    {
                        "stage": "failed",
                        "message": f"Pipeline resume failed: {exc}",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                orchestrator.state_store.upsert(failed)

    task = asyncio.create_task(_run_resume())
    _BACKGROUND_PIPELINE_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_PIPELINE_TASKS.discard)
    return state


@router.get("/pipelines/{pipeline_id}/audit")
def get_pipeline_audit(
    pipeline_id: str,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    _: dict = Depends(optional_pipeline_auth),
) -> dict[str, Any]:
    state = orchestrator.get_status(pipeline_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    trail = state.artifacts.get("audit_trail", [])
    if not isinstance(trail, list):
        trail = []
    return {"pipeline_id": pipeline_id, "events": trail[-50:], "total": len(trail)}


@router.post("/trigger-deployment", response_model=PipelineState)
async def trigger_deployment(
    request: TriggerDeploymentRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    settings: Settings = Depends(get_settings),
    x_api_key: str | None = Header(default=None),
) -> PipelineState:
    auth = AuthService(settings)
    user = auth.authenticate(x_api_key)
    auth.require_role(user, {"approver", "admin"})
    state = await orchestrator.trigger_deployment(
        request.pipeline_id,
        request.approved_by,
        actor=user.user_id,
        actor_roles=user.roles,
    )
    if state is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return state


@router.post("/analyze-logs", response_model=MonitoringResult)
def analyze_logs(
    request: AnalyzeLogsRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> MonitoringResult:
    return orchestrator.analyze_logs(request)


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    configured = (settings.llm_mode or "auto").lower()
    has_key = bool((settings.huggingface_api_key or settings.llm_api_key or "").strip())
    if configured == "mock":
        llm_mode = "mock"
    elif configured == "live":
        llm_mode = "live" if has_key else "mock"
    else:
        llm_mode = "live" if has_key else "mock"
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        queue_backend=settings.queue_backend,
        llm_mode=llm_mode,
        qa_mode=settings.qa_mode,
        auth_enabled=settings.auth_enabled or settings.api_require_auth,
    )


@router.get("/api/v1/pipeline/health", response_model=HealthResponse)
def pipeline_health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return health(settings)


async def ws_pipeline_auth(websocket: WebSocket) -> bool:
    cfg = get_settings()
    if not cfg.auth_enabled and not cfg.api_require_auth:
        return True
    token = websocket.query_params.get("api_key") or websocket.query_params.get("token")
    if not token:
        return False
    try:
        AuthService(cfg).authenticate(token)
        return True
    except HTTPException:
        return False


@router.websocket("/ws/pipeline-status/{pipeline_id}")
async def pipeline_status_ws(
    websocket: WebSocket,
    pipeline_id: str,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> None:
    if not await ws_pipeline_auth(websocket):
        await websocket.close(code=4401, reason="Authentication required")
        return
    await websocket.accept()
    state = orchestrator.get_status(pipeline_id)
    if state is not None:
        await websocket.send_json(
            {
                "type": "snapshot",
                "pipeline_id": pipeline_id,
                "stage": state.current_stage,
                "status": state.status,
                "history": state.history,
            }
        )
    try:
        while True:
            if websocket.client_state != WebSocketState.CONNECTED:
                break
            event = await orchestrator.wait_pipeline_event(pipeline_id, timeout=1.0)
            if event:
                await websocket.send_json(event)
    except WebSocketDisconnect:
        return


@router.websocket("/ws/analyze-logs")
async def analyze_logs_ws(
    websocket: WebSocket,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> None:
    if not await ws_pipeline_auth(websocket):
        await websocket.close(code=4401, reason="Authentication required")
        return
    await websocket.accept()
    last_request: AnalyzeLogsRequest | None = None

    try:
        while True:
            if websocket.client_state != WebSocketState.CONNECTED:
                break

            try:
                payload = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
                last_request = AnalyzeLogsRequest.model_validate(payload)
            except asyncio.TimeoutError:
                if last_request is None:
                    continue
            except ValueError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON payload"})
                continue
            except Exception as exc:  # noqa: BLE001
                await websocket.send_json({"type": "error", "message": f"Invalid monitoring payload: {exc}"})
                continue

            if last_request is None:
                continue

            result = await asyncio.to_thread(orchestrator.analyze_logs, last_request)
            await websocket.send_json(
                {
                    "type": "monitoring_result",
                    "pipeline_id": last_request.pipeline_id,
                    "result": result.model_dump(),
                }
            )
    except WebSocketDisconnect:
        return


@router.get("/runtime-config", response_model=RuntimeConfigResponse)
def runtime_config(settings: Settings = Depends(get_settings)) -> RuntimeConfigResponse:
    report = preflight_report(settings)
    return RuntimeConfigResponse.model_validate(report)


@router.post("/api/v1/webhook/github")
async def github_push_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
    settings: Settings = Depends(get_settings),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> Any:
    event = (x_github_event or "push").strip()
    delivery_id = (x_github_delivery or "").strip()

    if delivery_id:
        db = SessionLocal()
        try:
            prior = find_delivery(db, delivery_id)
            if prior is not None and prior.response_body:
                return JSONResponse(json.loads(prior.response_body), status_code=202)
        finally:
            db.close()

    if event == "ping":
        body_out = {"status": "ok", "event": "ping"}
        if delivery_id:
            db = SessionLocal()
            try:
                record_delivery(
                    db,
                    delivery_id=delivery_id,
                    event_type=event,
                    repo_full_name=None,
                    pipeline_id=None,
                    status="accepted",
                    response_body=body_out,
                )
            finally:
                db.close()
        return body_out

    if event != "push":
        return {"status": "ignored", "event": event}

    payload = await get_validated_github_payload(request, settings, x_hub_signature_256)
    repository = payload.get("repository") or {}
    repo_full_name = repository.get("full_name")
    ref = str(payload.get("ref") or "")
    branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else ref
    if not repo_full_name or not branch:
        raise HTTPException(status_code=400, detail="Missing repository or branch in push payload")
    if str(payload.get("after") or "").strip("0") == "":
        return {"status": "ignored", "reason": "branch deletion"}

    session_token = request.session.get("github_token") if hasattr(request, "session") else None

    async def _run_push() -> None:
        try:
            await start_github_push_pipeline(
                orchestrator,
                settings,
                repo_full_name=repo_full_name,
                branch=branch,
                github_token=session_token,
                correlation_id=getattr(request.state, "correlation_id", None),
                trace_id=getattr(request.state, "trace_id", None),
            )
        except Exception:
            LOGGER.exception("GitHub push webhook pipeline failed for %s", repo_full_name)

    task = asyncio.create_task(_run_push())
    _BACKGROUND_PIPELINE_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_PIPELINE_TASKS.discard)

    body_out = {
        "status": "accepted",
        "event": event,
        "repo_full_name": repo_full_name,
        "branch": branch,
        "correlation_id": getattr(request.state, "correlation_id", None),
    }
    if delivery_id:
        db = SessionLocal()
        try:
            record_delivery(
                db,
                delivery_id=delivery_id,
                event_type=event,
                repo_full_name=repo_full_name,
                pipeline_id=None,
                status="accepted",
                response_body=body_out,
            )
        finally:
            db.close()
    return JSONResponse(body_out, status_code=202)


@router.post("/api/v1/webhook/github/pr")
async def github_pr_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
    settings: Settings = Depends(get_settings),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> dict:
    delivery_id = (x_github_delivery or "").strip()
    if delivery_id:
        db = SessionLocal()
        try:
            prior = find_delivery(db, delivery_id)
            if prior is not None and prior.response_body:
                return JSONResponse(json.loads(prior.response_body), status_code=202)
        finally:
            db.close()

    payload = await get_validated_github_payload(request, settings, x_hub_signature_256)
    if payload.get("action") != "closed":
        return {"processed": False, "reason": "ignored-action"}

    pull_request = payload.get("pull_request", {})
    if not pull_request.get("merged", False):
        return {"processed": False, "reason": "not-merged"}

    repository = payload.get("repository", {})
    repo_full_name = repository.get("full_name")
    branch_name = pull_request.get("head", {}).get("ref")
    pr_number = pull_request.get("number")
    if not repo_full_name or not branch_name:
        raise HTTPException(status_code=400, detail="Missing repository or branch data")

    matched_state = None
    matched_branch = None
    for state in orchestrator.state_store.list_states():
        registry = state.artifacts.get("auto_pr_registry", {}) if isinstance(state.artifacts, dict) else {}
        branches = registry.get("branches", []) if isinstance(registry, dict) else []
        for item in branches:
            if not isinstance(item, dict):
                continue
            branch_match = item.get("branch_name") == branch_name
            pr_match = pr_number is not None and item.get("pr_number") == pr_number
            if branch_match or pr_match:
                matched_state = state
                matched_branch = item
                break
        if matched_state is not None:
            break

    if matched_state is None or matched_branch is None:
        return {"processed": False, "reason": "branch-not-found", "pr_number": pr_number}

    github_service = GitHubService(settings.github_token)
    try:
        deleted = await github_service.delete_branch(repo_full_name, branch_name)
    finally:
        await github_service.close()

    matched_branch["merged"] = True
    matched_branch["deleted"] = deleted
    matched_branch["merged_and_deleted"] = deleted
    orchestrator.state_store.upsert(matched_state)
    body_out = {
        "processed": True,
        "repo_full_name": repo_full_name,
        "branch_name": branch_name,
        "pr_number": pr_number,
        "deleted": deleted,
    }
    if delivery_id:
        db = SessionLocal()
        try:
            record_delivery(
                db,
                delivery_id=delivery_id,
                event_type="pull_request",
                repo_full_name=repo_full_name,
                pipeline_id=matched_state.pipeline_id,
                status="processed",
                response_body=body_out,
            )
        finally:
            db.close()
    return body_out
