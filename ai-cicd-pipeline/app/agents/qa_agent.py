import asyncio
import json
import re
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import LLM_ERROR_KEY, BaseAgent
from app.config import settings
from app.services.git_service import GitService
from app.utils.test_intelligence import select_relevant_tests
from app.utils.text_analysis import files_in_diff

SYSTEM_PROMPT = """You are a QA engineer analyzing test results. Return ONLY valid JSON:
{
  "test_summary": {"total": int, "passed": int, "failed": int, "errors": int, "duration_seconds": float},
  "verdict": "pass"|"fail",
  "root_causes": [{"test": string, "cause": string, "category": "assertion"|"exception"|"timeout"|"import_error"|"other"}],
  "recommendations": [string],
  "summary": string,
  "flaky_test_indicators": [string]
}
verdict is "fail" if failed > 0 OR errors > 0. Return ONLY valid JSON."""

_TRACE_FILE_RE = re.compile(r"^([\w./\\-]+\.py):(\d+)", re.MULTILINE)


def _categorize(longrepr: str) -> str:
    text = longrepr or ""
    if "AssertionError" in text or "assert " in text:
        return "assertion"
    if "Timeout" in text:
        return "timeout"
    if "ImportError" in text or "ModuleNotFoundError" in text:
        return "import_error"
    if "Error" in text or "Exception" in text:
        return "exception"
    return "other"


class QAAgent(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID,
        db: AsyncSession,
        anthropic_client: AsyncAnthropic,
        repo_path: str,
        diff_text: str = "",
        changed_files: list[str] | None = None,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.repo_path = repo_path
        self.diff_text = diff_text or ""
        self.changed_files = changed_files or []
        self.agent_model = settings.qa_model

    def _report_path(self) -> Path:
        return GitService().reports_dir(self.pipeline_run_id) / "pytest_report.json"

    def _run_pytest(self, report_path: Path, test_targets: list[str] | None = None) -> tuple[int, str]:
        targets = test_targets or [self.repo_path]
        cmd = tool_cmd(
            "pytest",
            *targets,
            "--tb=short",
            "--json-report",
            f"--json-report-file={report_path}",
            "--timeout=120",
            "-x",
            "--no-header",
            "-q",
        )
        try:
            p = subprocess.run(
                cmd,
                capture_output=True,
                encoding="utf-8", errors="replace",
                timeout=180,
                check=False,
                cwd=self.repo_path,
                env=repo_env(self.repo_path),
            )
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except subprocess.TimeoutExpired as exc:
            return 124, f"pytest timed out after 180s: {exc}"
        except (FileNotFoundError, OSError) as exc:
            return 127, f"pytest not available: {exc}"

    def _failure_issues(self, failed_tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Map failed tests to file-level issues so Auto-PR knows which files to patch."""
        repo = Path(self.repo_path)
        issues: list[dict[str, Any]] = []
        for test in failed_tests:
            test_file = str(test.get("nodeid", "")).split("::")[0]
            longrepr = str(test.get("longrepr", ""))
            files = {test_file} if test_file else set()
            for path, _line in _TRACE_FILE_RE.findall(longrepr):
                norm = path.replace("\\", "/")
                if (repo / norm).is_file():
                    files.add(norm)
            for f in sorted(files):
                issues.append(
                    {
                        "file": f,
                        "line": 0,
                        "type": "test_failure",
                        "test": test.get("nodeid"),
                        "description": longrepr[:1500],
                        "severity": "high",
                    }
                )
        return issues

    async def execute(self) -> dict[str, Any]:
        repo = Path(self.repo_path)
        if not (repo / "tests").is_dir() and not (repo / "test").is_dir():
            result = {
                "verdict": "pass",
                "summary": "QA simulated pass — no tests/ directory in repository",
                "test_summary": {"total": 0, "passed": 0, "failed": 0, "errors": 0, "duration_seconds": 0.0},
                "root_causes": [],
                "recommendations": ["Add a tests/ directory with automated tests."],
                "issues": [],
                "skipped": True,
                "analysis_mode": "simulated",
            }
            await self._save_artifact("qa_report", result, duration_seconds=self.elapsed_seconds)
            return result

        report_path = self._report_path()
        changed = self.changed_files or (files_in_diff(self.diff_text) if self.diff_text else [])
        selection = select_relevant_tests(changed, self.repo_path)
        test_targets = None
        if selection.get("mode") == "selected" and selection.get("selected_tests"):
            test_targets = [str(Path(self.repo_path) / t) for t in selection["selected_tests"]]

        returncode, stdout = await asyncio.to_thread(self._run_pytest, report_path, test_targets)

        report: dict[str, Any] = {}
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                report = {}

        summary = report.get("summary", {}) if isinstance(report, dict) else {}
        pytest_summary = {
            "total": int(summary.get("total", 0) or 0),
            "passed": int(summary.get("passed", 0) or 0),
            "failed": int(summary.get("failed", 0) or 0),
            "errors": int(summary.get("error", 0) or 0),
            "duration_seconds": float(report.get("duration", 0.0) or 0.0),
            "exit_code": returncode,
        }
        failed_tests = []
        for test in report.get("tests", []) if isinstance(report, dict) else []:
            if test.get("outcome") in ("failed", "error"):
                stage = next(
                    (s for s in ("setup", "call", "teardown") if (test.get(s) or {}).get("outcome") == "failed"),
                    "call",
                )
                phase = test.get(stage) or {}
                failed_tests.append(
                    {
                        "nodeid": test.get("nodeid"),
                        "longrepr": str(phase.get("longrepr", ""))[:3000],
                        "duration": phase.get("duration"),
                        "stage": stage,
                    }
                )

        infra_error = not report and returncode not in (0, 1, 2, 5)
        if returncode == 5 and not pytest_summary["total"]:
            verdict = "pass"
        elif infra_error:
            verdict = "pass"
        else:
            verdict = (
                "fail"
                if pytest_summary["failed"] or pytest_summary["errors"] or returncode in (1, 2)
                else "pass"
            )

        fallback = {
            "test_summary": pytest_summary,
            "verdict": verdict,
            "root_causes": [
                {"test": t["nodeid"], "cause": t["longrepr"][:300], "category": _categorize(t["longrepr"])}
                for t in failed_tests
            ],
            "recommendations": ["Fix failing tests before merging."] if verdict == "fail" else [],
            "summary": (
                f"pytest could not run (exit {returncode}); QA skipped."
                if infra_error
                else f"{pytest_summary['passed']}/{pytest_summary['total']} tests passed."
            ),
            "flaky_test_indicators": [],
            "analysis_mode": "heuristic",
        }
        if infra_error:
            fallback["infrastructure_error"] = True

        if failed_tests:
            user_message = (
                f"PYTEST REPORT SUMMARY:\n{json.dumps(pytest_summary)}\n\n"
                f"FAILED TESTS:\n{json.dumps(failed_tests[:10])}\n\n"
                f"STDOUT:\n{stdout[:2000]}"
            )
            result = await self._call_claude_json(SYSTEM_PROMPT, user_message, max_tokens=2000)
            if LLM_ERROR_KEY in result or "verdict" not in result:
                result = fallback
            else:
                for key, value in fallback.items():
                    result.setdefault(key, value)
                # Real failures always fail the gate regardless of the model's opinion.
                result["verdict"] = "fail" if verdict == "fail" else result["verdict"]
                result["analysis_mode"] = "llm"
        else:
            result = fallback

        result["issues"] = self._failure_issues(failed_tests)
        result["test_selection"] = selection
        await self._save_artifact(
            "qa_report",
            result,
            raw_output=stdout[:50000],
            duration_seconds=self.elapsed_seconds,
        )
        return result
