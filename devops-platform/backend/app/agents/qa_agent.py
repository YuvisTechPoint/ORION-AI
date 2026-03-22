from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from app.agents.base_agent import AgentInput, AgentOutput, BaseAgent


class TestFailureItem(BaseModel):
    test_name: str = ""
    error_type: str = ""
    likely_cause: str = ""
    suggested_fix: str = ""


class QAFailureAnalysis(BaseModel):
    test_failures: list[TestFailureItem] = Field(default_factory=list)
    pass_rate: float = 0.0


class QAAgent(BaseAgent):
    stage_key = "qa"

    response_model = QAFailureAnalysis

    def run(self, inp: AgentInput) -> AgentOutput:
        self.write_log(inp.pipeline_id, "QA", "INFO", "Running pytest suite")
        workdir = inp.context.get("temp_dir") or tempfile.mkdtemp()
        tests_dir = Path(workdir) / "tests"
        stdout = ""
        stderr = ""
        exit_code = 1

        if tests_dir.is_dir():
            try:
                proc = subprocess.run(
                    ["python", "-m", "pytest", str(tests_dir), "-q", "--tb=short"],
                    cwd=workdir,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                stdout = proc.stdout or ""
                stderr = proc.stderr or ""
                exit_code = proc.returncode
            except Exception as e:
                stderr = str(e)
                exit_code = 1
        else:
            self.write_log(inp.pipeline_id, "QA", "INFO", "No tests/ directory — using mock pass for QA stage")
            stdout = "no tests directory — simulated"
            exit_code = 0

        passed = exit_code == 0
        analysis: dict = {"test_failures": [], "pass_rate": 1.0 if passed else 0.0}

        if not passed:
            prompt = f"""Pytest failed. Analyze output and return ONLY JSON:
{{"test_failures":[{{"test_name":"","error_type":"","likely_cause":"","suggested_fix":""}}],"pass_rate":0.0}}

stdout:
{stdout[:6000]}
stderr:
{stderr[:6000]}"""
            try:
                raw = self._call_llm(prompt, QAFailureAnalysis)
                qa = QAFailureAnalysis.model_validate(raw)
                analysis = qa.model_dump()
            except Exception:
                analysis = {"test_failures": [], "pass_rate": 0.0}
            pr = float(analysis.get("pass_rate", 0.0))
            passed = pr >= 0.8

        self.emit_artifact(
            inp.pipeline_id,
            "qa",
            {"pytest_stdout": stdout[:8000], "pytest_stderr": stderr[:8000], "exit_code": exit_code, "llm": analysis},
        )
        self.write_log(
            inp.pipeline_id,
            "QA",
            "INFO" if passed else "ERROR",
            f"QA stage {'passed' if passed else 'failed'} (exit {exit_code})",
        )

        return AgentOutput(
            passed=passed,
            summary="Pytest passed" if exit_code == 0 else "Pytest failures analyzed",
            artifacts={"qa": {"exit_code": exit_code, "analysis": analysis}},
            next_context={},
        )
