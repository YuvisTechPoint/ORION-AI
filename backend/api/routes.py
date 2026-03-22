import asyncio
import json
import os
import shutil
import subprocess

from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi import File, UploadFile, Form, Query
from fastapi import Request
import hashlib
import hmac
import zipfile
import tempfile
from pathlib import Path
from starlette.websockets import WebSocketState
import httpx
import re

from core.config import Settings, get_settings
from models.schemas import (
    AnalyzeLogsRequest,
    HealthResponse,
    MonitoringResult,
    PipelineState,
    RuntimeConfigResponse,
    SubmitCodeRequest,
    SubmitCodeResponse,
    TriggerDeploymentRequest,
)
from services.orchestrator import Orchestrator
from services.auth import AuthService
from services.preflight import preflight_report
from services.github_service import GitHubService

router = APIRouter()
_ORCHESTRATOR: Orchestrator | None = None


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

    logs_text = await _run_gh_command(
        ["run", "view", str(run_id), "--repo", repo_full_name, "--log"],
        f"Failed fetching workflow logs for run {run_id}",
    )
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
    if not settings.github_token:
        raise HTTPException(status_code=500, detail="GitHub secret/token not configured")

    body = await request.body()
    digest = hmac.new(settings.github_token.encode("utf-8"), body, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    if not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid GitHub signature")

    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
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
    state = await orchestrator.submit_code(request, github_token=session_token)
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
        archive_path.write_bytes(contents)
        try:
            with zipfile.ZipFile(archive_path, "r") as z:
                z.extractall(path=tmp)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip archive")

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
            try:
                with zipfile.ZipFile(archive_path, "r") as z:
                    z.extractall(path=tmp)
            except zipfile.BadZipFile:
                raise HTTPException(status_code=400, detail="Invalid zip archive downloaded from GitHub")

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

            selected_modes = [m.strip().lower() for m in multimodal_modes.split(",") if m.strip()]
            selected_modes = list(dict.fromkeys(selected_modes))

            if "payment" in selected_modes and not _detect_payment_integration(repo_files):
                raise HTTPException(
                    status_code=400,
                    detail="Selected Payment Analyzer, but this repository does not appear to have payment integration.",
                )

            multimodal_inputs: list[dict] = []
            multimodal_results: list[dict] = []
            if selected_modes:
                for mode in selected_modes:
                    if mode == "git_logs":
                        gh_logs, gh_metadata = await _fetch_github_workflow_logs_via_gh(
                            repo_full_name=f"{owner}/{repo_name}",
                            branch=selected_branch,
                            limit=1,
                        )
                        combined_content = gh_logs
                        if multimodal_text.strip():
                            combined_content = f"{combined_content}\n\n# User notes\n{multimodal_text.strip()}"
                        multimodal_inputs.append(
                            {
                                "modality": "log",
                                "content": combined_content,
                                "name": "submit_multimodal_git_logs",
                                "metadata": {"source": "gh_cli_workflow", "mode": mode, **gh_metadata},
                            }
                        )
                        multimodal_results.append(_build_multimodal_mode_result(mode, combined_content, gh_metadata))
                        continue

                    if mode == "payment":
                        payment_hint = multimodal_text.strip() or "Payment analyzer selected. Review payment-sensitive code paths."
                        payment_context = {
                            "payment_related_files": [
                                rel
                                for rel, content in repo_files.items()
                                if any(marker in f"{rel}\n{content}".lower() for marker in ["payment", "stripe", "checkout", "invoice"])
                            ][:30]
                        }
                        multimodal_inputs.append(
                            {
                                "modality": "metrics",
                                "content": payment_hint,
                                "name": "submit_multimodal_payment",
                                "metadata": {"source": "submit-github", "mode": mode, **payment_context},
                            }
                        )
                        multimodal_results.append(_build_multimodal_mode_result(mode, payment_hint, payment_context))
                        continue

                    modality = "log" if mode == "git_logs" else "metrics"
                    content_value = multimodal_text.strip() or f"Mode selected: {mode}"
                    multimodal_inputs.append(
                        {
                            "modality": modality,
                            "content": content_value,
                            "name": f"submit_multimodal_{mode}",
                            "metadata": {"source": "submit-github", "mode": mode},
                        }
                    )
                    multimodal_results.append(_build_multimodal_mode_result(mode, content_value, {"source": "submit-github"}))

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

                state = await orchestrator.submit_code(request, github_token=session_token)
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
    llm_mode = "live" if settings.llm_api_key else "mock"
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        queue_backend=settings.queue_backend,
        llm_mode=llm_mode,
        qa_mode=settings.qa_mode,
        auth_enabled=settings.auth_enabled,
    )


@router.get("/api/v1/pipeline/health", response_model=HealthResponse)
def pipeline_health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return health(settings)


@router.websocket("/ws/pipeline-status/{pipeline_id}")
async def pipeline_status_ws(
    websocket: WebSocket,
    pipeline_id: str,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> None:
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


@router.post("/api/v1/webhook/github/pr")
async def github_pr_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> dict:
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
    return {
        "processed": True,
        "repo_full_name": repo_full_name,
        "branch_name": branch_name,
        "pr_number": pr_number,
        "deleted": deleted,
    }
