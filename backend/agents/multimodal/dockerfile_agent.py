from __future__ import annotations

from typing import Any

from agents.multimodal.base_multimodal_agent import BaseMultimodalAgent


class DockerfileAgent(BaseMultimodalAgent):
    def __init__(
        self,
        llm_client: Any,
        artifacts: list[dict[str, Any]],
        auto_pr_callback: Any | None = None,
    ) -> None:
        super().__init__(llm_client=llm_client, name="dockerfile_multimodal", artifacts=artifacts)
        self.auto_pr_callback = auto_pr_callback

    def execute(self) -> dict[str, Any]:
        system_prompt = (
            "You are a Docker expert and DevSecOps engineer. Analyze the Dockerfile, compose file, and build logs provided. "
            "Check for: base image vulnerabilities (outdated tags, EOL images), multi-stage build inefficiencies, "
            "secrets accidentally baked into layers (ENV or ARG with passwords/keys), missing .dockerignore entries "
            "causing large image sizes, incorrect USER directives (running as root), missing HEALTHCHECK instructions, "
            "improper COPY vs ADD usage, layer caching mistakes (COPY . . before pip install), and port exposure issues. "
            "Return ONLY valid JSON: "
            "{\"dockerfile_issues\": [{\"line\": int, \"issue_type\": \"security\"|\"performance\"|\"best_practice\"|\"error\", \"description\": string, \"current_code\": string, \"fixed_code\": string, \"severity\": string}], "
            "\"build_errors\": [{\"error_message\": string, \"cause\": string, \"fix\": string}], "
            "\"image_size_estimate_mb\": int, \"security_score\": int, \"optimized_dockerfile\": string, "
            "\"summary\": string, \"estimated_size_reduction_mb\": int}"
        )
        text_prompt = "Analyze uploaded Docker artifacts and return exactly the required JSON schema."
        raw, _ = self._call_claude_multimodal(system_prompt=system_prompt, text_prompt=text_prompt, max_tokens=3000)
        parsed = self._parse_json(raw)

        high_or_critical = False
        for issue in parsed.get("dockerfile_issues", []) if isinstance(parsed, dict) else []:
            if not isinstance(issue, dict):
                continue
            severity = str(issue.get("severity", "")).lower()
            if severity in {"high", "critical"}:
                high_or_critical = True
                break

        parsed["auto_pr_needed"] = high_or_critical
        if high_or_critical and callable(self.auto_pr_callback):
            callback_result = self.auto_pr_callback(parsed)
            parsed["auto_pr_triggered"] = True
            parsed["auto_pr_result"] = callback_result
        else:
            parsed["auto_pr_triggered"] = False
            parsed.setdefault("auto_pr_result", None)

        return parsed
