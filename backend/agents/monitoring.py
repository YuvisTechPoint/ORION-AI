from typing import Any

from agents.base import BaseAgent


class MonitoringAgent(BaseAgent):
    def __init__(self, llm_client: Any) -> None:
        super().__init__(llm_client=llm_client, name="monitoring")

    def build_prompt(self, payload: dict[str, Any]) -> str:
        logs = payload.get("logs", "")
        multimodal_inputs = payload.get("multimodal_inputs", [])
        return f"""
You are a Monitoring Agent.
Analyze logs and detect anomalies, likely root causes, and fixes.
Return strict JSON only and no markdown.
Schema:
{{
  "summary": "string",
  "anomalies": ["string"],
  "suggestions": ["string"]
}}
Logs:
{logs}

Multi-modal inputs:
{multimodal_inputs}
""".strip()
