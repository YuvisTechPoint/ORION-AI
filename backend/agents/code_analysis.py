from typing import Any

from agents.base import BaseAgent


class CodeAnalysisAgent(BaseAgent):
    def __init__(self, llm_client: Any) -> None:
        super().__init__(llm_client=llm_client, name="code_analysis")

    def build_prompt(self, payload: dict[str, Any]) -> str:
        code = payload.get("code", "")
        diff = payload.get("diff", "")
        config_text = payload.get("config_text", "")
        repo_files = payload.get("repo_files", {})
        multimodal_inputs = payload.get("multimodal_inputs", [])
        return f"""
You are a Code Analysis Agent.
Analyze the provided source code, code diff, and config for quality, maintainability, and reliability risks.
Return strict JSON only and no markdown.
Schema:
{{
  "summary": "string",
  "issues": [
    {{"type": "string", "severity": "low|medium|high", "line": "string", "fix": "string", "snippet": "string"}}
  ],
  "quality_score": 0,
  "suggestions": ["string"]
}}
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
