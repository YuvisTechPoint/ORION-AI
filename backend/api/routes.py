import asyncio

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
    enable_auto_pr: bool = Form(default=True),
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
        headers["Authorization"] = f"token {effective_github_token}"

    requested_branch = (branch or "").strip()
    branch_candidates: list[str] = []
    if requested_branch:
        branch_candidates.append(requested_branch)

    resolved_default_branch: str | None = None

    async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
        try:
            repo_meta = await client.get(f"https://api.github.com/repos/{owner}/{repo_name}", timeout=20.0)
            if repo_meta.status_code == 200:
                repo_meta_json = repo_meta.json()
                resolved_default_branch = str(repo_meta_json.get("default_branch") or "").strip() or None
                if resolved_default_branch:
                    branch_candidates.append(resolved_default_branch)

                # Enforce push permission only when auto-PR is enabled.
                if effective_github_token and requested_enable_auto_pr:
                    permissions = repo_meta_json.get("permissions", {})
                    if not bool(permissions.get("push", False)):
                        # Gracefully degrade to analysis-only mode when token cannot push.
                        enable_auto_pr = False
        except httpx.RequestError:
            # If metadata preflight fails, continue with branch fallbacks.
            pass

        branch_candidates.extend(["main", "master"])
        # Preserve order while deduplicating branch names.
        branch_candidates = list(dict.fromkeys([b for b in branch_candidates if b]))

        resp: httpx.Response | None = None
        selected_branch: str | None = None
        last_status_code: int | None = None

        for candidate_branch in branch_candidates:
            api_zip_url = f"https://api.github.com/repos/{owner}/{repo_name}/zipball/{candidate_branch}"
            try:
                # If we have a token, try API zipball first (works for private repos).
                if effective_github_token:
                    resp = await client.get(api_zip_url, timeout=30.0)
                else:
                    zip_url = f"https://github.com/{owner}/{repo_name}/archive/refs/heads/{candidate_branch}.zip"
                    resp = await client.get(zip_url, timeout=30.0)
            except httpx.RequestError:
                resp = None

            if resp is not None and resp.status_code == 200:
                selected_branch = candidate_branch
                break

            if resp is not None:
                last_status_code = resp.status_code

            # Fallback to codeload URL (often needed when GitHub serves redirects differently).
            codeload_url = f"https://codeload.github.com/{owner}/{repo_name}/zip/{candidate_branch}"
            try:
                resp = await client.get(codeload_url, timeout=30.0)
            except httpx.RequestError:
                resp = None

            if resp is not None and resp.status_code == 200:
                selected_branch = candidate_branch
                break

            if resp is not None:
                last_status_code = resp.status_code

        if resp is None or resp.status_code != 200 or not selected_branch:
            attempted = ", ".join(branch_candidates) if branch_candidates else "none"
            status_text = str(last_status_code) if last_status_code is not None else "network-error"
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Failed to download repo archive: HTTP {status_text}. "
                    f"Tried branches: {attempted}. "
                    "If the repository is private, login with GitHub or configure GITHUB_TOKEN with access."
                ),
            )

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

            request = SCR(
                repo_name=repo_name,
                code=primary_code,
                diff="",
                config_text="",
                repo_files=repo_files,
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
            if isinstance(item, dict) and item.get("branch_name") == branch_name:
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
