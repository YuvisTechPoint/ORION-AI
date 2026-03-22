import json
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.models.pipeline_artifact import PipelineArtifact


class ApprovalAgent(BaseAgent):
    async def execute(self) -> dict[str, Any]:
        r = await self.db.execute(
            select(PipelineArtifact).where(
                PipelineArtifact.pipeline_run_id == self.pipeline_run_id
            )
        )
        artifacts = list(r.scalars().all())
        payload = {a.artifact_type: a.content for a in artifacts}

        security = payload.get("security_scan") or {}
        qa = payload.get("qa_report") or {}
        code = payload.get("code_analysis") or {}

        highest = str(security.get("highest_severity", "")).lower()
        if highest in ("critical", "high"):
            out = {
                "decision": "rejected",
                "confidence": 1.0,
                "reason": "Critical or high security findings require manual review.",
                "warnings": [],
                "risk_level": "high",
            }
            await self._save_artifact("approval", out, duration_seconds=self.elapsed_seconds)
            return out

        if str(qa.get("verdict", "")).lower() == "fail":
            out = {
                "decision": "rejected",
                "confidence": 1.0,
                "reason": "Automated tests failed.",
                "warnings": [],
                "risk_level": "high",
            }
            await self._save_artifact("approval", out, duration_seconds=self.elapsed_seconds)
            return out

        if str(code.get("severity", "")).lower() == "fail":
            out = {
                "decision": "rejected",
                "confidence": 0.95,
                "reason": "Code analysis reported failing severity.",
                "warnings": code.get("issues", []),
                "risk_level": "medium",
            }
            await self._save_artifact("approval", out, duration_seconds=self.elapsed_seconds)
            return out

        user = json.dumps(
            {
                "artifacts": {k: v for k, v in payload.items()},
            }
        )[:24000]
        system = (
            "You are a release manager. Decide whether to approve deployment. "
            "Return JSON with decision (approved|rejected), confidence (0-1), reason (string), "
            "warnings (list of strings), risk_level (low|medium|high)."
        )
        out = await self._call_claude_json(system, user, max_tokens=1500)
        if "decision" not in out:
            out = {
                "decision": "approved",
                "confidence": 0.8,
                "reason": "Default approval after automated gates passed.",
                "warnings": [],
                "risk_level": "low",
            }
        await self._save_artifact("approval", out, duration_seconds=self.elapsed_seconds)
        return out
