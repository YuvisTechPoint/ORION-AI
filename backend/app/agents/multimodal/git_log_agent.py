from __future__ import annotations

from typing import Any

from app.agents.multimodal.base_multimodal_agent import BaseMultimodalAgent


class GitLogAgent(BaseMultimodalAgent):
    """Multimodal agent for git/server log analysis."""

    def __init__(self, anthropic_client: Any, artifacts: list[dict[str, Any]]) -> None:
        super().__init__(anthropic_client=anthropic_client, artifacts=artifacts)

    async def execute(self) -> dict:
        system_prompt = (
            "You are an expert DevOps engineer and Site Reliability Engineer specializing in log analysis, debugging, and incident response. "
            "You will receive log files, screenshots of error dashboards, git operation outputs, build logs, and server traces. Analyze everything provided and identify all errors, root causes, and fixes. "
            "You must classify every issue found. Return ONLY valid JSON in this exact schema with no additional text: {\"analysis_type\": string, \"severity\": \"low\"|\"medium\"|\"high\"|\"critical\", \"total_issues_found\": int, \"issues\": [{\"id\": int, \"category\": \"server_timeout\"|\"build_error\"|\"git_error\"|\"dependency_error\"|\"memory_leak\"|\"database_error\"|\"network_error\"|\"auth_error\"|\"syntax_error\"|\"other\", \"title\": string, \"description\": string, \"affected_file_or_service\": string, \"line_number\": int|null, \"error_code\": string|null, \"root_cause\": string, \"exact_fix\": string, \"fix_commands\": [string], \"prevention\": string, \"severity\": \"low\"|\"medium\"|\"high\"|\"critical\"}], \"server_timeout_analysis\": {\"detected\": bool, \"endpoints_affected\": [string], \"average_timeout_ms\": int|null, \"likely_cause\": string|null, \"fix\": string|null}, \"build_error_analysis\": {\"detected\": bool, \"failed_step\": string|null, \"missing_dependencies\": [string], \"incompatible_versions\": [string], \"exact_fix_command\": string|null}, \"git_error_analysis\": {\"detected\": bool, \"error_type\": string|null, \"affected_branch\": string|null, \"resolution_commands\": [string]}, \"performance_issues\": [{\"metric\": string, \"current_value\": string, \"threshold\": string, \"recommendation\": string}], \"immediate_actions\": [string], \"estimated_resolution_minutes\": int, \"summary\": string, \"can_auto_fix\": bool, \"auto_fix_commands\": [string]}"
        )
        user_prompt = (
            "Analyze all provided log files, screenshots, and error outputs. Find every error, timeout, build failure, git issue, and performance problem. "
            "Provide complete root cause analysis and exact fix commands for each issue found."
        )
        return await self._analyze(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=4000)
