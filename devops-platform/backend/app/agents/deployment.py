from __future__ import annotations

import re
import subprocess
import time
import uuid as uuid_lib

from pydantic import BaseModel, Field
from sqlalchemy import desc

from app.agents.base_agent import AgentInput, AgentOutput, BaseAgent
from app.config import get_settings
from app.models import PipelineRun, PipelineStatus, StageResult

_DOCKER_CACHE_SECONDS = 60.0
_docker_state: dict[str, object] = {"ok": False, "checked": None}


def docker_available() -> bool:
    checked = _docker_state["checked"]
    if checked is not None and time.monotonic() - float(checked) < _DOCKER_CACHE_SECONDS:
        return bool(_docker_state["ok"])
    try:
        proc = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        ok = proc.returncode == 0 and bool(proc.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    _docker_state.update(ok=ok, checked=time.monotonic())
    return ok


def resolved_deploy_mode() -> str:
    """docker | simulate | skip.

    auto: use Docker when a daemon is reachable, otherwise simulate deployment.
    """
    mode = get_settings().deploy_mode.strip().lower()
    if mode in ("docker", "skip", "simulate"):
        return mode
    return "docker" if docker_available() else "simulate"


class DeploymentResult(BaseModel):
    deployed_tag: str = ""
    rollback_available: bool = False
    previous_tag: str = ""
    container_id: str = ""
    simulated: bool = False
    skipped: bool = False


class DeploymentAgent(BaseAgent):
    stage_key = "deployment"

    response_model = DeploymentResult

    def _previous_stable_tag(self, pipeline_id, repo_url: str) -> str:
        prev = (
            self.db.query(StageResult)
            .join(PipelineRun, StageResult.pipeline_id == PipelineRun.id)
            .filter(
                PipelineRun.repo_url == repo_url,
                PipelineRun.status == PipelineStatus.COMPLETED,
                PipelineRun.id != pipeline_id,
                StageResult.stage == "deployment",
                StageResult.passed.is_(True),
            )
            .order_by(desc(PipelineRun.updated_at))
            .first()
        )
        if prev and prev.output_json:
            return str(prev.output_json.get("deployed_tag") or "")
        return ""

    def _tag_from_context(self, inp: AgentInput) -> tuple[str, str, str]:
        meta = inp.context.get("metadata_json") or {}
        repo_url = meta.get("repo_url") or ""
        commit = meta.get("commit_sha") or "unknown"
        match = re.search(r"github\.com[:/]([^/]+)/([^/\.]+)", repo_url)
        repo_name = match.group(2) if match else "app"
        tag = f"{repo_name}:{commit[:8]}"
        return repo_url, repo_name, tag

    def _execute_skip(self, inp: AgentInput, tag: str, prev_tag: str) -> AgentOutput:
        result = DeploymentResult(
            deployed_tag=tag,
            rollback_available=bool(prev_tag),
            previous_tag=prev_tag,
            skipped=True,
        )
        self.write_log(inp.pipeline_id, "DEPLOYMENT", "INFO", "Deployment skipped (DEPLOY_MODE=skip)")
        self.emit_artifact(inp.pipeline_id, "deployment", result.model_dump())
        return AgentOutput(
            passed=True,
            summary="Deployment skipped by policy",
            artifacts={"deployment": result.model_dump()},
            next_context={"deployment": result.model_dump()},
        )

    def _execute_simulated(self, inp: AgentInput, tag: str, prev_tag: str) -> AgentOutput:
        cid = f"simulated_{uuid_lib.uuid4().hex[:8]}"
        result = DeploymentResult(
            deployed_tag=tag,
            rollback_available=bool(prev_tag),
            previous_tag=prev_tag,
            container_id=cid,
            simulated=True,
        )
        self.write_log(
            inp.pipeline_id,
            "DEPLOYMENT",
            "INFO",
            f"Simulated deploy {tag} as {cid} (no Docker daemon required)",
        )
        self.emit_artifact(inp.pipeline_id, "deployment", result.model_dump())
        return AgentOutput(
            passed=True,
            summary=f"Simulated deployment of {tag}",
            artifacts={"deployment": result.model_dump()},
            next_context={"deployment": result.model_dump()},
        )

    def _execute_docker(self, inp: AgentInput, workdir: str, tag: str, prev_tag: str) -> AgentOutput:
        result = DeploymentResult(deployed_tag=tag, rollback_available=bool(prev_tag), previous_tag=prev_tag)
        self.write_log(inp.pipeline_id, "DEPLOYMENT", "INFO", f"Building image {tag}")

        try:
            build = subprocess.run(
                ["docker", "build", "-t", tag, "."],
                cwd=workdir,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
        except Exception as exc:
            self.write_log(inp.pipeline_id, "DEPLOYMENT", "ERROR", f"docker build failed: {exc}")
            if prev_tag:
                self.write_log(inp.pipeline_id, "DEPLOYMENT", "INFO", f"Rolling back to {prev_tag}")
            return AgentOutput(
                passed=False,
                summary=str(exc),
                artifacts={"deployment": result.model_dump()},
                next_context={},
            )

        if build.returncode != 0:
            detail = (build.stderr or build.stdout or "")[-500:]
            self.write_log(inp.pipeline_id, "DEPLOYMENT", "ERROR", f"docker build failed: {detail}")
            return AgentOutput(
                passed=False,
                summary="docker build failed",
                artifacts={"deployment": result.model_dump()},
                next_context={},
            )

        cid = f"{tag.split(':')[0]}_live_{uuid_lib.uuid4().hex[:8]}"
        try:
            run = subprocess.run(
                ["docker", "run", "-d", "--name", cid, tag],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
        except Exception as exc:
            self.write_log(inp.pipeline_id, "DEPLOYMENT", "ERROR", f"docker run failed: {exc}")
            return AgentOutput(
                passed=False,
                summary=str(exc),
                artifacts={"deployment": result.model_dump()},
                next_context={},
            )

        if run.returncode != 0:
            detail = (run.stderr or run.stdout or "")[-500:]
            self.write_log(inp.pipeline_id, "DEPLOYMENT", "ERROR", f"docker run failed: {detail}")
            return AgentOutput(
                passed=False,
                summary="docker run failed",
                artifacts={"deployment": result.model_dump()},
                next_context={},
            )

        result.container_id = cid
        self.emit_artifact(inp.pipeline_id, "deployment", result.model_dump())
        self.write_log(inp.pipeline_id, "DEPLOYMENT", "INFO", f"Deployed {tag} as {cid}")
        return AgentOutput(
            passed=True,
            summary=f"Deployed {tag}",
            artifacts={"deployment": result.model_dump()},
            next_context={"deployment": result.model_dump()},
        )

    def run(self, inp: AgentInput) -> AgentOutput:
        meta = inp.context.get("metadata_json") or {}
        workdir = inp.context.get("temp_dir") or meta.get("temp_dir") or "."
        repo_url, _repo_name, tag = self._tag_from_context(inp)
        prev_tag = self._previous_stable_tag(inp.pipeline_id, repo_url)
        mode = resolved_deploy_mode()

        if mode == "skip":
            return self._execute_skip(inp, tag, prev_tag)
        if mode == "simulate":
            return self._execute_simulated(inp, tag, prev_tag)
        return self._execute_docker(inp, workdir, tag, prev_tag)
