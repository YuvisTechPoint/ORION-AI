"""AI Software Engineer — autonomous detect/diagnose/fix/verify orchestration."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.services.auto_pr_service import IssueBundle
from app.services.fix_loop_service import run_fix_loop


class SoftwareEngineerAgent(BaseAgent):
    """Wraps autonomous fix loop with artifact persistence (Phase 2)."""

    artifact_type = "fix_loop_report"

    async def execute(
        self,
        repo_path: str,
        bundles: list[IssueBundle],
        *,
        security_passed: bool = True,
        qa_verdict: str = "pass",
    ) -> dict[str, Any]:
        report = run_fix_loop(
            repo_path,
            bundles,
            security_passed=security_passed,
            qa_verdict=qa_verdict,
        )
        await self._save_artifact(self.artifact_type, report, duration_seconds=self.elapsed_seconds)
        confidence = report.get("aggregate_confidence") or {}
        await self._save_artifact("patch_confidence_report", confidence)
        return report
