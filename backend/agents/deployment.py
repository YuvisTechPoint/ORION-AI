from typing import Any

from agents.base import BaseAgent


class DeploymentAgent(BaseAgent):
    def __init__(self, llm_client: Any) -> None:
        super().__init__(llm_client=llm_client, name="deployment")

    def build_prompt(self, payload: dict[str, Any]) -> str:
        return f"""
You are a Deployment Agent.
Given pipeline context, decide deployment action and rollback recommendation.
Return strict JSON only and no markdown.
Schema:
{{
  "status": "deployed|rolled_back|failed",
  "reason": "string",
  "environment": "staging|production"
}}
Context:
{payload}
""".strip()
