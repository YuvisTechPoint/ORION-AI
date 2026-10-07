from typing import Any

from agents.base import BaseAgent
from models.schemas import CodeAnalysisResult, SecurityResult


class StressAgent(BaseAgent):
    """Heuristic stress gate with an optional LLM explanation."""

    def __init__(self, llm_client: Any) -> None:
        super().__init__(llm_client=llm_client, name="stress")

    def build_prompt(self, payload: dict[str, Any]) -> str:
        return f"""
You are a Stress Testing Agent.
Given quality and security summaries, decide if a simulated load test would pass.
Return strict JSON only:
{{
  "passed": true,
  "mode": "heuristic",
  "summary": "string",
  "risk_score": 0
}}
Context:
{payload}
""".strip()

    def evaluate(self, analysis: CodeAnalysisResult, security: SecurityResult) -> dict[str, Any]:
        if security.blocked:
            return {"passed": False, "mode": "heuristic", "summary": "Stress skipped: security blocked", "risk_score": 100}
        high_security = any(issue.severity == "high" for issue in security.issues)
        if high_security:
            return {"passed": False, "mode": "heuristic", "summary": "Stress failed: high-severity security issues", "risk_score": 90}
        if analysis.quality_score < 60:
            return {"passed": False, "mode": "heuristic", "summary": "Stress failed: quality score below 60", "risk_score": 80}
        risk = len([issue for issue in analysis.issues if issue.severity in {"high", "medium"}]) + len(security.issues)
        passed = risk < 8 and analysis.quality_score >= 60
        return {
            "passed": passed,
            "mode": "heuristic",
            "summary": "Stress heuristic passed" if passed else "Stress heuristic failed on accumulated risk",
            "risk_score": risk,
        }
