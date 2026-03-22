from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.base_agent import AgentInput, AgentOutput, BaseAgent


class AnomalyItem(BaseModel):
    timestamp: str | None = None
    pattern: str = ""
    severity: str = "low"
    description: str = ""


class MonitoringSchema(BaseModel):
    anomalies: list[AnomalyItem] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    health_status: str = "healthy"


class MonitoringAgent(BaseAgent):
    stage_key = "monitoring"

    response_model = MonitoringSchema

    def run(self, inp: AgentInput) -> AgentOutput:
        logs = inp.context.get("log_text") or ""
        prompt = f"""Analyze runtime logs for anomalies. Return ONLY JSON:
{{
  "anomalies": [{{"timestamp": string|null, "pattern": string, "severity": "low"|"medium"|"high", "description": string}}],
  "alerts": [string],
  "health_status": "healthy"|"degraded"|"critical"
}}

Logs:
{logs[:12000]}"""

        self.write_log(inp.pipeline_id, "MONITORING", "INFO", "Analyzing logs with LLM")
        data = self._call_llm(prompt, MonitoringSchema)
        out = MonitoringSchema.model_validate(data)

        artifact = out.model_dump()
        self.emit_artifact(inp.pipeline_id, "monitoring", artifact)

        if out.health_status != "healthy":
            self.emit_alert(
                inp.pipeline_id,
                f"Health degraded: {out.health_status}",
                "critical" if out.health_status == "critical" else "warning",
            )

        self.write_log(
            inp.pipeline_id,
            "MONITORING",
            "INFO",
            f"Monitoring complete — status {out.health_status}",
            artifact=artifact,
        )

        return AgentOutput(
            passed=out.health_status != "critical",
            summary="; ".join(out.alerts[:3]) or "No major issues",
            artifacts={"monitoring": artifact},
            next_context={},
        )
