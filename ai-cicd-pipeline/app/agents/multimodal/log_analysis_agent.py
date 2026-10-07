import re
from typing import Any

from app.agents.multimodal.base_multimodal_agent import BaseMultimodalAgent, as_text
from app.config import settings
from app.utils.text_analysis import (
    classify_log_type,
    extract_error_signatures,
    extract_log_timeline,
    tail_lines,
)

LOG_SCHEMA = (
    'Return ONLY valid JSON: {"log_type": string, "root_cause": string, "affected_components": [string], '
    '"error_timeline": [{"timestamp": string, "event": string, "severity": string}], '
    '"exact_fix_commands": [string], "preventive_measures": [string], "severity": string, '
    '"estimated_resolution_time_minutes": int, "summary": string}'
)

LOG_TYPE_INSTRUCTIONS: dict[str, str] = {
    "server_timeout": (
        "You are a senior SRE analyzing server timeout traces. Identify which endpoints are timing out, "
        "which database queries are slow, whether connection pool exhaustion is occurring, and produce a "
        "concrete fix plan."
    ),
    "build_error": (
        "You are a build engineer analyzing failed build logs. Identify the exact line causing the build "
        "failure, missing dependencies, and incompatible versions, and suggest the exact `pip install` or "
        "`apt-get` command that fixes it."
    ),
    "git_operation": (
        "You are a Git expert analyzing git operation logs. Identify merge conflicts, detached HEAD states, "
        "and corrupted refs, and provide the exact git commands to resolve them."
    ),
    "deployment_crash": (
        "You are a platform engineer analyzing a crashed deployment. Identify why the process or container "
        "crashed (OOM kills, missing configuration, failed migrations, port conflicts, bad entrypoints), "
        "and give the exact commands to recover and redeploy safely."
    ),
    "memory_leak": (
        "You are a performance engineer analyzing memory growth. Identify which process or function is "
        "leaking, estimate the leak rate per hour, and state whether a restart schedule is needed."
    ),
}
VALID_LOG_TYPES = tuple(LOG_TYPE_INSTRUCTIONS)

_ERROR_RE = re.compile(r"\b(ERROR|FATAL|CRITICAL|Traceback|Exception|panic|failed|timed? ?out)\b", re.IGNORECASE)
_WARN_RE = re.compile(r"\b(WARN|WARNING)\b", re.IGNORECASE)
_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)")
_COMPONENT_RE = re.compile(r"\[([A-Za-z0-9_.\-/]{3,40})\]|\b([a-z][a-z0-9_\-]+(?:-service|-api|-worker))\b")

_DEFAULT_FIXES: dict[str, list[str]] = {
    "server_timeout": [
        "Inspect slow queries: SELECT query, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;",
        "Increase the DB connection pool size or add pool_pre_ping=True",
    ],
    "build_error": ["pip install -r requirements.txt --no-cache-dir", "pip check"],
    "git_operation": ["git status", "git fetch --all --prune", "git checkout <branch>"],
    "deployment_crash": ["docker logs --tail 200 <container>", "docker inspect <container> --format '{{.State.OOMKilled}}'"],
    "memory_leak": ["ps aux --sort=-rss | head -n 10", "py-spy dump --pid <pid>"],
}

_PATTERN_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"No module named '([\w.\-]+)'"), "pip install {0}"),
    (re.compile(r"ModuleNotFoundError: No module named '([\w.\-]+)'"), "pip install {0}"),
    (re.compile(r"Unable to locate package ([\w.\-]+)"), "apt-get update && apt-get install -y {0}"),
    (re.compile(r"CONFLICT \(content\): Merge conflict in (\S+)"), "git checkout --theirs {0} && git add {0}"),
    (re.compile(r"HEAD detached at (\S+)"), "git switch -c recovery-branch {0}"),
    (re.compile(r"QueuePool limit of size \d+ overflow \d+ reached"), "Raise pool_size/max_overflow and release sessions promptly"),
]


def scan_log_lines(text: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings = 0
    timeline: list[dict[str, str]] = []
    components: dict[str, int] = {}
    fixes: list[str] = []
    for line in text.splitlines():
        is_error = bool(_ERROR_RE.search(line))
        if _WARN_RE.search(line) and not is_error:
            warnings += 1
        if not is_error:
            continue
        errors.append(line.strip()[:300])
        ts = _TS_RE.search(line)
        if ts and len(timeline) < 50:
            timeline.append({"timestamp": ts.group(1), "event": line.strip()[:200], "severity": "high"})
        for match in _COMPONENT_RE.finditer(line):
            name = match.group(1) or match.group(2)
            components[name] = components.get(name, 0) + 1
        for pattern, template in _PATTERN_FIXES:
            m = pattern.search(line)
            if m:
                cmd = template.format(*m.groups())
                if cmd not in fixes:
                    fixes.append(cmd)
    return {
        "errors": errors,
        "warning_count": warnings,
        "timeline": timeline,
        "components": [c for c, _ in sorted(components.items(), key=lambda kv: -kv[1])[:10]],
        "fixes": fixes,
    }


def severity_from_counts(error_count: int) -> str:
    if error_count >= 50:
        return "critical"
    if error_count >= 10:
        return "high"
    if error_count > 0:
        return "medium"
    return "low"


class LogAnalysisAgent(BaseMultimodalAgent):
    artifact_type = "log_analysis"

    def __init__(self, *args: Any, log_type: str = "server_timeout", **kwargs: Any) -> None:
        if log_type not in LOG_TYPE_INSTRUCTIONS:
            raise ValueError(f"log_type must be one of {', '.join(VALID_LOG_TYPES)}")
        super().__init__(*args, **kwargs)
        self.log_type = log_type
        self.agent_model = settings.multimodal_git_model
        for art in self.artifacts:
            if art.get("type") in ("text", "log", "csv"):
                art["content"] = tail_lines(as_text(art.get("content", "")))

    def system_prompt(self) -> str:
        return f"{LOG_TYPE_INSTRUCTIONS[self.log_type]} {LOG_SCHEMA}"

    def _heuristic(self) -> dict[str, Any]:
        scan = scan_log_lines(self.combined_text())
        errors = scan["errors"]
        severity = severity_from_counts(len(errors))
        detected = classify_log_type(self.combined_text())
        return {
            "log_type": self.log_type,
            "detected_log_type": detected,
            "error_signatures": extract_error_signatures(self.combined_text())[:10],
            "structured_timeline": extract_log_timeline(self.combined_text())[:20],
            "root_cause": errors[-1] if errors else "No error lines detected in the provided logs.",
            "affected_components": scan["components"],
            "error_timeline": scan["timeline"],
            "exact_fix_commands": scan["fixes"] or (_DEFAULT_FIXES[self.log_type] if errors else []),
            "preventive_measures": ["Add alerting on error-rate spikes", "Keep structured logs with request IDs"],
            "severity": severity,
            "estimated_resolution_time_minutes": {"critical": 120, "high": 60, "medium": 30, "low": 0}[severity],
            "summary": f"{len(errors)} error lines and {scan['warning_count']} warnings found ({self.log_type}).",
        }

    async def execute(self) -> dict[str, Any]:
        result = await self._analyze_json(
            self.system_prompt(),
            f"Analyze the provided logs. log_type={self.log_type}.",
            self._heuristic(),
            required_key="root_cause",
        )
        result.setdefault("log_type", self.log_type)
        scan = scan_log_lines(self.combined_text())
        result["error_count"] = len(scan["errors"])
        result["warning_count"] = scan["warning_count"]
        return await self._persist(result)
