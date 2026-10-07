"""RemediationIntelligenceAgent — L0–L6 autonomy summary with optional LLM."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import LLM_ERROR_KEY, BaseAgent
from app.config import settings
from app.utils.artifact_summaries import summarize_artifact
from app.utils.remediation_intelligence import build_remediation_intelligence_report


SYSTEM_PROMPT = """You are an autonomous remediation engineer summarizing fix-loop outcomes.
Return ONLY valid JSON:
{
  "summary": string,
  "highlights": [string],
  "risks": [string],
  "next_steps": [string]
}"""


class RemediationIntelligenceAgent(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID | str | None,
        db: AsyncSession | None,
        anthropic_client: AsyncAnthropic | None,
        *,
        run: dict[str, Any],
        artifacts: dict[str, dict[str, Any]],
        fix_loop_report: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.run = run
        self.artifacts = artifacts
        self.fix_loop_report = fix_loop_report
        self.agent_model = settings.remediation_intelligence_model

    async def execute(self) -> dict[str, Any]:
        report = build_remediation_intelligence_report(
            run=self.run,
            artifacts=self.artifacts,
            fix_loop_report=self.fix_loop_report,
        )

        if settings.llm_enabled and self.anthropic_client is not None:
            prompt = self._prepare_llm_text(
                {
                    "autonomy": report.get("autonomy"),
                    "recommend": report.get("recommend"),
                    "patch": report.get("patch"),
                    "auto_pr": report.get("auto_pr"),
                    "gate_verdict": report.get("gate_verdict"),
                },
                max_chars=8000,
            )
            llm = await self._call_claude_json(SYSTEM_PROMPT, prompt)
            if LLM_ERROR_KEY not in llm:
                report["analysis_mode"] = "llm"
                if llm.get("summary"):
                    report["summary"] = str(llm["summary"])
                report["llm_insights"] = {
                    "highlights": llm.get("highlights") or [],
                    "risks": llm.get("risks") or [],
                    "next_steps": llm.get("next_steps") or [],
                }

        report["summary"] = summarize_artifact("remediation_intelligence", report) or report.get("summary", "")
        if self.pipeline_run_id and self.db is not None:
            await self._save_artifact("remediation_intelligence", report)
        return report
