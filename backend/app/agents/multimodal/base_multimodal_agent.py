from __future__ import annotations

import base64
import io
import json
import re
import zipfile
from typing import Any

from app.config import settings


class BaseMultimodalAgent:
    """Base helper for Anthropic multimodal agents.

    This class is intentionally lightweight and independent from the existing
    agents.BaseAgent so it can be used for dedicated multimodal analysis
    endpoints without impacting the core pipeline agents.
    """

    def __init__(self, anthropic_client: Any, artifacts: list[dict[str, Any]] | None = None) -> None:
        self.anthropic_client = anthropic_client
        self.artifacts: list[dict[str, Any]] = artifacts or []

    def _build_multimodal_content(self, text_prompt: str) -> list[dict[str, Any]]:
        """Build Anthropic messages content array from artifacts and a text prompt.

        Each artifact dict is expected to have keys:
        - type: "text" | "image" | "csv" | "log" | "zip" | "pdf"
        - content: bytes | str
        - filename: str
        - mime_type: str
        """

        content_blocks: list[dict[str, Any]] = []

        for artifact in self.artifacts:
            artifact_type = str(artifact.get("type", "text"))
            filename = str(artifact.get("filename", "uploaded_file"))
            mime_type = str(artifact.get("mime_type", "text/plain"))
            content = artifact.get("content", b"")

            if artifact_type == "image":
                raw = content if isinstance(content, (bytes, bytearray)) else str(content).encode("utf-8")
                content_blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": base64.b64encode(raw).decode(),
                        },
                    }
                )
            elif artifact_type == "pdf":
                raw = content if isinstance(content, (bytes, bytearray)) else str(content).encode("utf-8")
                content_blocks.append(
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64.b64encode(raw).decode(),
                        },
                    }
                )
            elif artifact_type == "zip":
                raw_bytes = content if isinstance(content, (bytes, bytearray)) else str(content).encode("utf-8")
                try:
                    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
                        for name in archive.namelist():
                            lower = name.lower()
                            if not (lower.endswith(".txt") or lower.endswith(".log")):
                                continue
                            try:
                                with archive.open(name) as member:
                                    file_bytes = member.read()
                            except Exception:  # noqa: BLE001
                                continue
                            content_str = file_bytes.decode("utf-8", errors="ignore")
                            snippet = content_str[:30000]
                            content_blocks.append({"type": "text", "text": f"FILE: {name}\n{snippet}"})
                except zipfile.BadZipFile:
                    # Ignore invalid zip artifacts; they are not fatal to analysis.
                    continue
            else:
                if isinstance(content, (bytes, bytearray)):
                    text_value = content.decode("utf-8", errors="ignore")
                else:
                    text_value = str(content)

                text_snippet = str(text_value)[:40000]
                content_blocks.append(
                    {
                        "type": "text",
                        "text": f"FILE: {filename}\nTYPE: {artifact_type}\n{text_snippet}",
                    }
                )

        # Finally append the direct user text prompt as its own block.
        content_blocks.append({"type": "text", "text": text_prompt})
        return content_blocks

    async def _analyze(self, system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> dict[str, Any]:
        """Call Anthropic Claude with multimodal content and parse strict JSON output."""

        if self.anthropic_client is None:
            raise ValueError("Anthropic client is not configured for this agent")

        content = self._build_multimodal_content(user_prompt)

        response = await self.anthropic_client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
        )

        raw_text = ""
        if getattr(response, "content", None):
            first_block = response.content[0]
            raw_text = getattr(first_block, "text", "") or ""

        cleaned = re.sub(r"```json|```", "", raw_text).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Retry once with a stricter prompt asking for raw JSON only.
            retry_prompt = (
                user_prompt
                + "\n\nIMPORTANT: Your previous response was not valid JSON. Return ONLY the raw JSON object, no explanation, no markdown."
            )
            retry_content = self._build_multimodal_content(retry_prompt)
            retry_response = await self.anthropic_client.messages.create(
                model=settings.anthropic_model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": retry_content}],
            )

            retry_text = ""
            if getattr(retry_response, "content", None):
                first_retry_block = retry_response.content[0]
                retry_text = getattr(first_retry_block, "text", "") or ""

            cleaned_retry = re.sub(r"```json|```", "", retry_text).strip()
            try:
                return json.loads(cleaned_retry)
            except json.JSONDecodeError as exc:  # noqa: PERF203
                raise ValueError(f"Claude returned invalid JSON: {retry_text[:500]}") from exc
