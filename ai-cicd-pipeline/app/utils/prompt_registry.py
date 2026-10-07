"""Versioned prompt registry for ORION agents."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

PROMPT_VERSIONS: dict[str, dict[str, Any]] = {
    "CodeAnalysisAgent": {"version": "1.2.0", "hash": "code-v12", "owner": "platform"},
    "SecurityAgent": {"version": "1.1.0", "hash": "sec-v11", "owner": "security"},
    "QAAgent": {"version": "1.0.3", "hash": "qa-v103", "owner": "platform"},
    "ApprovalAgent": {"version": "2.0.0", "hash": "appr-v20", "owner": "governance"},
    "MonitoringAgent": {"version": "1.3.0", "hash": "mon-v13", "owner": "sre"},
    "SoftwareEngineerAgent": {"version": "1.0.1", "hash": "se-v101", "owner": "platform"},
}


def build_prompt_registry_snapshot(*, agents: list[str] | None = None) -> dict[str, Any]:
    agents = agents or list(PROMPT_VERSIONS.keys())
    prompts = []
    for name in agents:
        meta = PROMPT_VERSIONS.get(name, {"version": "unknown", "hash": "unknown", "owner": "unknown"})
        prompts.append({"agent": name, **meta})
    return {
        "prompts": prompts,
        "registry_size": len(prompts),
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "summary": f"Prompt registry: {len(prompts)} prompt version(s) tracked.",
    }
