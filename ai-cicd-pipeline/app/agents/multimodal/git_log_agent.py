from typing import Any

from app.agents.multimodal.base_multimodal_agent import BaseMultimodalAgent
from app.agents.multimodal.log_analysis_agent import scan_log_lines, severity_from_counts
from app.config import settings

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


def _category(line: str) -> str:
    low = line.lower()
    if "timeout" in low or "timed out" in low:
        return "server_timeout"
    if "conflict" in low or "detached head" in low or "fatal:" in low:
        return "git_error"
    if "no module named" in low or "could not find a version" in low:
        return "dependency_error"
    if "memoryerror" in low or "out of memory" in low or "oomkilled" in low:
        return "memory_leak"
    if "syntaxerror" in low:
        return "syntax_error"
    if "401" in low or "403" in low or "permission denied" in low:
        return "auth_error"
    if "connection refused" in low or "econnreset" in low:
        return "network_error"
    if "psycopg" in low or "sqlalchemy" in low or "database" in low:
        return "database_error"
    if "build" in low or "error:" in low:
        return "build_error"
    return "other"


class GitLogAgent(BaseMultimodalAgent):
    artifact_type = "log_analysis"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.agent_model = settings.multimodal_git_model

    def _heuristic(self) -> dict[str, Any]:
        scan = scan_log_lines(self.combined_text())
        issues = [
            {
                "id": idx,
                "category": _category(line),
                "title": line[:80],
                "description": line,
                "affected_file_or_service": "",
                "line_number": None,
                "error_code": None,
                "root_cause": line,
                "exact_fix": "",
                "fix_commands": [],
                "prevention": "",
                "severity": "medium",
            }
            for idx, line in enumerate(dict.fromkeys(scan["errors"]), start=1)
        ][:50]
        categories = {i["category"] for i in issues}
        severity = severity_from_counts(len(scan["errors"]))
        return {
            "analysis_type": "git_and_server_logs",
            "severity": severity,
            "total_issues_found": len(issues),
            "issues": issues,
            "server_timeout_analysis": {"detected": "server_timeout" in categories, "endpoints_affected": [],
                                        "average_timeout_ms": None, "likely_cause": None, "fix": None},
            "build_error_analysis": {"detected": bool(categories & {"build_error", "dependency_error"}),
                                     "failed_step": None, "missing_dependencies": [], "incompatible_versions": [],
                                     "exact_fix_command": scan["fixes"][0] if scan["fixes"] else None},
            "git_error_analysis": {"detected": "git_error" in categories, "error_type": None,
                                   "affected_branch": None, "resolution_commands": []},
            "performance_issues": [],
            "immediate_actions": scan["fixes"],
            "estimated_resolution_minutes": 30 if issues else 0,
            "summary": f"{len(issues)} distinct error(s) detected.",
            "can_auto_fix": bool(scan["fixes"]),
            "auto_fix_commands": scan["fixes"],
        }

    async def execute(self) -> dict[str, Any]:
        result = await self._analyze_json(GIT_LOG_SYSTEM, GIT_LOG_USER, self._heuristic(), "issues", max_tokens=4000)
        return await self._persist(result)
