"""TestIntelligenceAgent — selection, flaky, coverage, and mutation heuristics."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import LLM_ERROR_KEY, BaseAgent
from app.config import settings
from app.utils.artifact_summaries import summarize_artifact
from app.utils.test_intelligence import build_test_intelligence_report

SYSTEM_PROMPT = """You are a staff QA engineer summarizing test intelligence for CI/CD.
Return ONLY valid JSON:
{
  "summary": string,
  "highlights": [string],
  "risks": [string],
  "recommendations": [string]
}"""


class TestIntelligenceAgent(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID | str | None,
        db: AsyncSession | None,
        anthropic_client: AsyncAnthropic | None,
        *,
        repo_path: str,
        changed_files: list[str] | None = None,
        qa_current: dict[str, Any] | None = None,
        historical_qa: list[dict[str, Any]] | None = None,
        contract_report: dict[str, Any] | None = None,
        test_generation: dict[str, Any] | None = None,
        run_live_coverage: bool = False,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.repo_path = repo_path
        self.changed_files = changed_files or []
        self.qa_current = qa_current
        self.historical_qa = historical_qa or []
        self.contract_report = contract_report
        self.test_generation = test_generation
        self.run_live_coverage = run_live_coverage
        self.agent_model = settings.test_intelligence_model

    async def execute(self) -> dict[str, Any]:
        report = build_test_intelligence_report(
            self.repo_path,
            changed_files=self.changed_files,
            qa_current=self.qa_current,
            historical_qa=self.historical_qa,
            contract_report=self.contract_report,
            test_generation=self.test_generation,
            run_live_coverage=self.run_live_coverage,
        )

        if settings.llm_enabled and self.anthropic_client is not None:
            prompt = self._prepare_llm_text(
                {
                    "selection_mode": report.get("mode"),
                    "flaky": report.get("flaky_analysis"),
                    "coverage": report.get("coverage_regression"),
                    "mutation_targets": (report.get("mutation_targets") or {}).get("target_count"),
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

        report["summary"] = summarize_artifact("test_intelligence", report) or report.get("summary", "")
        if self.pipeline_run_id and self.db is not None:
            await self._save_artifact("test_intelligence", report)
        return report
