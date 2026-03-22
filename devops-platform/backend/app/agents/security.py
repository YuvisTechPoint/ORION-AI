from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.base_agent import AgentInput, AgentOutput, BaseAgent


class VulnerabilityItem(BaseModel):
    id: str = ""
    title: str = ""
    severity: str = "low"
    cve: str | None = None
    description: str = ""
    affected_code: str = ""


class SecuritySchema(BaseModel):
    vulnerabilities: list[VulnerabilityItem] = Field(default_factory=list)
    overall_risk: str = "low"
    passed: bool = True


class SecurityAgent(BaseAgent):
    stage_key = "security"

    response_model = SecuritySchema

    def run(self, inp: AgentInput) -> AgentOutput:
        snapshot = inp.context.get("code_snapshot") or {}
        files = snapshot.get("files") or []
        brief = "\n".join(f"--- {f.get('path')} ---\n{f.get('content', '')[:3500]}" for f in files[:5])

        prompt = f"""You are an application security auditor. Scan for security issues. Respond ONLY with JSON:
{{
  "vulnerabilities": [{{"id": string, "title": string, "severity": "low"|"medium"|"high"|"critical", "cve": string|null, "description": string, "affected_code": string}}],
  "overall_risk": "low"|"medium"|"high"|"critical",
  "passed": boolean  // false if ANY vulnerability severity is critical OR overall_risk is critical
}}

Code:
{brief}

Rules: If any vulnerability has severity \"critical\" OR overall_risk is \"critical\", passed must be false."""

        self.write_log(inp.pipeline_id, "DEV", "INFO", "Starting security scan")
        data = self._call_llm(prompt, SecuritySchema)
        out = SecuritySchema.model_validate(data)

        critical_vuln = any(v.severity == "critical" for v in out.vulnerabilities)
        if critical_vuln or out.overall_risk == "critical":
            out.passed = False
        else:
            out.passed = out.passed and not critical_vuln

        for v in out.vulnerabilities:
            self.write_log(
                inp.pipeline_id,
                "DEV",
                "WARNING" if v.severity in ("high", "critical") else "INFO",
                f"[{v.severity.upper()}] {v.title}: {v.description[:500]}",
            )

        self.emit_artifact(inp.pipeline_id, "security", out.model_dump())

        if not out.passed:
            self.write_log(
                inp.pipeline_id,
                "DEV",
                "BLOCKED",
                "Pipeline blocked by security findings",
                artifact=out.model_dump(),
            )
            self.write_log(
                inp.pipeline_id,
                "DEV",
                "BLOCKED",
                "Auto-remediation skipped: blocked reason is not auto-resolvable by policy",
            )

        return AgentOutput(
            passed=out.passed,
            summary=f"Overall risk {out.overall_risk}, {len(out.vulnerabilities)} findings",
            artifacts={"security": out.model_dump()},
            next_context={"security": out.model_dump()},
        )
