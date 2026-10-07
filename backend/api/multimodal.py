from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
import requests

from agents.multimodal.dockerfile_agent import DockerfileAgent
from agents.multimodal.github_log_agent import GitHubLogAgent
from agents.multimodal.log_analysis_agent import LogAnalysisAgent
from agents.multimodal.payment_agent import PaymentAgent
from agents.multimodal.production_triage_agent import ProductionTriageAgent
from api.auth import optional_github_token, require_auth
from core.config import get_settings
from core.llm_client import LLMClient
from services.auto_pr_service import AutoPRService

router = APIRouter()


def _artifact_type(file_name: str, mime_type: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if mime_type.startswith("image/"):
        return "image"
    if mime_type == "application/pdf" or suffix == ".pdf":
        return "pdf"
    if mime_type in {"text/csv", "application/csv"} or suffix == ".csv":
        return "csv"
    if suffix in {".log", ".txt"}:
        return "log"
    return "text"


def _multimodal_response(
    agent_type: str,
    result: dict[str, Any],
    *,
    pipeline_run_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "success",
        "agent": agent_type,
        "agent_type": agent_type,
        "pipeline_run_id": pipeline_run_id,
        "result": result,
    }
    if extra:
        payload.update(extra)
    return payload


async def _artifacts_from_request(
    files: list[UploadFile],
    text_input: str = "",
    *,
    settings: Any,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for upload in files:
        raw = await upload.read()
        if len(raw) > settings.multimodal_max_file_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File {upload.filename} exceeds {settings.multimodal_max_file_bytes} bytes",
            )
        artifacts.append(_to_artifact(upload=upload, raw=raw))
    if text_input.strip():
        artifacts.append(
            {
                "type": "text",
                "content": text_input,
                "filename": "pasted.txt",
                "mime_type": "text/plain",
            }
        )
    return artifacts


def _git_log_text(
    text_input: str,
    *,
    use_gh_cli: str = "false",
    repo_full_name: str = "",
    branch: str = "",
    commit_sha: str = "",
    log_limit: str = "",
    pr_number: str = "",
) -> str:
    parts = [text_input.strip()] if text_input.strip() else []
    context = {
        "use_gh_cli": use_gh_cli.lower() in {"1", "true", "yes", "on"},
        "repo_full_name": repo_full_name.strip(),
        "branch": branch.strip(),
        "commit_sha": commit_sha.strip(),
        "log_limit": log_limit.strip(),
        "pr_number": pr_number.strip(),
    }
    context = {key: value for key, value in context.items() if value not in {False, "", 0}}
    if context:
        parts.append(f"Git context: {json.dumps(context)}")
    return "\n".join(parts)


def _to_artifact(upload: UploadFile, raw: bytes) -> dict[str, Any]:
    mime = upload.content_type or "application/octet-stream"
    file_name = upload.filename or "uploaded_file"
    kind = _artifact_type(file_name=file_name, mime_type=mime)
    if kind in {"image", "pdf"}:
        content: bytes | str = raw
    else:
        content = raw.decode("utf-8", errors="ignore")
    return {
        "type": kind,
        "content": content,
        "filename": file_name,
        "mime_type": mime,
    }


def _send_triage_slack_alert(webhook_url: str, triage_result: dict[str, Any]) -> bool:
    if not webhook_url:
        return False
    payload = {
        "text": "ORION P1 triage escalation",
        "triage": triage_result,
    }
    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        return 200 <= response.status_code < 300
    except Exception:
        return False


def _detect_dockerfile_path(artifacts: list[dict[str, Any]]) -> str:
    for artifact in artifacts:
        filename = str(artifact.get("filename", ""))
        lower = filename.lower()
        if lower.endswith("dockerfile") or lower.endswith("dockerfile.dev"):
            return filename
    return "Dockerfile"


async def _run_docker_auto_pr(
    settings: Any,
    analysis_result: dict[str, Any],
    artifacts: list[dict[str, Any]],
    repo_full_name: str | None,
    clone_url: str | None,
    branch: str,
    pipeline_run_id: str | None,
    github_token: str | None,
) -> dict[str, Any]:
    if not bool(analysis_result.get("auto_pr_needed", False)):
        return {"queued": False, "reason": "no-high-severity-dockerfile-issues"}
    if not repo_full_name:
        return {"queued": False, "reason": "repo_full_name-required-for-auto-pr"}
    if not (github_token or settings.github_token):
        return {"queued": False, "reason": "github-token-not-configured"}

    target_file_path = _detect_dockerfile_path(artifacts)
    service = AutoPRService(
        github_token=github_token or settings.github_token,
        repo_full_name=repo_full_name,
        clone_url=clone_url or "",
        base_branch=branch,
    )
    try:
        return await service.open_dockerfile_remediation_pr(
            analysis_result=analysis_result,
            target_file_path=target_file_path,
            run_id=pipeline_run_id or str(uuid4()),
        )
    except Exception as exc:
        return {"queued": False, "reason": f"auto-pr-failed: {exc}"}
    finally:
        await service.close()


@router.post("/analyze")
async def analyze_multimodal(
    agent_type: str = Form(...),
    pipeline_run_id: str | None = Form(default=None),
    log_type: str = Form(default="server_timeout"),
    files: list[UploadFile] = File(...),
    repo_full_name: str | None = Form(default=None),
    clone_url: str | None = Form(default=None),
    branch: str = Form(default="main"),
    user: dict = Depends(require_auth),
    github_token: str | None = Depends(optional_github_token),
) -> dict[str, Any]:
    _ = user
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    settings = get_settings()
    artifacts: list[dict[str, Any]] = []
    for upload in files:
        raw = await upload.read()
        if len(raw) > settings.multimodal_max_file_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File {upload.filename} exceeds {settings.multimodal_max_file_bytes} bytes",
            )
        artifacts.append(_to_artifact(upload=upload, raw=raw))

    llm_client = LLMClient(settings)
    normalized = agent_type.strip().lower()

    if normalized == "payment":
        agent = PaymentAgent(llm_client=llm_client, artifacts=artifacts)
    elif normalized in {"log", "log_analysis", "server_logs"}:
        agent = LogAnalysisAgent(llm_client=llm_client, artifacts=artifacts, log_type=log_type)
    elif normalized in {"github", "github_log", "github_actions"}:
        agent = GitHubLogAgent(llm_client=llm_client, artifacts=artifacts)
    elif normalized in {"git", "git_log", "git_logs", "git_operation"}:
        agent = LogAnalysisAgent(llm_client=llm_client, artifacts=artifacts, log_type="git_operation")
    elif normalized in {"docker", "dockerfile"}:
        agent = DockerfileAgent(llm_client=llm_client, artifacts=artifacts)
    elif normalized in {"triage", "production_triage", "incident"}:
        agent = ProductionTriageAgent(llm_client=llm_client, artifacts=artifacts)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported agent_type: {agent_type}")

    result = agent.execute()

    if normalized in {"docker", "dockerfile"}:
        auto_pr_result = await _run_docker_auto_pr(
            settings=settings,
            analysis_result=result,
            artifacts=artifacts,
            repo_full_name=repo_full_name,
            clone_url=clone_url,
            branch=branch,
            pipeline_run_id=pipeline_run_id,
            github_token=github_token,
        )
        result["auto_pr_triggered"] = bool(auto_pr_result.get("queued", False))
        result["auto_pr_result"] = auto_pr_result

    return {
        "pipeline_run_id": pipeline_run_id,
        "agent_type": normalized,
        "artifacts_count": len(artifacts),
        "result": result,
    }


@router.post("/triage")
async def triage_multimodal(
    pipeline_run_id: str | None = Form(default=None),
    files: list[UploadFile] = File(...),
    user: dict = Depends(require_auth),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    settings = get_settings()
    artifacts: list[dict[str, Any]] = []
    for upload in files:
        raw = await upload.read()
        if len(raw) > settings.multimodal_max_file_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File {upload.filename} exceeds {settings.multimodal_max_file_bytes} bytes",
            )
        artifacts.append(_to_artifact(upload=upload, raw=raw))

    llm_client = LLMClient(settings)
    agent = ProductionTriageAgent(llm_client=llm_client, artifacts=artifacts)
    result = agent.execute()

    slack_sent = False
    if bool(result.get("escalate_to_human", False)):
        slack_sent = _send_triage_slack_alert(settings.slack_webhook_url, result)

    return {
        "pipeline_run_id": pipeline_run_id,
        "agent_type": "production_triage",
        "artifacts_count": len(artifacts),
        "slack_sent": slack_sent,
        "result": result,
    }


@router.post("/git-logs")
async def analyze_git_logs(
    text_input: str = Form(default=""),
    use_gh_cli: str = Form(default="false"),
    repo_full_name: str = Form(default=""),
    branch: str = Form(default="main"),
    commit_sha: str = Form(default=""),
    log_limit: str = Form(default="30"),
    pr_number: str = Form(default=""),
    pipeline_run_id: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    user: dict = Depends(require_auth),
) -> dict[str, Any]:
    _ = user
    settings = get_settings()
    combined_text = _git_log_text(
        text_input,
        use_gh_cli=use_gh_cli,
        repo_full_name=repo_full_name,
        branch=branch,
        commit_sha=commit_sha,
        log_limit=log_limit,
        pr_number=pr_number,
    )
    artifacts = await _artifacts_from_request(files, combined_text, settings=settings)
    if not artifacts:
        raise HTTPException(status_code=400, detail="Provide at least one file or text input")

    llm_client = LLMClient(settings)
    agent = LogAnalysisAgent(llm_client=llm_client, artifacts=artifacts, log_type="git_operation")
    result = agent.execute()
    return _multimodal_response("git_log_analysis", result, pipeline_run_id=pipeline_run_id)


@router.post("/payment")
async def analyze_payment(
    text_input: str = Form(default=""),
    reconcile: bool = Form(default=False),
    pipeline_run_id: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    user: dict = Depends(require_auth),
) -> dict[str, Any]:
    _ = user
    settings = get_settings()
    artifacts = await _artifacts_from_request(files, text_input, settings=settings)
    if not artifacts:
        raise HTTPException(status_code=400, detail="Provide at least one file or text input")

    llm_client = LLMClient(settings)
    agent = PaymentAgent(llm_client=llm_client, artifacts=artifacts)
    result = agent.execute()
    if reconcile:
        csv_text = text_input
        for artifact in artifacts:
            content = artifact.get("content")
            if artifact.get("type") == "csv" and isinstance(content, str):
                csv_text = content
                break
        result["reconciliation"] = agent.generate_reconciliation_report(csv_text)
    return _multimodal_response("payment_analysis", result, pipeline_run_id=pipeline_run_id)
