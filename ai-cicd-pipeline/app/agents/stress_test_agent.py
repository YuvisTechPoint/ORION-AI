import asyncio
import csv
import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.config import settings


LOCUSTFILE_TEMPLATE = '''
from locust import HttpUser, task, between

class StressUser(HttpUser):
    wait_time = between(0.5, 2)

    @task(3)
    def health(self):
        self.client.get("/health", name="/health")

    @task(2)
    def runs(self):
        self.client.get("/api/v1/pipeline/runs", name="/api/v1/pipeline/runs")

    @task(1)
    def root(self):
        self.client.get("/", name="/")
'''


class StressTestAgent(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID,
        db: AsyncSession,
        anthropic_client: AsyncAnthropic,
        repo_path: str,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.repo_path = repo_path

    async def execute(self) -> dict[str, Any]:
        base = Path("/tmp/pipeline") / str(self.pipeline_run_id)
        base.mkdir(parents=True, exist_ok=True)
        lf = base / "locustfile.py"
        lf.write_text(LOCUSTFILE_TEMPLATE, encoding="utf-8")
        prefix = str(base / "stress")

        def _run_locust() -> tuple[int, str]:
            cmd = [
                "locust",
                "--headless",
                "-u",
                str(settings.stress_test_users),
                "-r",
                str(settings.stress_test_spawn_rate),
                "--run-time",
                f"{settings.stress_test_duration}s",
                f"--csv={prefix}",
                f"--host={settings.staging_url}",
                "--only-summary",
                "-f",
                str(lf),
            ]
            p = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600, check=False
            )
            return p.returncode, p.stdout + p.stderr

        code, log = await asyncio.to_thread(_run_locust)

        stats_path = Path(f"{prefix}_stats.csv")
        rows: list[dict[str, str]] = []
        if stats_path.is_file():
            with stats_path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

        user = json.dumps({"locust_log": log[:20000], "stats_rows": rows[:200]})
        system = (
            "You are a performance engineer. Analyze Locust CSV/summary. "
            "Return JSON with performance_verdict (pass|warn|fail), p95_ms (float), error_rate_pct (float)."
        )
        out = await self._call_claude_json(system, user, max_tokens=1500)
        if "performance_verdict" not in out:
            out = {
                "performance_verdict": "warn" if code != 0 else "pass",
                "p95_ms": 0.0,
                "error_rate_pct": 0.0,
            }
        await self._save_artifact(
            "stress_report",
            out,
            raw_output=log[:50000],
            duration_seconds=self.elapsed_seconds,
        )
        return out
