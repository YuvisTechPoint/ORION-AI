import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.code_analysis_agent import CodeAnalysisAgent
from app.agents.qa_agent import QAAgent
from app.agents.security_agent import SecurityAgent

AgentCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]


class FullScanOrchestrator(BaseAgent):
    """Runs code, security and QA analysis concurrently and never exits early."""

    LABELS = ("code_issues", "security_issues", "qa_issues")

    def __init__(
        self,
        pipeline_run_id: UUID,
        db: AsyncSession,
        anthropic_client: AsyncAnthropic | None,
        repo_path: str,
        diff_text: str,
        changed_files: list[str] | None = None,
        on_agent_complete: AgentCallback | None = None,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.repo_path = repo_path
        self.diff_text = diff_text
        self.changed_files = changed_files or []
        self.on_agent_complete = on_agent_complete

    async def _run(self, label: str, agent: BaseAgent) -> dict[str, Any]:
        result = await agent.execute()
        if self.on_agent_complete is not None:
            maybe = self.on_agent_complete(label, result)
            if asyncio.iscoroutine(maybe):
                await maybe
        return result

    async def execute(self) -> dict[str, Any]:
        agents = (
            CodeAnalysisAgent(self.pipeline_run_id, self.db, self.anthropic_client, self.repo_path, self.diff_text),
            SecurityAgent(self.pipeline_run_id, self.db, self.anthropic_client, self.repo_path, self.diff_text),
            QAAgent(
                self.pipeline_run_id,
                self.db,
                self.anthropic_client,
                self.repo_path,
                self.diff_text,
                self.changed_files,
            ),
        )
        results = await asyncio.gather(
            *[self._run(label, agent) for label, agent in zip(self.LABELS, agents, strict=True)],
            return_exceptions=True,
        )

        combined_issues: dict[str, Any] = {}
        for label, result in zip(self.LABELS, results, strict=True):
            if isinstance(result, BaseException):
                self.logger.error("%s agent failed: %s", label, result)
                combined_issues[label] = {"error": str(result), "skipped": True}
            else:
                combined_issues[label] = result

        await self._save_artifact("full_scan_combined", combined_issues, duration_seconds=self.elapsed_seconds)
        return combined_issues
