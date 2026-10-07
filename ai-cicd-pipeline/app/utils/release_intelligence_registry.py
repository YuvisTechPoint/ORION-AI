"""Release intelligence registry — promotion paths, DORA bands, and policy defaults."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings

DEFAULT_PROMOTION_PATH = ["dev", "staging", "canary", "production"]

DORA_BANDS: dict[str, dict[str, float]] = {
    "deploy_frequency_per_day": {"elite": 1.0, "high": 0.2, "medium": 0.05},
    "change_failure_rate": {"elite": 0.05, "high": 0.10, "medium": 0.15},
    "lead_time_hours": {"elite": 24.0, "high": 168.0, "medium": 720.0},
    "mttr_hours": {"elite": 1.0, "high": 24.0, "medium": 168.0},
}


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text or text == "{}":
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def resolve_release_policy(repo: str = "") -> dict[str, Any]:
    custom = _parse_json(settings.release_policy_json)
    org = repo.split("/", 1)[0] if "/" in repo else repo
    org_block = custom.get(org) if isinstance(custom.get(org), dict) else {}
    repo_block = custom.get(repo) if isinstance(custom.get(repo), dict) else {}

    max_risk = float(
        repo_block.get("max_risk_score")
        or org_block.get("max_risk_score")
        or settings.release_max_risk_score
    )
    prediction_block = float(
        repo_block.get("prediction_block_threshold")
        or org_block.get("prediction_block_threshold")
        or settings.release_prediction_block_threshold
    )
    require_passport = bool(
        repo_block.get("require_passport_pass")
        if "require_passport_pass" in repo_block
        else org_block.get("require_passport_pass", settings.release_require_passport_pass)
    )

    promotion_raw = repo_block.get("promotion_path") or org_block.get("promotion_path")
    promotion = list(promotion_raw) if isinstance(promotion_raw, list) else list(DEFAULT_PROMOTION_PATH)

    return {
        "repository": repo or None,
        "organization": org or None,
        "max_risk_score": max_risk,
        "prediction_block_threshold": prediction_block,
        "require_passport_pass": require_passport,
        "promotion_path": promotion,
        "dora_bands": DORA_BANDS,
        "summary": (
            f"Release policy: max risk {max_risk:.0f}, "
            f"prediction block ≥{prediction_block:.0f}%, passport required={require_passport}."
        ),
    }
