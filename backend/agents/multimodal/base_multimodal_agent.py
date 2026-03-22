from __future__ import annotations

import base64
import json
import os
from abc import abstractmethod
from typing import Any

try:
    from anthropic import Anthropic
except Exception:  # pragma: no cover - optional dependency
    Anthropic = None

from agents.base import BaseAgent


class BaseMultimodalAgent(BaseAgent):
    def __init__(self, llm_client: Any, name: str, artifacts: list[dict[str, Any]] | None = None) -> None:
        super().__init__(llm_client=llm_client, name=name)
        self.artifacts = artifacts or []

    @abstractmethod
    def execute(self) -> dict[str, Any]:
        raise NotImplementedError

    def build_prompt(self, payload: dict[str, Any]) -> str:
        # Multimodal agents use _call_claude_multimodal, but BaseAgent requires this contract.
        return str(payload)

    def _build_multimodal_message(self, text_prompt: str) -> list[dict[str, Any]]:
        content_blocks: list[dict[str, Any]] = []
        for artifact in self.artifacts:
            artifact_type = str(artifact.get("type", "text"))
            filename = str(artifact.get("filename", "uploaded_file"))
            mime_type = str(artifact.get("mime_type", "text/plain"))
            content = artifact.get("content", "")

            if artifact_type == "image":
                raw = content if isinstance(content, (bytes, bytearray)) else str(content).encode("utf-8")
                content_blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": base64.b64encode(raw).decode("utf-8"),
                        },
                    }
                )
            elif artifact_type in {"text", "csv", "log"}:
                text_content = content.decode("utf-8", errors="ignore") if isinstance(content, (bytes, bytearray)) else str(content)
                content_blocks.append({"type": "text", "text": f"FILE: {filename}\n{text_content[:50000]}"})
            elif artifact_type == "pdf":
                raw = content if isinstance(content, (bytes, bytearray)) else str(content).encode("utf-8")
                content_blocks.append(
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64.b64encode(raw).decode("utf-8"),
                        },
                    }
                )
            else:
                text_content = content.decode("utf-8", errors="ignore") if isinstance(content, (bytes, bytearray)) else str(content)
                content_blocks.append({"type": "text", "text": f"FILE: {filename}\n{text_content[:50000]}"})

        content_blocks.append({"type": "text", "text": text_prompt})
        return content_blocks

    def _call_claude_multimodal(self, system_prompt: str, text_prompt: str, max_tokens: int = 3000) -> tuple[str, int]:
        api_key = os.getenv("LLM_API_KEY", "")
        model = os.getenv("LLM_MODEL", "claude-3-7-sonnet-latest")
        provider = (os.getenv("LLM_PROVIDER", "openai") or "openai").strip().lower()
        if provider != "huggingface" and api_key and Anthropic is not None:
            try:
                client = Anthropic(api_key=api_key)
                response = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": self._build_multimodal_message(text_prompt)}],
                )
                parts = []
                for block in getattr(response, "content", []):
                    text = getattr(block, "text", "")
                    if text:
                        parts.append(text)
                output = "\n".join(parts).strip()
                usage = getattr(response, "usage", None)
                tokens = int(getattr(usage, "output_tokens", 0) or 0)
                return output, tokens
            except Exception:
                # If the remote multimodal LLM call fails for any reason, fall back
                # to the local LLM client behavior below instead of raising.
                pass

        fallback_prompt = f"{system_prompt}\n\n{text_prompt}\n\nArtifacts:\n{json.dumps(self.artifacts, default=str)[:12000]}"
        raw = self.llm_client.generate(fallback_prompt)
        if isinstance(raw, dict):
            return json.dumps(raw), 0
        return str(raw), 0
