import asyncio
import contextlib
import inspect
import json
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import TERMINAL_STATUSES, PipelineRun
from app.services.events import publish_event
from app.utils.json_utils import extract_json
from app.utils.logger import get_logger
from app.utils.text_analysis import redact_secrets, sanitize_for_agent, truncate_with_context
from app.utils.prompt_injection_firewall import sanitize_untrusted_input

JSON_SUFFIX = "Return ONLY valid JSON, no markdown, no backticks, no explanation."
LLM_ERROR_KEY = "_llm_error"
# After Anthropic rejects the key, stop hammering it from every agent of every run for a while.
LLM_AUTH_COOLDOWN_SECONDS = 300.0

_llm_state: dict[str, Any] = {"status": "unverified", "detail": None, "checked_at": None, "retry_after": 0.0}


def llm_status() -> dict[str, Any]:
    """Process-local view of the Anthropic integration: unverified | ok | auth_failed | error."""
    if not settings.llm_enabled:
        return {"status": "disabled", "detail": "ANTHROPIC_API_KEY is not configured", "checked_at": None}
    return {k: _llm_state[k] for k in ("status", "detail", "checked_at")}


def _record_llm(status: str, detail: str | None = None, cooldown: float = 0.0) -> None:
    _llm_state.update(
        status=status,
        detail=detail,
        checked_at=datetime.now(timezone.utc).isoformat(),
        retry_after=time.monotonic() + cooldown if cooldown else 0.0,
    )


class BaseAgent(ABC):
    def __init__(
        self,
        pipeline_run_id: uuid.UUID | str | None,
        db: AsyncSession | None,
        anthropic_client: AsyncAnthropic | None,
    ) -> None:
        if isinstance(pipeline_run_id, str):
            pipeline_run_id = uuid.UUID(pipeline_run_id)
        self.pipeline_run_id = pipeline_run_id
        self.db = db
        self.anthropic_client = anthropic_client
        self.logger = get_logger(f"agent.{self.__class__.__name__}")
        self.start_time: float | None = time.time()
        self.tokens_used = 0
        self.agent_model = settings.anthropic_model
        self.memory_enabled = settings.agent_memory_enabled

    @abstractmethod
    async def execute(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time if self.start_time else 0.0

    @property
    def memory_store(self) -> Any:
        if self.db is None:
            return None
        return self.db.info.get("_orion_memory")

    def _memory_scope_id(self) -> str | None:
        return str(self.pipeline_run_id) if self.pipeline_run_id else None

    def _inject_memory_prefix(self, user_message: Any) -> Any:
        store = self.memory_store
        scope_id = self._memory_scope_id()
        if not self.memory_enabled or store is None or not scope_id:
            return user_message
        ctx = store.get_context(self.__class__.__name__, scope_id, limit=settings.agent_memory_context_limit)
        if not ctx:
            return user_message
        prefix = "Prior agent interactions for this pipeline run:\n"
        for item in ctx[-settings.agent_memory_context_limit :]:
            resp = item.get("response_payload") or {}
            summary = resp.get("summary") if isinstance(resp, dict) else str(resp)
            prefix += f"- {self.__class__.__name__}: {str(summary)[:240]}\n"
        if isinstance(user_message, str):
            return f"{prefix}\n{user_message}"
        return [{"type": "text", "text": prefix}, *user_message]

    def _record_memory(self, prompt_payload: dict[str, Any], response_payload: dict[str, Any]) -> None:
        store = self.memory_store
        scope_id = self._memory_scope_id()
        if not self.memory_enabled or store is None or not scope_id:
            return
        store.append_interaction(self.__class__.__name__, scope_id, prompt_payload, response_payload)

    def _db_lock(self) -> asyncio.Lock | contextlib.AbstractAsyncContextManager:
        # Agents may run concurrently (FullScanOrchestrator) on one AsyncSession, which
        # SQLAlchemy forbids; serialize all DB work through a lock stored on the session.
        if self.db is None:
            return contextlib.nullcontext()
        lock = self.db.info.get("_orion_lock")
        if lock is None:
            lock = asyncio.Lock()
            self.db.info["_orion_lock"] = lock
        return lock

    async def _call_claude(
        self, system_prompt: str, user_message: Any, max_tokens: int = 2000
    ) -> tuple[str, int]:
        if self.anthropic_client is None:
            raise RuntimeError("Anthropic client not configured")
        real_client = isinstance(self.anthropic_client, AsyncAnthropic)
        if real_client and not settings.llm_enabled:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")
        if real_client and _llm_state["status"] == "auth_failed" and time.monotonic() < _llm_state["retry_after"]:
            raise RuntimeError(f"Anthropic API key was rejected; LLM calls paused ({_llm_state['detail']})")

        started = time.time()
        try:
            result = self.anthropic_client.messages.create(
                model=self.agent_model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            msg = await result if inspect.isawaitable(result) else result
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            if real_client:
                _record_llm("auth_failed", f"{type(exc).__name__}: {getattr(exc, 'message', exc)}"[:300],
                            cooldown=LLM_AUTH_COOLDOWN_SECONDS)
            raise RuntimeError(f"{self.__class__.__name__} Claude call failed: {exc}") from exc
        except anthropic.APIError as exc:
            if real_client:
                _record_llm("error", f"{type(exc).__name__}: {exc}"[:300])
            raise RuntimeError(f"{self.__class__.__name__} Claude call failed: {exc}") from exc
        if real_client:
            _record_llm("ok")

        text = "".join(getattr(block, "text", "") for block in msg.content)
        usage = getattr(msg, "usage", None)
        tokens = int(getattr(usage, "input_tokens", 0) or 0) + int(
            getattr(usage, "output_tokens", 0) or 0
        )
        self.tokens_used += tokens
        self.logger.info(
            "claude call agent=%s tokens=%d duration=%.2fs",
            self.__class__.__name__,
            tokens,
            time.time() - started,
        )
        return text, tokens

    async def _call_claude_json(
        self,
        system_prompt: str,
        user_message: Any,
        max_tokens: int = 2000,
        raise_on_error: bool = False,
    ) -> dict[str, Any]:
        """Return the parsed JSON dict, or {LLM_ERROR_KEY: reason} so callers can fall back to heuristics."""
        system = system_prompt if JSON_SUFFIX in system_prompt else f"{system_prompt}\n{JSON_SUFFIX}"
        message = self._inject_memory_prefix(user_message)
        raw = ""
        try:
            for attempt in range(2):
                raw, _ = await self._call_claude(system, message, max_tokens=max_tokens)
                try:
                    parsed = extract_json(raw)
                    if isinstance(parsed, dict):
                        if LLM_ERROR_KEY not in parsed:
                            prompt_payload = (
                                {"text": user_message[:2000]}
                                if isinstance(user_message, str)
                                else {"content": "structured"}
                            )
                            self._record_memory(prompt_payload, parsed)
                        return parsed
                    payload = {"items": parsed}
                    self._record_memory({"text": str(user_message)[:2000]}, payload)
                    return payload
                except json.JSONDecodeError:
                    if attempt == 0:
                        retry_note = (
                            "Your previous response was not valid JSON. Return ONLY the JSON object."
                        )
                        message = (
                            f"{user_message}\n\n{retry_note}"
                            if isinstance(user_message, str)
                            else [*user_message, {"type": "text", "text": retry_note}]
                        )
            error = f"Invalid JSON from model: {raw[:500]}"
        except RuntimeError as exc:
            error = str(exc)

        if raise_on_error:
            raise ValueError(error)
        self.logger.warning("LLM unavailable, using heuristic fallback: %s", error)
        return {LLM_ERROR_KEY: error}

    def _prepare_llm_text(self, text: str, max_chars: int = 8000) -> str:
        cleaned = sanitize_untrusted_input(text)
        return truncate_with_context(sanitize_for_agent(cleaned), max_chars)

    async def _save_artifact(
        self,
        artifact_type: str,
        content: dict[str, Any],
        raw_output: str | None = None,
        tokens_used: int | None = None,
        duration_seconds: float | None = None,
    ) -> PipelineArtifact | None:
        if self.db is None or self.pipeline_run_id is None:
            return None
        if raw_output is not None:
            raw_output = redact_secrets(raw_output)
        art = PipelineArtifact(
            pipeline_run_id=self.pipeline_run_id,
            artifact_type=artifact_type,
            content=content,
            raw_output=raw_output,
            agent_model=self.agent_model,
            tokens_used=tokens_used if tokens_used is not None else (self.tokens_used or None),
            duration_seconds=duration_seconds if duration_seconds is not None else self.elapsed_seconds,
        )
        async with self._db_lock():
            self.db.add(art)
            await self.db.commit()
            await self.db.refresh(art)
        publish_event(
            self.pipeline_run_id,
            {
                "kind": "artifact",
                "artifact_type": artifact_type,
                "agent": self.__class__.__name__,
                "summary": _artifact_summary(artifact_type, content),
            },
        )
        return art

    async def _update_run_status(self, status: str, error_message: str | None = None) -> None:
        if self.db is None or self.pipeline_run_id is None:
            return
        async with self._db_lock():
            r = await self.db.execute(
                select(PipelineRun).where(PipelineRun.id == self.pipeline_run_id)
            )
            run = r.scalar_one_or_none()
            if not run:
                return
            run.status = status
            if error_message is not None:
                run.error_message = error_message
            if status in TERMINAL_STATUSES:
                run.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
        publish_event(self.pipeline_run_id, {"kind": "stage-update", "stage": status, "status": status})


def _artifact_summary(artifact_type: str, content: Any) -> str:
    from app.utils.artifact_summaries import summarize_artifact

    return summarize_artifact(artifact_type, content)[:300]
