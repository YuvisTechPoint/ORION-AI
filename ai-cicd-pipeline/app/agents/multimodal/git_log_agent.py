from typing import Any

from anthropic import AsyncAnthropic

from app.agents.multimodal.base_multimodal_agent import BaseMultimodalAgent

GIT_LOG_SYSTEM = (
    "You are an expert DevOps engineer and Site Reliability Engineer specializing in log analysis, "
    "debugging, and incident response. You will receive log files, screenshots of error dashboards, "
    "git operation outputs, build logs, and server traces. Analyze everything provided and identify "
    "all errors, root causes, and fixes. Return ONLY valid JSON in this exact schema: "
    '{"analysis_type": string, "severity": "low"|"medium"|"high"|"critical", '
    '"total_issues_found": int, "issues": [{"id": int, "category": "server_timeout"|"build_error"|'
    '"git_error"|"dependency_error"|"memory_leak"|"database_error"|"network_error"|"auth_error"|'
    '"syntax_error"|"other", "title": string, "description": string, '
    '"affected_file_or_service": string, "line_number": int|null, "error_code": string|null, '
    '"root_cause": string, "exact_fix": string, "fix_commands": [string], "prevention": string, '
    '"severity": "low"|"medium"|"high"|"critical"}], '
    '"server_timeout_analysis": {"detected": bool, "endpoints_affected": [string], '
    '"average_timeout_ms": int|null, "likely_cause": string|null, "fix": string|null}, '
    '"build_error_analysis": {"detected": bool, "failed_step": string|null, '
    '"missing_dependencies": [string], "incompatible_versions": [string], '
    '"exact_fix_command": string|null}, '
    '"git_error_analysis": {"detected": bool, "error_type": string|null, '
    '"affected_branch": string|null, "resolution_commands": [string]}, '
    '"performance_issues": [{"metric": string, "current_value": string, "threshold": string, '
    '"recommendation": string}], "immediate_actions": [string], '
    '"estimated_resolution_minutes": int, "summary": string, "can_auto_fix": bool, '
    '"auto_fix_commands": [string]}'
)

GIT_LOG_USER = (
    "Analyze all provided log files, screenshots, and error outputs. Find every error, timeout, "
    "build failure, git issue, and performance problem. Provide complete root cause analysis and "
    "exact fix commands for each issue."
)


class GitLogAgent(BaseMultimodalAgent):
    def __init__(
        self, anthropic_client: AsyncAnthropic, artifacts: list[dict[str, Any]]
    ) -> None:
        super().__init__(anthropic_client, artifacts)

    async def execute(self) -> dict[str, Any]:
        return await self._analyze(GIT_LOG_SYSTEM, GIT_LOG_USER, max_tokens=4000)
