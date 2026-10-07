"""FinOps registry — budgets, allocation dimensions, and chargeback defaults."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings

DEFAULT_ALLOCATION_DIMENSIONS: list[str] = [
    "repository",
    "agent",
    "model",
    "stage",
    "environment",
]


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text or text == "{}":
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def resolve_finops_budgets(repo: str = "") -> dict[str, Any]:
    custom = _parse_json(settings.finops_budget_json)
    org = repo.split("/", 1)[0] if "/" in repo else repo
    org_block = custom.get(org) if isinstance(custom.get(org), dict) else {}
    repo_block = custom.get(repo) if isinstance(custom.get(repo), dict) else {}
    per_run = float(
        repo_block.get("per_run_usd")
        or org_block.get("per_run_usd")
        or settings.finops_budget_usd_per_run
    )
    monthly = float(
        repo_block.get("monthly_usd")
        or org_block.get("monthly_usd")
        or settings.finops_budget_usd_monthly
    )
    return {
        "per_run_usd": per_run,
        "monthly_usd": monthly,
        "repository": repo or None,
        "organization": org or None,
        "dimensions": DEFAULT_ALLOCATION_DIMENSIONS,
        "llm_cost_per_1k_tokens": settings.finops_llm_cost_per_1k_tokens,
        "compute_cost_per_minute": settings.finops_compute_cost_per_minute,
        "summary": f"FinOps budgets: ${per_run:.2f}/run, ${monthly:.2f}/month.",
    }
