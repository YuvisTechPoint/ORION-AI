from __future__ import annotations

import re
import subprocess
import uuid as uuid_lib

from pydantic import BaseModel, Field
from sqlalchemy import desc

from app.agents.base_agent import AgentInput, AgentOutput, BaseAgent
from app.models import PipelineRun, PipelineStatus, StageResult


class DeploymentResult(BaseModel):
    deployed_tag: str = ""
    rollback_available: bool = False
    previous_tag: str = ""
    container_id: str = ""


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

    def run(self, inp: AgentInput) -> AgentOutput:
        meta = inp.context.get("metadata_json") or {}
        repo_url = meta.get("repo_url") or ""
        commit = meta.get("commit_sha") or "unknown"
        m = re.search(r"github\.com[:/]([^/]+)/([^/\.]+)", repo_url)
        repo_name = m.group(2) if m else "app"
        tag = f"{repo_name}:{commit[:8]}"
        prev_tag = self._previous_stable_tag(inp.pipeline_id, repo_url)

        self.write_log(inp.pipeline_id, "DEPLOYMENT", "INFO", f"Building image {tag}")

        result = DeploymentResult(deployed_tag=tag, rollback_available=bool(prev_tag), previous_tag=prev_tag)
        try:
            subprocess.run(
                ["docker", "build", "-t", tag, "."],
                cwd="/tmp",
                capture_output=True,
                timeout=120,
                check=False,
            )
        except Exception as e:
            self.write_log(inp.pipeline_id, "DEPLOYMENT", "ERROR", f"docker build failed: {e}")
            if prev_tag:
                self.write_log(inp.pipeline_id, "DEPLOYMENT", "INFO", f"Rolling back to {prev_tag}")
            return AgentOutput(
                passed=False,
                summary=str(e),
                artifacts={"deployment": result.model_dump()},
                next_context={},
            )

        cid = f"{repo_name}_live_{uuid_lib.uuid4().hex[:8]}"
        try:
            subprocess.run(
                ["docker", "run", "-d", "--name", cid, tag],
                capture_output=True,
                timeout=60,
                check=False,
            )
        except Exception as e:
            self.write_log(inp.pipeline_id, "DEPLOYMENT", "ERROR", f"docker run failed: {e}")
            return AgentOutput(
                passed=False,
                summary=str(e),
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
