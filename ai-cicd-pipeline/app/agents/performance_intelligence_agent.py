"""PerformanceIntelligenceAgent — baseline comparison and profile recommendations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import LLM_ERROR_KEY, BaseAgent
from app.config import settings
from app.utils.artifact_summaries import summarize_artifact
from app.utils.performance_intelligence import build_performance_intelligence_report


SYSTEM_PROMPT = """You are a performance engineer summarizing load-test intelligence.
Return ONLY valid JSON:
{
  "summary": string,
  "highlights": [string],
  "risks": [string],
  "recommendations": [string]
}"""


class PerformanceIntelligenceAgent(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID | str | None,
        db: AsyncSession | None,
        anthropic_client: AsyncAnthropic | None,
        *,
        stress_report: dict[str, Any],
        historical_stress: list[dict[str, Any]] | None = None,
        profile: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.stress_report = stress_report
        self.historical_stress = historical_stress or []
        self.profile = profile
        self.agent_model = settings.performance_intelligence_model

    async def execute(self) -> dict[str, Any]:
        report = build_performance_intelligence_report(
            self.stress_report,
            historical_stress=self.historical_stress,
            profile=self.profile,
        )

        if settings.llm_enabled and self.anthropic_client is not None:
            prompt = self._prepare_llm_text(
                {
                    "current": report.get("current"),
                    "baseline": report.get("baseline_comparison"),
                    "gate_verdict": report.get("gate_verdict"),
                    "recommended_profiles": report.get("recommended_profiles"),
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
                    "recommendations": llm.get("recommendations") or [],
                }

        report["summary"] = summarize_artifact("performance_intelligence", report) or report.get("summary", "")
        if self.pipeline_run_id and self.db is not None:
            await self._save_artifact("performance_intelligence", report)
        return report
