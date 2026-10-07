"""DeploymentIntelligenceAgent — strategy, environments, and SLO rollback analysis."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import LLM_ERROR_KEY, BaseAgent
from app.config import settings
from app.utils.artifact_summaries import summarize_artifact
from app.utils.deployment_intelligence import build_deployment_intelligence_report

SYSTEM_PROMPT = """You are a deployment/SRE engineer summarizing release intelligence.
Return ONLY valid JSON:
{
  "summary": string,
  "highlights": [string],
  "risks": [string],
  "recommendations": [string]
}"""


class DeploymentIntelligenceAgent(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID | str | None,
        db: AsyncSession | None,
        anthropic_client: AsyncAnthropic | None,
        *,
        deployment_info: dict[str, Any] | None = None,
        progressive_delivery: dict[str, Any] | None = None,
        error_budget_report: dict[str, Any] | None = None,
        stress_report: dict[str, Any] | None = None,
        change_risk_report: dict[str, Any] | None = None,
        rollback_intelligence: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.deployment_info = deployment_info or {}
        self.progressive_delivery = progressive_delivery
        self.error_budget_report = error_budget_report
        self.stress_report = stress_report
        self.change_risk_report = change_risk_report
        self.rollback_intelligence = rollback_intelligence
        self.agent_model = settings.deployment_intelligence_model

    async def execute(self) -> dict[str, Any]:
        report = build_deployment_intelligence_report(
            deployment_info=self.deployment_info,
            progressive_delivery=self.progressive_delivery,
            error_budget_report=self.error_budget_report,
            stress_report=self.stress_report,
            change_risk_report=self.change_risk_report,
            rollback_intelligence=self.rollback_intelligence,
        )

        if settings.llm_enabled and self.anthropic_client is not None:
            prompt = self._prepare_llm_text(
                {
                    "deployment": report.get("deployment"),
                    "strategy": report.get("strategy"),
                    "slo_rollback": report.get("slo_rollback"),
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
                    "recommendations": llm.get("recommendations") or [],
                }

        report["summary"] = summarize_artifact("deployment_intelligence", report) or report.get("summary", "")
        if self.pipeline_run_id and self.db is not None:
            await self._save_artifact("deployment_intelligence", report)
        return report
