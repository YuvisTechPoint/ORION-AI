import re
import zipfile
from datetime import datetime
from typing import Any

import httpx

from app.agents.multimodal.base_multimodal_agent import BaseMultimodalAgent, as_bytes, extract_zip_text_files

GITHUB_LOG_SYSTEM_PROMPT = (
    "You are a GitHub Actions expert. Analyze the provided CI/CD workflow log files. Identify failed steps, "
    "error messages, flaky tests, network failures, rate limit hits, and authentication errors. Return ONLY "
    'valid JSON: `{"workflow_name": string, "failed_steps": [{"step_name": string, "error_type": '
    '"build"|"test"|"network"|"auth"|"rate_limit"|"timeout"|"unknown", "error_message": string, '
    '"line_number": int, "fix": string}], "total_duration_seconds": int, "slowest_steps": [{"step": string, '
    '"duration_seconds": int}], "flaky_indicators": [string], "annotations": [string], "can_be_retried": bool, '
    '"retry_strategy": string, "root_cause": string, "summary": string}`'
)

_ERROR_TYPES: list[tuple[str, re.Pattern[str]]] = [
    ("rate_limit", re.compile(r"rate limit|429|secondary rate", re.IGNORECASE)),
    ("auth", re.compile(r"401|403|authentication|unauthorized|permission denied|bad credentials", re.IGNORECASE)),
    ("timeout", re.compile(r"timed? ?out|timeout|exceeded the maximum execution time", re.IGNORECASE)),
    ("network", re.compile(r"ECONNRESET|ETIMEDOUT|could not resolve|connection (refused|reset)|network", re.IGNORECASE)),
    ("test", re.compile(r"FAILED |AssertionError|tests? failed|pytest|jest", re.IGNORECASE)),
    ("build", re.compile(r"error:|compil|ModuleNotFoundError|npm ERR|pip|build failed", re.IGNORECASE)),
]
_FIXES = {
    "rate_limit": "Retry later or authenticate with a token that has a higher rate limit",
    "auth": "Check repository secrets and token permissions for the workflow",
    "timeout": "Increase timeout-minutes or speed up the step (caching, parallelism)",
    "network": "Re-run the job; add retries around network calls",
    "test": "Fix the failing tests locally and push again",
    "build": "Fix the build error shown in the step log",
    "unknown": "Inspect the step log for details",
}
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
_WORKFLOW_RE = re.compile(r"^(?:\d+_)?(.+?)(?:/|\\)", re.IGNORECASE)


def classify_error(message: str) -> str:
    for name, pattern in _ERROR_TYPES:
        if pattern.search(message):
            return name
    return "unknown"


def step_name_from_file(filename: str) -> str:
    base = filename.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
    return re.sub(r"^\d+_", "", base) or base


def _duration_seconds(text: str) -> int:
    stamps = [m.group(1) for line in text.splitlines() if (m := _TS_RE.match(line))]
    if len(stamps) < 2:
        return 0
    try:
        start = datetime.fromisoformat(stamps[0])
        end = datetime.fromisoformat(stamps[-1])
    except ValueError:
        return 0
    return max(int((end - start).total_seconds()), 0)


class GitHubLogAgent(BaseMultimodalAgent):
    artifact_type = "github_log_analysis"

    def _expand_zip_artifacts(self) -> None:
        expanded: list[dict[str, Any]] = []
        for art in self.artifacts:
            is_zip = art.get("mime_type") == "application/zip" or art.get("type") == "zip"
            if not is_zip:
                expanded.append(art)
                continue
            try:
                expanded.extend(extract_zip_text_files(as_bytes(art.get("content", b"")), suffixes=(".txt",)))
            except zipfile.BadZipFile:
                self.logger.warning("Invalid zip artifact: %s", art.get("filename"))
        self.artifacts = expanded

    async def fetch_run_logs(self, repo_full_name: str, run_id: int, github_token: str) -> bytes:
        url = f"https://api.github.com/repos/{repo_full_name}/actions/runs/{run_id}/logs"
        headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.content

    async def add_run_logs(self, repo_full_name: str, run_id: int, github_token: str) -> None:
        data = await self.fetch_run_logs(repo_full_name, run_id, github_token)
        self.artifacts.append(
            {"type": "zip", "content": data, "filename": f"run-{run_id}-logs.zip", "mime_type": "application/zip"}
        )

    def _heuristic(self) -> dict[str, Any]:
        failed_steps: list[dict[str, Any]] = []
        annotations: list[str] = []
        durations: list[dict[str, Any]] = []
        workflow_name = ""
        for art in self.text_artifacts():
            filename = str(art.get("filename", ""))
            text = str(art.get("content", ""))
            if not workflow_name and (m := _WORKFLOW_RE.match(filename.replace("\\", "/"))):
                workflow_name = m.group(1)
            step = step_name_from_file(filename)
            durations.append({"step": step, "duration_seconds": _duration_seconds(text)})
            for lineno, line in enumerate(text.splitlines(), start=1):
                if "##[error]" in line or "##[warning]" in line:
                    annotations.append(line.split("##[", 1)[1][:300])
                if "##[error]" in line:
                    message = line.split("##[error]", 1)[1].strip()
                    etype = classify_error(message + " " + text[-2000:])
                    failed_steps.append(
                        {
                            "step_name": step,
                            "error_type": etype,
                            "error_message": message[:300],
                            "line_number": lineno,
                            "fix": _FIXES[etype],
                        }
                    )
        types = {s["error_type"] for s in failed_steps}
        retryable = bool(types) and types <= {"network", "rate_limit", "timeout"}
        durations.sort(key=lambda d: -d["duration_seconds"])
        return {
            "workflow_name": workflow_name or "unknown",
            "failed_steps": failed_steps,
            "total_duration_seconds": sum(d["duration_seconds"] for d in durations),
            "slowest_steps": durations[:5],
            "flaky_indicators": ["Transient network/rate-limit/timeout errors"] if retryable else [],
            "annotations": annotations[:50],
            "can_be_retried": retryable,
            "retry_strategy": "Re-run failed jobs" if retryable else "Fix the root cause before re-running",
            "root_cause": failed_steps[0]["error_message"] if failed_steps else "No failed steps detected",
            "summary": f"{len(failed_steps)} failed step(s) across {len(durations)} log file(s).",
        }

    async def execute(self) -> dict[str, Any]:
        self._expand_zip_artifacts()
        result = await self._analyze_json(
            GITHUB_LOG_SYSTEM_PROMPT,
            "Analyze these GitHub Actions workflow logs.",
            self._heuristic(),
            required_key="failed_steps",
            max_tokens=4000,
        )
        return await self._persist(result)
