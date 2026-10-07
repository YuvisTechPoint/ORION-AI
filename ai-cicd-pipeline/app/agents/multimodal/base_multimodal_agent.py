import base64
import io
import zipfile
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import LLM_ERROR_KEY, BaseAgent

MAX_TEXT_CHARS = 50_000
IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_EXT_TYPES = {
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".gif": ("image", "image/gif"),
    ".webp": ("image", "image/webp"),
    ".pdf": ("pdf", "application/pdf"),
    ".csv": ("csv", "text/csv"),
    ".log": ("log", "text/plain"),
    ".zip": ("zip", "application/zip"),
}


def artifact_from_upload(filename: str, content_type: str | None, data: bytes) -> dict[str, Any]:
    name = (filename or "file").lower()
    mime = (content_type or "").lower()
    for ext, (atype, default_mime) in _EXT_TYPES.items():
        if name.endswith(ext):
            return {"type": atype, "content": data, "filename": filename, "mime_type": default_mime}
    if mime in IMAGE_MIME_TYPES:
        return {"type": "image", "content": data, "filename": filename, "mime_type": mime}
    if mime == "application/pdf":
        return {"type": "pdf", "content": data, "filename": filename, "mime_type": mime}
    if mime in ("application/zip", "application/x-zip-compressed"):
        return {"type": "zip", "content": data, "filename": filename, "mime_type": "application/zip"}
    return {"type": "text", "content": data, "filename": filename, "mime_type": mime or "text/plain"}


def as_text(content: bytes | str | Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, (bytes, bytearray)):
        return bytes(content).decode("utf-8", errors="replace")
    return str(content)


def as_bytes(content: bytes | str | Any) -> bytes:
    if isinstance(content, (bytes, bytearray)):
        return bytes(content)
    return str(content).encode("utf-8")


def extract_zip_text_files(data: bytes, suffixes: tuple[str, ...] = (".txt", ".log")) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in sorted(zf.namelist()):
            if name.endswith("/") or not name.lower().endswith(suffixes):
                continue
            out.append(
                {
                    "type": "text",
                    "content": zf.read(name).decode("utf-8", errors="replace"),
                    "filename": name,
                    "mime_type": "text/plain",
                }
            )
    return out


class BaseMultimodalAgent(BaseAgent):
    artifact_type = "multimodal_analysis"

    def __init__(
        self,
        pipeline_run_id: UUID | str | None = None,
        db: AsyncSession | None = None,
        anthropic_client: AsyncAnthropic | None = None,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.artifacts: list[dict[str, Any]] = list(artifacts or [])

    def text_artifacts(self) -> list[dict[str, Any]]:
        return [a for a in self.artifacts if a.get("type") in ("text", "csv", "log")]

    def combined_text(self) -> str:
        return "\n".join(as_text(a.get("content", "")) for a in self.text_artifacts())

    def _build_multimodal_message(self, text_prompt: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for art in self.artifacts:
            atype = str(art.get("type", "text")).lower()
            filename = art.get("filename") or "file"
            mime = str(art.get("mime_type") or "").lower()
            content = art.get("content", b"")

            if atype == "image":
                media_type = mime if mime in IMAGE_MIME_TYPES else "image/png"
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.b64encode(as_bytes(content)).decode("ascii"),
                        },
                    }
                )
            elif atype == "pdf":
                blocks.append(
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64.b64encode(as_bytes(content)).decode("ascii"),
                        },
                    }
                )
            elif atype == "zip":
                try:
                    for inner in extract_zip_text_files(as_bytes(content)):
                        blocks.append(
                            {
                                "type": "text",
                                "text": f"FILE: {filename}::{inner['filename']}\n{inner['content'][:MAX_TEXT_CHARS]}",
                            }
                        )
                except zipfile.BadZipFile:
                    blocks.append({"type": "text", "text": f"FILE: {filename}\n<invalid zip archive>"})
            else:
                blocks.append({"type": "text", "text": f"FILE: {filename}\n{as_text(content)[:MAX_TEXT_CHARS]}"})

        blocks.append({"type": "text", "text": text_prompt})
        return blocks

    async def _call_claude_multimodal(
        self, system_prompt: str, text_prompt: str, max_tokens: int = 3000
    ) -> tuple[str, int]:
        return await self._call_claude(
            system_prompt, self._build_multimodal_message(text_prompt), max_tokens=max_tokens
        )

    async def _analyze_json(
        self, system_prompt: str, text_prompt: str, fallback: dict[str, Any], required_key: str, max_tokens: int = 3000
    ) -> dict[str, Any]:
        """Ask Claude for structured JSON; use the deterministic fallback when unavailable."""
        result = await self._call_claude_json(
            system_prompt, self._build_multimodal_message(text_prompt), max_tokens=max_tokens
        )
        if LLM_ERROR_KEY in result or required_key not in result:
            fallback = dict(fallback)
            fallback["analysis_mode"] = "heuristic"
            if LLM_ERROR_KEY in result:
                fallback["llm_unavailable_reason"] = result[LLM_ERROR_KEY][:300]
            return fallback
        result["analysis_mode"] = "llm"
        return result

    async def _persist(self, result: dict[str, Any], artifact_type: str | None = None) -> dict[str, Any]:
        result.setdefault("artifacts_analyzed", [a.get("filename") for a in self.artifacts])
        await self._save_artifact(artifact_type or self.artifact_type, result, duration_seconds=self.elapsed_seconds)
        return result
