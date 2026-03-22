import asyncio
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.code_analysis_agent import CodeAnalysisAgent
from app.agents.qa_agent import QAAgent
from app.agents.security_agent import SecurityAgent


class FullScanOrchestrator(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID,
        db: AsyncSession,
        anthropic_client: AsyncAnthropic,
        repo_path: str,
        diff_text: str,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.repo_path = repo_path
        self.diff_text = diff_text

    async def execute(self) -> dict[str, Any]:
        code_agent = CodeAnalysisAgent(
            self.pipeline_run_id,
            self.db,
            self.anthropic_client,
            self.repo_path,
            self.diff_text,
        )
        sec_agent = SecurityAgent(
            self.pipeline_run_id,
            self.db,
            self.anthropic_client,
            self.repo_path,
            self.diff_text,
        )
        qa_agent = QAAgent(
            self.pipeline_run_id,
            self.db,
            self.anthropic_client,
            self.repo_path,
        )

        results = await asyncio.gather(
            code_agent.execute(),
            sec_agent.execute(),
            qa_agent.execute(),
            return_exceptions=True,
        )

        combined_issues: dict[str, Any] = {}
        labels = ("code_issues", "security_issues", "qa_issues")
        for label, res in zip(labels, results, strict=True):
            if isinstance(res, BaseException):
                combined_issues[label] = {"error": str(res), "skipped": True}
            else:
                combined_issues[label] = res

        await self._save_artifact(
            "full_scan_combined",
            combined_issues,
            duration_seconds=self.elapsed_seconds,
        )
        return combined_issues
