"""RepositoryIntelligenceAgent — fingerprinting, stack detection, ownership, licenses."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import LLM_ERROR_KEY, BaseAgent
from app.config import settings
from app.utils.artifact_summaries import summarize_artifact
from app.utils.repository_intelligence import analyze_repository

SYSTEM_PROMPT = """You are a staff engineer summarizing repository intelligence for a DevOps platform.
Given structured JSON about languages, monorepo layout, licenses, service graph, and change impact,
return ONLY valid JSON:
{
  "summary": string (2-3 sentences for engineers),
  "highlights": [string],
  "risks": [string],
  "recommendations": [string]
}"""


class RepositoryIntelligenceAgent(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID | str | None,
        db: AsyncSession | None,
        anthropic_client: AsyncAnthropic | None,
        *,
        repo_path: str,
        repo: str = "",
        commit: str = "",
        changed_files: list[str] | None = None,
        diff_text: str = "",
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.repo_path = repo_path
        self.repo = repo
        self.commit = commit
        self.changed_files = changed_files or []
        self.diff_text = diff_text or ""
        self.agent_model = settings.repository_intelligence_model

    async def execute(self) -> dict[str, Any]:
        report = analyze_repository(
            self.repo_path,
            repo=self.repo,
            commit=self.commit,
            changed_files=self.changed_files,
            diff_text=self.diff_text,
        )
        if report.get("error"):
            return report

        llm_block: dict[str, Any] | None = None
        if settings.llm_enabled and self.anthropic_client is not None:
            prompt = self._prepare_llm_text(
                {
                    "repo": self.repo,
                    "stack": report.get("stack"),
                    "monorepo": report.get("monorepo"),
                    "licenses": report.get("licenses"),
                    "ownership": {
                        "codeowners_found": (report.get("ownership") or {}).get("codeowners_found"),
                        "unowned_changed_paths": (report.get("ownership") or {}).get("unowned_changed_paths"),
                    },
                    "api_surface": report.get("api_surface"),
                    "change_impact": report.get("change_impact"),
                },
                max_chars=12000,
            )
            llm_block = await self._call_claude_json(SYSTEM_PROMPT, prompt)
            if LLM_ERROR_KEY not in llm_block:
                report["analysis_mode"] = "llm"
                if llm_block.get("summary"):
                    report["summary"] = str(llm_block["summary"])
                report["llm_insights"] = {
                    "highlights": llm_block.get("highlights") or [],
                    "risks": llm_block.get("risks") or [],
                    "recommendations": llm_block.get("recommendations") or [],
                }

        report["summary"] = summarize_artifact("repository_intelligence", report) or report.get("summary", "")
        if self.pipeline_run_id and self.db is not None:
            await self._save_artifact("repository_intelligence", report)
        return report
