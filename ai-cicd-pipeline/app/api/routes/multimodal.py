import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.multimodal import (
    VALID_LOG_TYPES,
    CiBuildLogAgent,
    DockerfileAgent,
    GitHubLogAgent,
    GitLogAgent,
    KubernetesManifestAgent,
    LogAnalysisAgent,
    MetricsSnapshotAgent,
    PaymentAgent,
    ProductionTriageAgent,
    artifact_from_upload,
)
from app.agents.multimodal.base_multimodal_agent import BaseMultimodalAgent
from app.api.routes.auth import optional_auth
from app.config import settings
from app.database import get_db
from app.models.pipeline_run import PipelineRun
from app.services.slack_service import slack_service
from app.utils.auth_utils import get_effective_github_token
from app.utils.multimodal_intelligence import build_route_report
from app.utils.multimodal_registry import MULTIMODAL_AGENT_CATALOG, build_multimodal_catalog_report, normalize_agent_id

router = APIRouter(prefix="/multimodal", tags=["Multimodal Analysis"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
AGENT_ALIASES: dict[str, str] = {}
for _entry in MULTIMODAL_AGENT_CATALOG:
    AGENT_ALIASES[_entry["id"]] = _entry["id"]
    for _alias in _entry["aliases"]:
        AGENT_ALIASES[_alias.lower()] = _entry["id"]


def get_anthropic_client() -> AsyncAnthropic | None:
    return AsyncAnthropic(api_key=settings.anthropic_api_key) if settings.llm_enabled else None


async def _collect_artifacts(files: list[UploadFile], text_input: str) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for uf in files:
        data = await uf.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"{uf.filename} exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
            )
        artifacts.append(artifact_from_upload(uf.filename or "file", uf.content_type, data))
    if text_input.strip():
        artifacts.append(
            {"type": "text", "content": text_input, "filename": "pasted.txt", "mime_type": "text/plain"}
        )
    return artifacts


async def _resolve_run(db: AsyncSession, pipeline_run_id: str | None) -> uuid.UUID | None:
    if not pipeline_run_id:
        return None
    try:
        run_id = uuid.UUID(pipeline_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="pipeline_run_id must be a UUID") from exc
    if await db.get(PipelineRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return run_id


def _require_artifacts(artifacts: list[dict[str, Any]]) -> None:
    if not artifacts:
        raise HTTPException(status_code=400, detail="Provide at least one file or text input")


def _response(agent_type: str, user: dict[str, Any], result: dict[str, Any], run_id: uuid.UUID | None) -> dict[str, Any]:
    return {
        "status": "success",
        "agent": agent_type,
        "agent_type": agent_type,
        "pipeline_run_id": str(run_id) if run_id else None,
        "analyzed_by": user.get("username"),
        "result": result,
    }


@router.post("/analyze")
async def analyze(
    request: Request,
    user: dict = Depends(optional_auth),
    db: AsyncSession = Depends(get_db),
    client: AsyncAnthropic | None = Depends(get_anthropic_client),
    agent_type: str = Form(...),
    pipeline_run_id: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    text_input: str = Form(default=""),
    log_type: str = Form(default="server_timeout"),
    repo_full_name: str | None = Form(default=None),
    clone_url: str | None = Form(default=None),
    branch: str = Form(default="main"),
    dockerfile_path: str = Form(default="Dockerfile"),
    github_run_id: int | None = Form(default=None),
) -> dict[str, Any]:
    normalized = normalize_agent_id(agent_type) or AGENT_ALIASES.get(agent_type.strip().lower())
    if normalized is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported agent_type '{agent_type}'. Use one of: {', '.join(sorted(set(AGENT_ALIASES.values())))}",
        )
    run_id = await _resolve_run(db, pipeline_run_id)
    artifacts = await _collect_artifacts(files, text_input)
    session_token = request.session.get("github_token")
    common: dict[str, Any] = {
        "pipeline_run_id": run_id,
        "db": db if run_id else None,
        "anthropic_client": client,
        "artifacts": artifacts,
    }

    agent: BaseMultimodalAgent
    if normalized == "log_analysis":
        if log_type not in VALID_LOG_TYPES:
            raise HTTPException(status_code=400, detail=f"log_type must be one of: {', '.join(VALID_LOG_TYPES)}")
        agent = LogAnalysisAgent(log_type=log_type, **common)
    elif normalized == "github_actions":
        agent = GitHubLogAgent(**common)
        if github_run_id is not None:
            if not repo_full_name:
                raise HTTPException(status_code=400, detail="repo_full_name is required with github_run_id")
            try:
                await agent.add_run_logs(repo_full_name, github_run_id, get_effective_github_token(session_token))
            except ValueError as exc:
                raise HTTPException(status_code=401, detail=str(exc)) from exc
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail=f"Failed to fetch GitHub run logs: {exc}") from exc
    elif normalized == "dockerfile":
        agent = DockerfileAgent(
            repo_full_name=repo_full_name,
            clone_url=clone_url,
            branch=branch,
            github_token=session_token,
            dockerfile_path=dockerfile_path,
            **common,
        )
    elif normalized == "production_triage":
        agent = ProductionTriageAgent(**common)
    elif normalized == "payment":
        agent = PaymentAgent(**common)
    elif normalized == "ci_build_log":
        agent = CiBuildLogAgent(**common)
    elif normalized == "metrics_snapshot":
        agent = MetricsSnapshotAgent(**common)
    elif normalized == "kubernetes":
        agent = KubernetesManifestAgent(**common)
    else:
        agent = GitLogAgent(**common)

    _require_artifacts(agent.artifacts)
    result = await agent.execute()
    if normalized == "production_triage" and result.get("escalate_to_human"):
        await slack_service.send_triage_alert(result)
    return _response(normalized, user, result, run_id)


@router.get("/catalog")
async def multimodal_catalog(_: dict = Depends(optional_auth)) -> dict[str, Any]:
    report = build_multimodal_catalog_report()
    return {"generated_at": datetime.now(timezone.utc).isoformat(), **report}


@router.post("/route")
async def multimodal_route(
    _: dict = Depends(optional_auth),
    agent_type: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    text_input: str = Form(default=""),
) -> dict[str, Any]:
    artifacts = await _collect_artifacts(files, text_input)
    route = build_route_report(
        artifacts=artifacts,
        text_input=text_input,
        preferred_agent=agent_type,
    )
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "route": route}


@router.post("/triage")
async def triage(
    user: dict = Depends(optional_auth),
    db: AsyncSession = Depends(get_db),
    client: AsyncAnthropic | None = Depends(get_anthropic_client),
    pipeline_run_id: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    text_input: str = Form(default=""),
) -> dict[str, Any]:
    run_id = await _resolve_run(db, pipeline_run_id)
    artifacts = await _collect_artifacts(files, text_input)
    _require_artifacts(artifacts)
    agent = ProductionTriageAgent(
        pipeline_run_id=run_id, db=db if run_id else None, anthropic_client=client, artifacts=artifacts
    )
    result = await agent.execute()
    slack_sent = False
    if result.get("escalate_to_human"):
        await slack_service.send_triage_alert(result)
        slack_sent = slack_service.enabled
    response = _response("production_triage", user, result, run_id)
    response["slack_alert_sent"] = slack_sent
    return response


@router.post("/git-logs")
async def analyze_git_logs(
    user: dict = Depends(optional_auth),
    client: AsyncAnthropic | None = Depends(get_anthropic_client),
    files: list[UploadFile] = File(default=[]),
    text_input: str = Form(default=""),
) -> dict[str, Any]:
    artifacts = await _collect_artifacts(files, text_input)
    _require_artifacts(artifacts)
    result = await GitLogAgent(anthropic_client=client, artifacts=artifacts).execute()
    return _response("git_log_analysis", user, result, None)


@router.post("/payment")
async def analyze_payment(
    user: dict = Depends(optional_auth),
    client: AsyncAnthropic | None = Depends(get_anthropic_client),
    files: list[UploadFile] = File(default=[]),
    text_input: str = Form(default=""),
    reconcile: bool = Form(default=False),
) -> dict[str, Any]:
    artifacts = await _collect_artifacts(files, text_input)
    _require_artifacts(artifacts)
    agent = PaymentAgent(anthropic_client=client, artifacts=artifacts)
    result = await agent.execute()
    if reconcile:
        result["reconciliation"] = await agent.generate_reconciliation_report()
    return _response("payment_analysis", user, result, None)
