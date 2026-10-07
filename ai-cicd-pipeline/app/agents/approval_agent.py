import json
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import LLM_ERROR_KEY, BaseAgent
from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.severity import exceeds_threshold

SYSTEM_PROMPT = """You are a principal engineer making a deployment approval decision.
Review all pipeline results and decide whether to approve deployment to production.
Apply these rules strictly:
- REJECT if any security finding is high or critical severity
- REJECT if test failure rate > 0%
- REJECT if p95 response time > 2000ms under load
- REJECT if code analysis severity is "fail"
- APPROVE with warnings if there are minor warnings but no critical issues
Return ONLY valid JSON:
{
  "decision": "approved"|"rejected",
  "confidence": float (0.0-1.0),
  "reason": string (one sentence),
  "warnings": [string],
  "approval_conditions": [string],
  "risk_level": "low"|"medium"|"high"
}
Return ONLY valid JSON."""


class ApprovalAgent(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID,
        db: AsyncSession,
        anthropic_client: AsyncAnthropic,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.agent_model = settings.approval_model

    async def _build_summary(self) -> dict[str, Any]:
        async with self._db_lock():
            rows = (
                await self.db.execute(
                    select(PipelineArtifact)
                    .where(PipelineArtifact.pipeline_run_id == self.pipeline_run_id)
                    .order_by(PipelineArtifact.created_at)
                )
            ).scalars().all()
            run = (
                await self.db.execute(select(PipelineRun).where(PipelineRun.id == self.pipeline_run_id))
            ).scalar_one_or_none()
        latest = {a.artifact_type: a.content or {} for a in rows}
        code = latest.get("code_analysis", {})
        sec = latest.get("security_scan", {})
        qa = latest.get("qa_report", {})
        stress = latest.get("stress_report", {})
        return {
            "code_analysis": {
                "severity": code.get("severity"),
                "critical_issues_count": code.get("critical_issues_count"),
                "warnings_count": code.get("warnings_count"),
                "summary": code.get("summary"),
            },
            "security": {
                "highest_severity": sec.get("highest_severity"),
                "high_critical_count": sec.get("high_critical_count"),
                "security_score": sec.get("security_score"),
                "summary": sec.get("summary"),
            },
            "qa": {
                "verdict": qa.get("verdict"),
                "test_summary": qa.get("test_summary"),
                "summary": qa.get("summary"),
            },
            "stress": {
                "performance_verdict": stress.get("performance_verdict"),
                "p95_ms": stress.get("p95_ms"),
                "error_rate_pct": stress.get("error_rate_pct"),
                "summary": stress.get("summary"),
                "skipped": stress.get("skipped", False),
            },
            "has_warnings": bool(run.has_warnings) if run else False,
        }

    @staticmethod
    def hard_rule_violations(summary: dict[str, Any]) -> list[str]:
        violations = []
        if str(summary["code_analysis"].get("severity", "")).lower() == "fail":
            violations.append("code analysis severity is fail")
        if exceeds_threshold(summary["security"].get("highest_severity"), settings.max_security_severity):
            violations.append(
                f"security severity {summary['security'].get('highest_severity')} exceeds "
                f"{settings.max_security_severity}"
            )
        if str(summary["qa"].get("verdict", "")).lower() == "fail":
            violations.append("tests failed")
        if str(summary["stress"].get("performance_verdict", "")).lower() == "fail":
            violations.append("load test failed")
        return violations

    async def execute(self) -> dict[str, Any]:
        summary = await self._build_summary()
        violations = self.hard_rule_violations(summary)
        if violations:
            result = {
                "decision": "rejected",
                "confidence": 1.0,
                "reason": "Hard rule violated: " + "; ".join(violations),
                "warnings": [],
                "approval_conditions": [],
                "risk_level": "high",
                "blocked_by": "rule_engine",
            }
            await self._save_artifact("approval", result, duration_seconds=self.elapsed_seconds)
            return result

        warnings = []
        if summary["has_warnings"]:
            warnings.append("Pipeline recorded non-blocking warnings.")
        if summary["stress"].get("skipped"):
            warnings.append("Load testing was skipped.")
        fallback = {
            "decision": "approved",
            "confidence": 0.8,
            "reason": "All automated quality gates passed.",
            "warnings": warnings,
            "approval_conditions": ["Monitor the deployment for the observation window."],
            "risk_level": "medium" if warnings else "low",
            "blocked_by": None,
            "analysis_mode": "heuristic",
        }

        user_message = f"PIPELINE RESULTS:\n{json.dumps(summary, indent=2, default=str)}"
        result = await self._call_claude_json(SYSTEM_PROMPT, user_message, max_tokens=1500)
        if LLM_ERROR_KEY in result or str(result.get("decision", "")).lower() not in ("approved", "rejected"):
            result = fallback
        else:
            for key, value in fallback.items():
                result.setdefault(key, value)
            result["blocked_by"] = "llm" if result["decision"] == "rejected" else None
            result["analysis_mode"] = "llm"
        result["pipeline_summary"] = summary

        await self._save_artifact("approval", result, duration_seconds=self.elapsed_seconds)
        return result
