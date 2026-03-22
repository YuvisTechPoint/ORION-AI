import base64
import io
import json
import re
import zipfile
from typing import Any

from anthropic import AsyncAnthropic

from app.config import settings


class BaseMultimodalAgent:
    def __init__(
        self,
        anthropic_client: AsyncAnthropic,
        artifacts: list[dict[str, Any]],
    ) -> None:
        self.anthropic_client = anthropic_client
        self.artifacts = artifacts

    def _build_multimodal_content(self, text_prompt: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for art in self.artifacts:
            atype = (art.get("type") or "").lower()
            content = art.get("content")
            filename = art.get("filename") or "file"
            mime = (art.get("mime_type") or "").lower()

            if isinstance(content, str):
                raw = content.encode("utf-8")
            elif isinstance(content, (bytes, bytearray)):
                raw = bytes(content)
            else:
                raw = str(content).encode("utf-8")

            if atype == "image" or mime in ("image/png", "image/jpeg"):
                media = "image/png" if "png" in mime or filename.endswith(".png") else "image/jpeg"
                b64 = base64.standard_b64encode(raw).decode("ascii")
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media,
                            "data": b64,
                        },
                    }
                )
            elif atype == "pdf" or mime == "application/pdf" or filename.lower().endswith(
                ".pdf"
            ):
                b64 = base64.standard_b64encode(raw).decode("ascii")
                blocks.append(
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64,
                        },
                    }
                )
            elif atype == "zip" or filename.lower().endswith(".zip"):
                try:
                    zf = zipfile.ZipFile(io.BytesIO(raw))
                    for name in zf.namelist()[:200]:
                        try:
                            data = zf.read(name)[:40000]
                            text = data.decode("utf-8", errors="replace")
                        except Exception:
                            text = "<binary>"
                        blocks.append(
                            {
                                "type": "text",
                                "text": f"[{filename}::{name}]\n{text[:40000]}",
                            }
                        )
                except zipfile.BadZipFile:
                    blocks.append(
                        {"type": "text", "text": f"[{filename}] invalid zip"}
                    )
            elif atype in ("text", "csv", "log"):
                text = raw.decode("utf-8", errors="replace")[:40000]
                blocks.append(
                    {"type": "text", "text": f"[{filename}]\n{text}"}
                )
            else:
                text = raw.decode("utf-8", errors="replace")[:40000]
                blocks.append(
                    {"type": "text", "text": f"[{filename}]\n{text}"}
                )

        blocks.append({"type": "text", "text": text_prompt})
        return blocks

    async def _analyze(
        self, system_prompt: str, user_prompt: str, max_tokens: int = 4000
    ) -> dict[str, Any]:
        content = self._build_multimodal_content(user_prompt)
        sys2 = system_prompt + "\nReturn ONLY valid JSON, no markdown, no backticks."
        msg = await self.anthropic_client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            system=sys2,
            messages=[{"role": "user", "content": content}],
        )
        raw_text = ""
        for block in msg.content:
            if hasattr(block, "text"):
                raw_text += block.text
        cleaned = raw_text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            retry_blocks = list(content)
            retry_blocks.append(
                {
                    "type": "text",
                    "text": "Your previous reply was not valid JSON. Return ONLY valid JSON.",
                }
            )
            msg2 = await self.anthropic_client.messages.create(
                model=settings.anthropic_model,
                max_tokens=max_tokens,
                system=sys2,
                messages=[{"role": "user", "content": retry_blocks}],
            )
            raw2 = ""
            for block in msg2.content:
                if hasattr(block, "text"):
                    raw2 += block.text
            c2 = raw2.strip()
            c2 = re.sub(r"^```(?:json)?\s*", "", c2)
            c2 = re.sub(r"\s*```$", "", c2)
            try:
                return json.loads(c2)
            except json.JSONDecodeError:
                return {"parse_error": True, "raw": c2}
