"""ObservabilityIntelligenceAgent — deploy correlation and AIOps signal synthesis."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import LLM_ERROR_KEY, BaseAgent
from app.config import settings
from app.utils.artifact_summaries import summarize_artifact
from app.utils.observability_intelligence import build_observability_intelligence_report

SYSTEM_PROMPT = """You are an SRE summarizing production observability after a deployment.
Return ONLY valid JSON:
{
  "summary": string,
  "highlights": [string],
  "risks": [string],
  "recommendations": [string]
}"""


class ObservabilityIntelligenceAgent(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID | str | None,
        db: AsyncSession | None,
        anthropic_client: AsyncAnthropic | None,
        *,
        deployment_info: dict[str, Any] | None = None,
        otel_trace_context: dict[str, Any] | None = None,
        synthetic_monitoring_report: dict[str, Any] | None = None,
        stress_report: dict[str, Any] | None = None,
        error_budget_report: dict[str, Any] | None = None,
        service_graph: dict[str, Any] | None = None,
        monitoring_summary: dict[str, Any] | None = None,
        change_risk_report: dict[str, Any] | None = None,
        historical_synthetic: list[dict[str, Any]] | None = None,
        historical_stress: list[dict[str, Any]] | None = None,
        log_excerpt: str = "",
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.deployment_info = deployment_info
        self.otel_trace_context = otel_trace_context
        self.synthetic_monitoring_report = synthetic_monitoring_report
        self.stress_report = stress_report
        self.error_budget_report = error_budget_report
        self.service_graph = service_graph
        self.monitoring_summary = monitoring_summary
        self.change_risk_report = change_risk_report
        self.historical_synthetic = historical_synthetic
        self.historical_stress = historical_stress
        self.log_excerpt = log_excerpt
        self.agent_model = settings.observability_intelligence_model

    async def execute(self) -> dict[str, Any]:
        report = build_observability_intelligence_report(
            deployment_info=self.deployment_info,
            otel_trace_context=self.otel_trace_context,
            synthetic_monitoring_report=self.synthetic_monitoring_report,
            stress_report=self.stress_report,
            error_budget_report=self.error_budget_report,
            service_graph=self.service_graph,
            monitoring_summary=self.monitoring_summary,
            change_risk_report=self.change_risk_report,
            historical_synthetic=self.historical_synthetic,
            historical_stress=self.historical_stress,
            log_excerpt=self.log_excerpt,
        )

        if settings.llm_enabled and self.anthropic_client is not None:
            prompt = self._prepare_llm_text(
                {
                    "deploy_correlation": report.get("deploy_correlation"),
                    "metric_anomalies": report.get("metric_anomalies"),
                    "log_signals": report.get("log_signals"),
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

        report["summary"] = summarize_artifact("observability_intelligence", report) or report.get("summary", "")
        if self.pipeline_run_id and self.db is not None:
            await self._save_artifact("observability_intelligence", report)
        return report
