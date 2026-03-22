import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent


class QAAgent(BaseAgent):
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
        tests_dir = Path(self.repo_path) / "tests"
        if not tests_dir.is_dir():
            res = {
                "verdict": "pass",
                "test_summary": "No tests directory; skipped.",
                "root_causes": [],
                "recommendations": [],
            }
            await self._save_artifact("qa_report", res, duration_seconds=self.elapsed_seconds)
            return res

        out_json = Path("/tmp") / str(self.pipeline_run_id) / "pytest.json"
        out_json.parent.mkdir(parents=True, exist_ok=True)

        def _run_pytest() -> tuple[int, str]:
            p = subprocess.run(
                [
                    "pytest",
                    self.repo_path,
                    "--tb=short",
                    "--json-report",
                    f"--json-report-file={out_json}",
                    "--timeout=120",
                    "-x",
                    "-q",
                ],
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            return p.returncode, p.stdout + p.stderr

        code, raw = await asyncio.to_thread(_run_pytest)
        report: dict[str, Any] = {}
        if out_json.is_file():
            try:
                report = json.loads(out_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                report = {}

        user = json.dumps({"pytest_report": report, "raw_log": raw[:20000]})
        system = (
            "You are a QA automation expert. Analyze pytest JSON report. "
            "Return JSON with verdict (pass|fail), test_summary (string), "
            "root_causes (list of strings), recommendations (list of strings)."
        )
        out = await self._call_claude_json(system, user, max_tokens=2000)
        if "verdict" not in out:
            summary = report.get("summary", {}) if isinstance(report, dict) else {}
            failed = int(summary.get("failed", 0) or 0)
            out = {
                "verdict": "fail" if failed or code != 0 else "pass",
                "test_summary": json.dumps(summary),
                "root_causes": [],
                "recommendations": [],
            }
        await self._save_artifact(
            "qa_report",
            out,
            raw_output=raw[:50000],
            duration_seconds=self.elapsed_seconds,
        )
        return out
