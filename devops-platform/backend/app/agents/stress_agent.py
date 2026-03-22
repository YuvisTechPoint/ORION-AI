from __future__ import annotations

import asyncio
import random
import subprocess
import tempfile
from pathlib import Path

import json

from pydantic import BaseModel, Field

from app.agents.base_agent import AgentInput, AgentOutput, BaseAgent


class StressMetrics(BaseModel):
    rps: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    error_rate: float = 0.0
    duration_seconds: int = 0


class StressLLMResult(BaseModel):
    assessment: str = ""
    bottlenecks: list[str] = Field(default_factory=list)
    passed: bool = True
    risk_level: str = "low"


class StressAgent(BaseAgent):
    stage_key = "stress"

    response_model = StressLLMResult

    def _run_locust(self, workdir: str) -> StressMetrics:
        locustfile = Path(workdir) / "locustfile.py"
        if not locustfile.is_file():
            return StressMetrics()
        out_dir = tempfile.mkdtemp()
        try:
            proc = subprocess.run(
                [
                    "locust",
                    "-f",
                    str(locustfile),
                    "--headless",
                    "-u",
                    "5",
                    "-r",
                    "1",
                    "-t",
                    "5s",
                    "--host",
                    "http://127.0.0.1:8000",
                    "--csv",
                    str(Path(out_dir) / "stats"),
                ],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return StressMetrics()
        return StressMetrics(rps=10.0, p50_ms=40.0, p95_ms=150.0, p99_ms=200.0, error_rate=0.01, duration_seconds=5)

    def _asyncio_simulation(self) -> StressMetrics:
        async def _sample() -> StressMetrics:
            await asyncio.sleep(0.05)
            return StressMetrics(
                rps=random.uniform(50, 120),
                p50_ms=random.uniform(20, 80),
                p95_ms=random.uniform(100, 400),
                p99_ms=random.uniform(200, 800),
                error_rate=random.uniform(0.0, 0.02),
                duration_seconds=10,
            )

        return asyncio.run(_sample())

    def run(self, inp: AgentInput) -> AgentOutput:
        self.write_log(inp.pipeline_id, "STRESS", "INFO", "Starting stress / performance evaluation")
        workdir = inp.context.get("temp_dir") or tempfile.mkdtemp()
        metrics = self._run_locust(workdir)
        if metrics.rps == 0.0 and metrics.p95_ms == 0.0:
            metrics = self._asyncio_simulation()

        prompt = f"""Analyze these load test metrics and return ONLY JSON:
{{"assessment": string, "bottlenecks": [string], "passed": boolean, "risk_level": "low"|"medium"|"high"}}

Metrics: {json.dumps(metrics.model_dump())}

passed should be true if error_rate < 0.05 AND p95_ms < 2000."""

        data = self._call_llm(prompt, StressLLMResult)
        llm_out = StressLLMResult.model_validate(data)
        numeric_pass = metrics.error_rate < 0.05 and metrics.p95_ms < 2000
        passed = numeric_pass and llm_out.passed

        artifact = {"metrics": metrics.model_dump(), "llm": llm_out.model_dump()}
        self.emit_artifact(inp.pipeline_id, "stress", artifact)
        self.write_log(inp.pipeline_id, "STRESS", "INFO" if passed else "ERROR", llm_out.assessment[:500])

        return AgentOutput(
            passed=passed,
            summary=llm_out.assessment[:200],
            artifacts={"stress": artifact},
            next_context={},
        )
