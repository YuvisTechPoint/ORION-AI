import asyncio
import csv
import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import LLM_ERROR_KEY, BaseAgent
from app.config import settings
from app.services.git_service import GitService
from app.utils.performance_intelligence import resolve_stress_profile
from app.utils.tools import tool_cmd, tool_env

# Used only when the repository ships no locustfile; probes endpoints every service is expected to have.
LOCUSTFILE_TEMPLATE = '''from locust import HttpUser, task, between


class PipelineUser(HttpUser):
    wait_time = between(0.5, 2.0)

    @task(3)
    def health_check(self):
        self.client.get("/health", timeout=5)

    @task(1)
    def get_root(self):
        self.client.get("/", timeout=5)
'''

REPO_LOCUSTFILES = ("locustfile.py", "tests/locustfile.py", "load_tests/locustfile.py", "perf/locustfile.py")

SYSTEM_PROMPT = """You are a performance engineer analyzing load test results. Return ONLY valid JSON:
{
  "performance_verdict": "pass"|"warn"|"fail",
  "p95_ms": float,
  "avg_ms": float,
  "error_rate_pct": float,
  "requests_per_second": float,
  "bottlenecks": [string],
  "performance_score": int (0-100),
  "summary": string,
  "recommendations": [string]
}
verdict: "fail" if error_rate_pct > 5 OR p95_ms > 2000. "warn" if error_rate_pct > 1 OR p95_ms > 1000. "pass" otherwise.
Return ONLY valid JSON."""


def verdict_for(error_rate_pct: float, p95_ms: float) -> str:
    if error_rate_pct > 5 or p95_ms > 2000:
        return "fail"
    if error_rate_pct > 1 or p95_ms > 1000:
        return "warn"
    return "pass"


def _num(row: dict[str, str], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", "N/A"):
            try:
                return float(value)
            except ValueError:
                continue
    return 0.0


def parse_locust_stats(stats_path: Path) -> tuple[list[dict[str, Any]], dict[str, float]]:
    rows: list[dict[str, Any]] = []
    aggregate: dict[str, str] | None = None
    with stats_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("Name") == "Aggregated":
                aggregate = row
                continue
            rows.append(
                {
                    "name": row.get("Name"),
                    "requests": int(_num(row, "Request Count")),
                    "failures": int(_num(row, "Failure Count")),
                    "avg_ms": _num(row, "Average Response Time", "Average (ms)"),
                    "p95_ms": _num(row, "95%", "95%ile (ms)"),
                    "max_ms": _num(row, "Max Response Time", "Max (ms)"),
                    "rps": _num(row, "Requests/s"),
                }
            )
    if aggregate is not None:
        total = _num(aggregate, "Request Count")
        failures = _num(aggregate, "Failure Count")
        overall = {
            "total_requests": total,
            "total_failures": failures,
            "avg_response_ms": _num(aggregate, "Average Response Time", "Average (ms)"),
            "p95_ms": _num(aggregate, "95%", "95%ile (ms)"),
            "max_ms": _num(aggregate, "Max Response Time", "Max (ms)"),
            "requests_per_second": _num(aggregate, "Requests/s"),
        }
    else:
        total = float(sum(r["requests"] for r in rows))
        failures = float(sum(r["failures"] for r in rows))
        overall = {
            "total_requests": total,
            "total_failures": failures,
            "avg_response_ms": (sum(r["avg_ms"] * r["requests"] for r in rows) / total) if total else 0.0,
            "p95_ms": max((r["p95_ms"] for r in rows), default=0.0),
            "max_ms": max((r["max_ms"] for r in rows), default=0.0),
            "requests_per_second": sum(r["rps"] for r in rows),
        }
    overall["failure_rate_pct"] = (failures / total * 100) if total else 0.0
    return rows, overall


class StressTestAgent(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID,
        db: AsyncSession,
        anthropic_client: AsyncAnthropic,
        repo_path: str,
        *,
        profile: str | None = None,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.repo_path = repo_path
        self.profile = resolve_stress_profile(profile)
        self.agent_model = settings.stress_model

    async def _staging_reachable(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.get(settings.staging_url.rstrip("/") + "/health")
            return True
        except httpx.HTTPError:
            return False

    def _repo_locustfile(self) -> Path | None:
        repo = Path(self.repo_path).resolve()
        for rel in REPO_LOCUSTFILES:
            candidate = (repo / rel).resolve()
            if candidate.is_file() and candidate.is_relative_to(repo):
                return candidate
        return None

    async def _skip(self, reason: str) -> dict[str, Any]:
        result = {
            "performance_verdict": "warn",
            "p95_ms": 0.0,
            "avg_ms": 0.0,
            "error_rate_pct": 0.0,
            "requests_per_second": 0.0,
            "bottlenecks": [],
            "performance_score": 0,
            "summary": f"Stress test skipped: {reason}",
            "recommendations": ["Ensure STAGING_URL is reachable from the worker to enable load testing."],
            "skipped": True,
        }
        await self._save_artifact("stress_report", result, duration_seconds=self.elapsed_seconds)
        return result

    async def execute(self) -> dict[str, Any]:
        if not await self._staging_reachable():
            return await self._skip(f"staging target {settings.staging_url} is unreachable")

        base = GitService().reports_dir(self.pipeline_run_id)
        locustfile = self._repo_locustfile()
        locustfile_source = "built-in"
        if locustfile is None:
            locustfile = base / "locustfile.py"
            locustfile.write_text(LOCUSTFILE_TEMPLATE, encoding="utf-8")
        else:
            locustfile_source = locustfile.relative_to(Path(self.repo_path).resolve()).as_posix()
        csv_prefix = str(base / "stress")

        def _run_locust() -> tuple[int, str]:
            cmd = [
                *tool_cmd("locust"),
                "--headless",
                "-u",
                str(self.profile["users"]),
                "-r",
                str(self.profile["spawn_rate"]),
                "--run-time",
                f"{int(self.profile['duration_seconds'])}s",
                f"--csv={csv_prefix}",
                f"--host={settings.staging_url}",
                f"--locustfile={locustfile}",
                "--only-summary",
            ]
            try:
                p = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=tool_env(),
                    timeout=int(self.profile["duration_seconds"]) + 30,
                    check=False,
                )
                return p.returncode, (p.stdout or "") + (p.stderr or "")
            except subprocess.TimeoutExpired as exc:
                return 124, f"locust timed out: {exc}"
            except (FileNotFoundError, OSError) as exc:
                return 127, f"locust not available: {exc}"

        code, log = await asyncio.to_thread(_run_locust)
        stats_path = Path(f"{csv_prefix}_stats.csv")
        if not stats_path.is_file():
            return await self._skip(f"locust produced no stats (exit {code}): {log[-300:]}")

        rows, overall = parse_locust_stats(stats_path)
        if not overall["total_requests"]:
            return await self._skip("load test completed without any requests")

        verdict = verdict_for(overall["failure_rate_pct"], overall["p95_ms"])
        fallback = {
            "performance_verdict": verdict,
            "p95_ms": overall["p95_ms"],
            "avg_ms": overall["avg_response_ms"],
            "error_rate_pct": round(overall["failure_rate_pct"], 3),
            "requests_per_second": overall["requests_per_second"],
            "bottlenecks": [r["name"] for r in rows if r["p95_ms"] > 1000],
            "performance_score": max(0, int(100 - overall["failure_rate_pct"] * 5 - overall["p95_ms"] / 50)),
            "summary": (
                f"{int(overall['total_requests'])} requests, {overall['failure_rate_pct']:.2f}% errors, "
                f"p95 {overall['p95_ms']:.0f}ms."
            ),
            "recommendations": [],
            "analysis_mode": "heuristic",
        }

        user_message = f"OVERALL:\n{json.dumps(overall)}\n\nPER ENDPOINT:\n{json.dumps(rows[:50])}"
        result = await self._call_claude_json(SYSTEM_PROMPT, user_message, max_tokens=1500)
        if LLM_ERROR_KEY in result or "performance_verdict" not in result:
            result = fallback
        else:
            for key, value in fallback.items():
                result.setdefault(key, value)
            # The measured numbers decide the gate; the model only adds narrative.
            result["performance_verdict"] = verdict
            result["analysis_mode"] = "llm"
        result["overall"] = overall
        result["locustfile"] = locustfile_source
        result["stress_profile"] = self.profile.get("name", "standard")
        result["profile"] = self.profile

        await self._save_artifact(
            "stress_report",
            result,
            raw_output=log[:50000],
            duration_seconds=self.elapsed_seconds,
        )
        return result
