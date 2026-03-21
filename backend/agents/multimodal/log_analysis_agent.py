from __future__ import annotations

from typing import Any

from agents.multimodal.base_multimodal_agent import BaseMultimodalAgent


class LogAnalysisAgent(BaseMultimodalAgent):
    ALLOWED_LOG_TYPES = {"server_timeout", "build_error", "git_operation", "deployment_crash", "memory_leak"}

    def __init__(self, llm_client: Any, artifacts: list[dict[str, Any]], log_type: str = "server_timeout") -> None:
        super().__init__(llm_client=llm_client, name="log_analysis_multimodal", artifacts=artifacts)
        self.log_type = log_type if log_type in self.ALLOWED_LOG_TYPES else "server_timeout"

    @staticmethod
    def _truncate_to_last_lines(value: str, max_lines: int = 10000) -> str:
        lines = value.splitlines()
        if len(lines) <= max_lines:
            return value
        return "\n".join(lines[-max_lines:])

    def _prepare_log_artifacts(self) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for artifact in self.artifacts:
            clone = dict(artifact)
            kind = str(clone.get("type", "text"))
            content = clone.get("content", "")
            if kind in {"text", "log", "csv"}:
                text = content.decode("utf-8", errors="ignore") if isinstance(content, (bytes, bytearray)) else str(content)
                clone["content"] = self._truncate_to_last_lines(text, max_lines=10000)
            prepared.append(clone)
        return prepared

    def execute(self) -> dict[str, Any]:
        self.artifacts = self._prepare_log_artifacts()

        prompt_by_type = {
            "server_timeout": "Identify which endpoints are timing out, what database queries are slow, and whether connection pool exhaustion is occurring, then provide a fix plan.",
            "build_error": "Identify the exact line causing the build failure, missing dependencies, incompatible versions, and suggest exact pip install or apt-get fixes.",
            "git_operation": "Identify merge conflicts, detached HEAD states, corrupted refs, and provide exact git commands to resolve.",
            "deployment_crash": "Identify deployment crash root cause, affected startup/runtime components, and concrete rollback or mitigation steps.",
            "memory_leak": "Identify which process or function is leaking memory, estimate leak trend, and whether restart scheduling is needed.",
        }
        log_specific = prompt_by_type[self.log_type]

        system_prompt = (
            "You are a production log analysis agent. "
            + log_specific
            + " Return ONLY valid JSON using this schema exactly: "
            + '{"log_type": string, "root_cause": string, "affected_components": [string], '
            + '"error_timeline": [{"timestamp": string, "event": string, "severity": string}], '
            + '"exact_fix_commands": [string], "preventive_measures": [string], '
            + '"severity": string, "estimated_resolution_time_minutes": int, "summary": string}'
        )
        text_prompt = f"Analyze the uploaded log artifacts for log_type={self.log_type} and return only the required JSON schema."
        raw, _ = self._call_claude_multimodal(system_prompt=system_prompt, text_prompt=text_prompt, max_tokens=3000)
        parsed = self._parse_json(raw)
        parsed.setdefault("log_type", self.log_type)
        return parsed
