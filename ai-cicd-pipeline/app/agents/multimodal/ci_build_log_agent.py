import re
from typing import Any

from app.agents.multimodal.base_multimodal_agent import BaseMultimodalAgent, as_text
from app.config import settings

CI_BUILD_SCHEMA = (
    'Return ONLY valid JSON: {"ci_platform": string, "failed_stages": [{"stage": string, "error_type": string, '
    '"error_message": string, "line_number": int, "fix": string}], "root_cause": string, '
    '"retry_recommended": bool, "retry_strategy": string, "severity": string, "summary": string}'
)

_PLATFORM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("jenkins", re.compile(r"\b(Jenkins|\[Pipeline\]|Finished: (FAILURE|UNSTABLE)|hudson\.)\b", re.IGNORECASE)),
    ("gitlab_ci", re.compile(r"\b(gitlab-runner|GitLab CI|ERROR: Job failed)\b", re.IGNORECASE)),
    ("circleci", re.compile(r"\b(CircleCI|circle ci)\b", re.IGNORECASE)),
    ("azure_pipelines", re.compile(r"\b(Azure Pipelines|##\[error\].*Azure)\b", re.IGNORECASE)),
    ("generic_ci", re.compile(r"\b(build failed|pipeline failed|job failed)\b", re.IGNORECASE)),
]

_ERROR_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("test", re.compile(r"FAILED |AssertionError|tests? failed|pytest", re.IGNORECASE), "Fix failing tests locally"),
    ("compile", re.compile(r"error:|compil|ModuleNotFoundError|npm ERR", re.IGNORECASE), "Fix compile/build dependency errors"),
    ("timeout", re.compile(r"timed? ?out|timeout|exceeded the maximum", re.IGNORECASE), "Increase job timeout or optimize step"),
    ("auth", re.compile(r"401|403|unauthorized|permission denied", re.IGNORECASE), "Verify CI secrets and credentials"),
    ("infra", re.compile(r"agent offline|no space left|OOM|killed", re.IGNORECASE), "Check runner capacity and disk/memory"),
]


def detect_ci_platform(text: str) -> str:
    for name, pattern in _PLATFORM_PATTERNS:
        if pattern.search(text):
            return name
    return "unknown"


class CiBuildLogAgent(BaseMultimodalAgent):
    artifact_type = "ci_build_log_analysis"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.agent_model = settings.multimodal_git_model

    def _heuristic(self) -> dict[str, Any]:
        failed_stages: list[dict[str, Any]] = []
        platform = "unknown"
        for art in self.text_artifacts():
            text = as_text(art.get("content", ""))
            platform = detect_ci_platform(text) if platform == "unknown" else platform
            stage = str(art.get("filename") or "build").rsplit(".", 1)[0]
            for lineno, line in enumerate(text.splitlines(), start=1):
                if not re.search(r"\b(error|failed|failure|fatal|panic)\b", line, re.IGNORECASE):
                    continue
                error_type = "unknown"
                fix = "Inspect the failing stage log"
                for etype, pattern, suggestion in _ERROR_PATTERNS:
                    if pattern.search(line):
                        error_type = etype
                        fix = suggestion
                        break
                failed_stages.append(
                    {
                        "stage": stage,
                        "error_type": error_type,
                        "error_message": line.strip()[:300],
                        "line_number": lineno,
                        "fix": fix,
                    }
                )
        retryable = bool(failed_stages) and all(s["error_type"] in {"timeout", "infra"} for s in failed_stages[:3])
        severity = "high" if len(failed_stages) >= 3 else ("medium" if failed_stages else "low")
        return {
            "ci_platform": platform,
            "failed_stages": failed_stages[:25],
            "root_cause": failed_stages[0]["error_message"] if failed_stages else "No CI failures detected",
            "retry_recommended": retryable,
            "retry_strategy": "Re-run failed jobs after runner recovery" if retryable else "Fix root cause before retry",
            "severity": severity,
            "summary": f"{platform} CI: {len(failed_stages)} failure line(s) detected.",
        }

    async def execute(self) -> dict[str, Any]:
        result = await self._analyze_json(
            f"You are a CI/CD engineer analyzing Jenkins, GitLab CI, CircleCI, or generic build logs. {CI_BUILD_SCHEMA}",
            "Identify failed stages, root cause, and retry guidance.",
            self._heuristic(),
            required_key="failed_stages",
            max_tokens=3500,
        )
        return await self._persist(result)
