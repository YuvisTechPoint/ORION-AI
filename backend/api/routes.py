from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi import File, UploadFile, Form, Query
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

router = APIRouter()
_ORCHESTRATOR: Orchestrator | None = None


def get_orchestrator(settings: Settings = Depends(get_settings)) -> Orchestrator:
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        _ORCHESTRATOR = Orchestrator(settings)
    return _ORCHESTRATOR


@router.post("/submit-code", response_model=SubmitCodeResponse)
async def submit_code(
    request: SubmitCodeRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> SubmitCodeResponse:
    state = await orchestrator.submit_code(request)
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
    force_real: bool = Query(default=False),
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
    repo_url: str = Form(...),
    branch: str | None = Form(default="main"),
    code_entry: str | None = Form(default=None),
    force_real: bool = Query(default=False),
    orchestrator: Orchestrator = Depends(get_orchestrator),
    settings: Settings = Depends(get_settings),
) -> SubmitCodeResponse:
    """Fetch a public GitHub repository archive and run the pipeline.

    This downloads the branch zip from GitHub, extracts it, and behaves like
    `/submit-archive`. The `repo_url` should be a public GitHub repo URL such
    as `https://github.com/owner/repo` or `https://github.com/owner/repo.git`.
    """
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
    # Prefer API download when token is available (supports private repos)
    api_zip_url = f"https://api.github.com/repos/{owner}/{repo_name}/zipball/{branch}"

    headers = {"User-Agent": "devops-agent/0.1"}
    if settings.github_token:
        headers["Authorization"] = f"token {settings.github_token}"

    async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
        try:
            # If we have a token, try the API zipball endpoint (works for private repos)
            if settings.github_token:
                resp = await client.get(api_zip_url, timeout=30.0)
            else:
                zip_url = f"https://github.com/{owner}/{repo_name}/archive/refs/heads/{branch}.zip"
                resp = await client.get(zip_url, timeout=30.0)
        except httpx.RequestError:
            raise HTTPException(status_code=400, detail="Failed to fetch repository archive from GitHub")

        if resp.status_code != 200:
            # Fallback to codeload URL (often needed when GitHub serves 3xx/404 differently)
            codeload_url = f"https://codeload.github.com/{owner}/{repo_name}/zip/{branch}"
            try:
                resp = await client.get(codeload_url, timeout=30.0)
            except httpx.RequestError:
                raise HTTPException(status_code=400, detail="Failed to fetch repository archive from GitHub (codeload)")

        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Failed to download repo archive: HTTP {resp.status_code}")

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


@router.get("/runtime-config", response_model=RuntimeConfigResponse)
def runtime_config(settings: Settings = Depends(get_settings)) -> RuntimeConfigResponse:
    report = preflight_report(settings)
    return RuntimeConfigResponse.model_validate(report)
