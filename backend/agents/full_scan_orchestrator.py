from __future__ import annotations

import asyncio
from typing import Any

from agents.base import BaseAgent
from agents.code_analysis import CodeAnalysisAgent
from agents.security import SecurityAgent
from core.logging_config import get_logger
from core.rule_engine import run_quality_rules, run_security_rules
from services.qa_runner import QARunner


class FullScanOrchestrator(BaseAgent):
    """Runs code, security, and QA checks concurrently without early exit."""

    def __init__(self, llm_client: Any, qa_timeout_seconds: int = 30) -> None:
        super().__init__(llm_client=llm_client, name="full_scan_orchestrator")
        self.logger = get_logger("full_scan_orchestrator")
        self.code_agent = CodeAnalysisAgent(llm_client)
        self.security_agent = SecurityAgent(llm_client)
        self.qa_runner = QARunner(timeout_seconds=qa_timeout_seconds)

    def build_prompt(self, payload: dict[str, Any]) -> str:
        return str(payload)

    async def execute(self, repo_path: str, diff_text: str, pipeline_run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        del repo_path, diff_text, pipeline_run_id

        code_task = asyncio.to_thread(self.code_agent.run, payload)
        security_task = asyncio.to_thread(self.security_agent.run, payload)
        qa_task = asyncio.to_thread(self._run_qa, payload.get("repo_files") or {})

        code_result, security_result, qa_result = await asyncio.gather(
            code_task,
            security_task,
            qa_task,
            return_exceptions=True,
        )

        normalized_code = self._normalize_agent_result("code", code_result)
        normalized_security = self._normalize_agent_result("security", security_result)
        normalized_qa = self._normalize_agent_result("qa", qa_result)

        if isinstance(normalized_code, dict):
            rule_issues = run_quality_rules(
                payload.get("code", ""),
                payload.get("diff", ""),
                payload.get("config_text", ""),
                payload.get("repo_files", {}),
            )
            normalized_code.setdefault("issues", [])
            normalized_code["issues"].extend(rule_issues)

        if isinstance(normalized_security, dict):
            rule_issues = run_security_rules(
                payload.get("code", ""),
                payload.get("diff", ""),
                payload.get("config_text", ""),
                payload.get("repo_files", {}),
            )
            normalized_security.setdefault("issues", [])
            normalized_security["issues"].extend(rule_issues)
            normalized_security["blocked"] = any(
                isinstance(issue, dict) and issue.get("severity") == "high"
                for issue in normalized_security.get("issues", [])
            )

        return {
            "code_issues": normalized_code,
            "security_issues": normalized_security,
            "qa_issues": normalized_qa,
        }

    def _run_qa(self, repo_files: dict[str, str]) -> dict[str, Any]:
        if not repo_files:
            return {"passed": True, "skipped": True, "summary": "QA skipped: repo files not provided", "issues": []}

        qa_result = self.qa_runner.run_pytest(repo_files=repo_files)
        if qa_result.get("passed"):
            qa_result["issues"] = []
            return qa_result

        qa_result["issues"] = [
            {
                "type": "qa_test_failure",
                "severity": "high",
                "line": "n/a",
                "fix": qa_result.get("summary", "Fix failing tests and rerun QA"),
                "snippet": qa_result.get("stderr", "")[:200],
                "file_path": "tests",
            }
        ]
        return qa_result

    def _normalize_agent_result(self, agent_name: str, result: Any) -> dict[str, Any]:
        if isinstance(result, Exception):
            self.logger.error("%s agent failed during full scan: %s", agent_name, result)
            return {"error": str(result), "skipped": True}
        if isinstance(result, dict):
            return result
        return {"error": f"Unexpected {agent_name} result type", "skipped": True}
