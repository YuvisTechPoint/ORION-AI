"""Load stack catalog from config/stacks.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "config" / "stacks.json"


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        return {"host": "127.0.0.1", "stacks": []}
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def stack_entries(*, include_hub: bool = False) -> list[dict[str, Any]]:
    stacks = load_catalog().get("stacks") or []
    if include_hub:
        return list(stacks)
    return [s for s in stacks if s.get("id") != "hub" and s.get("api")]


def stack_by_id(stack_id: str) -> dict[str, Any] | None:
    for stack in stack_entries(include_hub=True):
        if stack.get("id") == stack_id:
            return stack
    return None
