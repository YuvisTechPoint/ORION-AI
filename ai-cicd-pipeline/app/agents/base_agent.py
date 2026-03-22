import json
import re
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun


class BaseAgent(ABC):
    def __init__(
        self,
        pipeline_run_id: uuid.UUID,
        db: AsyncSession,
        anthropic_client: AsyncAnthropic,
    ) -> None:
        self.pipeline_run_id = pipeline_run_id
        self.db = db
        self.anthropic_client = anthropic_client
        self.start_time = time.time()

    @abstractmethod
    async def execute(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    async def _call_claude(
        self, system_prompt: str, user_message: str, max_tokens: int = 2000
    ) -> tuple[str, int]:
        msg = await self.anthropic_client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        text = ""
        for block in msg.content:
            if hasattr(block, "text"):
                text += block.text
        tokens = getattr(msg.usage, "output_tokens", 0) or 0
        return text, int(tokens)

    async def _call_claude_json(
        self, system_prompt: str, user_message: str, max_tokens: int = 2000
    ) -> dict[str, Any]:
        sys2 = system_prompt + "\nReturn ONLY valid JSON, no markdown, no backticks."
        um = user_message
        last_cleaned = ""
        for attempt in range(2):
            text, _ = await self._call_claude(sys2, um, max_tokens=max_tokens)
            cleaned = text.strip()
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            last_cleaned = cleaned
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                um = user_message + "\nYour previous reply was not valid JSON. Return ONLY valid JSON."
                if attempt == 1:
                    break
        return {"parse_error": True, "raw": last_cleaned}

    async def _save_artifact(
        self,
        artifact_type: str,
        content: dict[str, Any],
        raw_output: str | None = None,
        tokens_used: int | None = None,
        duration_seconds: float | None = None,
    ) -> PipelineArtifact:
        art = PipelineArtifact(
            pipeline_run_id=self.pipeline_run_id,
            artifact_type=artifact_type,
            content=content,
            raw_output=raw_output,
            agent_model=settings.anthropic_model,
            tokens_used=tokens_used,
            duration_seconds=duration_seconds,
        )
        self.db.add(art)
        await self.db.commit()
        await self.db.refresh(art)
        return art

    async def _update_run_status(
        self, status: str, error_message: str | None = None
    ) -> None:
        r = await self.db.execute(
            select(PipelineRun).where(PipelineRun.id == self.pipeline_run_id)
        )
        run = r.scalar_one_or_none()
        if not run:
            return
        run.status = status
        if error_message is not None:
            run.error_message = error_message
        await self.db.commit()
