from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import anthropic
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AgentLog
from app.redis_publish import publish_pipeline_event

logger = logging.getLogger(__name__)


class AgentContractError(Exception):
    """LLM response failed JSON/schema validation."""


class AgentInput(BaseModel):
    pipeline_id: UUID
    stage_name: str
    context: dict[str, Any] = Field(default_factory=dict)


class AgentOutput(BaseModel):
    passed: bool
    summary: str
    artifacts: dict[str, Any] = Field(default_factory=dict)
    next_context: dict[str, Any] = Field(default_factory=dict)


class BaseAgent:
    """Abstract base: subclasses implement run() and response_model."""

    stage_key: str = "base"
    response_model: type[BaseModel]

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def _require_anthropic(self) -> anthropic.Anthropic:
        if not self.settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set — cannot run LLM agents.")
        return anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

    def _call_llm(self, prompt: str, response_schema: type[BaseModel]) -> dict[str, Any]:
        client = self._require_anthropic()
        msg = client.messages.create(
            model=self.settings.anthropic_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        for block in msg.content:
            if block.type == "text":
                text += block.text
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise AgentContractError(f"Invalid JSON from LLM: {e}") from e
        try:
            validated = response_schema.model_validate(data)
        except Exception as e:
            corrective = (
                f"Your previous reply was invalid: {e}\n"
                f"Raw: {text[:2000]}\n"
                "Reply with ONLY valid JSON matching the schema, no markdown."
            )
            msg2 = client.messages.create(
                model=self.settings.anthropic_model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt + "\n\n" + corrective}],
            )
            text2 = ""
            for block in msg2.content:
                if block.type == "text":
                    text2 += block.text
            try:
                data2 = json.loads(text2.strip().split("```json")[-1].split("```")[0] if "```" in text2 else text2)
                validated = response_schema.model_validate(data2)
            except Exception as e2:
                raise AgentContractError(f"Schema validation failed after retry: {e2}") from e2
            return validated.model_dump()
        return validated.model_dump()

    def write_log(
        self,
        pipeline_id: UUID,
        stage: str,
        level: str,
        message: str,
        artifact: dict[str, Any] | None = None,
    ) -> None:
        row = AgentLog(
            pipeline_id=pipeline_id,
            stage=stage,
            level=level,
            message=message,
            timestamp=datetime.now(timezone.utc),
            artifact_json=artifact,
        )
        self.db.add(row)
        self.db.commit()
        ts = row.timestamp.isoformat() if row.timestamp else ""
        publish_pipeline_event(
            str(pipeline_id),
            {
                "type": "log",
                "stage": stage,
                "level": level,
                "message": message,
                "timestamp": ts,
            },
        )

    def emit_artifact(self, pipeline_id: UUID, stage: str, data: dict[str, Any]) -> None:
        publish_pipeline_event(
            str(pipeline_id),
            {"type": "artifact", "stage": stage, "data": data},
        )

    def emit_alert(self, pipeline_id: UUID, message: str, severity: str = "warning") -> None:
        publish_pipeline_event(
            str(pipeline_id),
            {"type": "alert", "message": message, "severity": severity},
        )

    def run(self, inp: AgentInput) -> AgentOutput:
        raise NotImplementedError
