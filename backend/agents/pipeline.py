from typing import Any

from agents.base import BaseAgent


class PipelineAgent(BaseAgent):
    def __init__(self, llm_client: Any) -> None:
        super().__init__(llm_client=llm_client, name="pipeline")

    def build_prompt(self, payload: dict[str, Any]) -> str:
        return f"""
You are a Pipeline Control Agent.
Decide next stage in this fixed flow: dev -> qa -> stress -> approval -> deployment.
If severe risks exist, choose blocked.
Return strict JSON only and no markdown.
Schema:
{{
  "next_stage": "dev|qa|stress|approval|deployment|blocked|completed|failed|rolled_back",
  "reason": "string",
  "approved": false
}}
Context:
{payload}
""".strip()
