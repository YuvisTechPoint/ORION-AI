from typing import Any

from agents.base import BaseAgent


class SecurityAgent(BaseAgent):
    def __init__(self, llm_client: Any) -> None:
        super().__init__(llm_client=llm_client, name="security")

    def build_prompt(self, payload: dict[str, Any]) -> str:
        code = payload.get("code", "")
        diff = payload.get("diff", "")
        config_text = payload.get("config_text", "")
        repo_files = payload.get("repo_files", {})
        multimodal_inputs = payload.get("multimodal_inputs", [])
        return f"""
You are a Security Agent simulating SAST.
Analyze code and config for vulnerabilities and misconfigurations.
Return strict JSON only and no markdown.
Schema:
{{
  "summary": "string",
  "issues": [
    {{"type": "string", "severity": "low|medium|high", "line": "string", "fix": "string", "snippet": "string"}}
  ],
  "blocked": true
}}
Set blocked=true if any high severity issue exists.
Input code:
{code}

Input diff:
{diff}

Input config:
{config_text}

Repository files (path -> content):
{repo_files}

Multi-modal inputs:
{multimodal_inputs}
""".strip()
