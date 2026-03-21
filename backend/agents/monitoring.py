import asyncio
from typing import Any

from agents.base import BaseAgent
from services.journald_service import JournaldService


class MonitoringAgent(BaseAgent):
    def __init__(self, llm_client: Any) -> None:
        super().__init__(llm_client=llm_client, name="monitoring")
        self.journald_service = JournaldService()

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt_payload = self._prepare_payload(payload)
        try:
            asyncio.get_running_loop()
            metrics = {"journald_summary": {"error": "metrics collection unavailable while event loop is running"}}
        except RuntimeError:
            metrics = asyncio.run(self._collect_metrics())
        prompt_payload["metrics"] = metrics

        prompt = self.build_prompt(prompt_payload)
        raw = self.llm_client.generate(prompt)
        if isinstance(raw, dict):
            parsed = raw
        else:
            parsed = self._parse_json(raw)
        self._record_memory(prompt_payload=prompt_payload, response_payload=parsed)
        return parsed

    async def _collect_metrics(self) -> dict[str, Any]:
        summary = await self.journald_service.get_error_summary()
        return {"journald_summary": summary}

    def build_prompt(self, payload: dict[str, Any]) -> str:
        logs = payload.get("logs", "")
        multimodal_inputs = payload.get("multimodal_inputs", [])
        metrics = payload.get("metrics", {})
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

Metrics:
{metrics}

Multi-modal inputs:
{multimodal_inputs}
""".strip()
