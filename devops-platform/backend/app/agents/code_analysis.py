from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.base_agent import AgentInput, AgentOutput, BaseAgent


class IssueItem(BaseModel):
    file: str = ""
    line: int = 0
    severity: str = "low"
    description: str = ""


class CodeAnalysisSchema(BaseModel):
    code_quality_score: int = Field(ge=0, le=100)
    issues: list[IssueItem] = Field(default_factory=list)
    complexity_rating: str = "medium"
    recommendations: list[str] = Field(default_factory=list)
    passed: bool = True


class CodeAnalysisAgent(BaseAgent):
    stage_key = "code_analysis"

    response_model = CodeAnalysisSchema

    def run(self, inp: AgentInput) -> AgentOutput:
        snapshot = inp.context.get("code_snapshot") or {}
        files = snapshot.get("files") or []
        brief = "\n".join(f"--- {f.get('path')} ---\n{f.get('content', '')[:4000]}" for f in files[:5])

        prompt = f"""You are a senior code reviewer. Analyze the following repository snapshot and respond ONLY with valid JSON (no markdown) matching this schema:
{{
  "code_quality_score": <int 0-100>,
  "issues": [{{"file": string, "line": int, "severity": "low"|"medium"|"high"|"critical", "description": string}}],
  "complexity_rating": "low"|"medium"|"high",
  "recommendations": [string],
  "passed": boolean  // true if code_quality_score >= 60 AND no critical severity issues
}}

Code snapshot:
{brief}

Total files sampled: {len(files)}. Total chars: {snapshot.get('total_chars', 0)}.
Respond with JSON only."""

        self.write_log(inp.pipeline_id, "DEV", "INFO", "Starting code analysis")
        data = self._call_llm(prompt, CodeAnalysisSchema)
        out = CodeAnalysisSchema.model_validate(data)

        for issue in out.issues:
            self.write_log(
                inp.pipeline_id,
                "DEV",
                "INFO" if issue.severity != "critical" else "WARNING",
                f"{issue.file}:{issue.line} [{issue.severity}] {issue.description}",
            )

        passed = out.code_quality_score >= 60 and not any(i.severity == "critical" for i in out.issues)
        out.passed = passed and out.passed

        self.emit_artifact(inp.pipeline_id, "code_analysis", out.model_dump())
        self.write_log(
            inp.pipeline_id,
            "DEV",
            "INFO" if out.passed else "ERROR",
            f"Code analysis {'passed' if out.passed else 'failed'} — score {out.code_quality_score}",
            artifact=out.model_dump(),
        )

        return AgentOutput(
            passed=out.passed,
            summary=f"Quality score {out.code_quality_score}, complexity {out.complexity_rating}",
            artifacts={"code_analysis": out.model_dump()},
            next_context={"code_analysis": out.model_dump()},
        )
