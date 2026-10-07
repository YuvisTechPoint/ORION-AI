"""Unified risk engine registry — org/repo policy and dimension weights."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings

DEFAULT_DIMENSION_WEIGHTS: dict[str, float] = {
    "change_risk": 0.22,
    "quality_gates": 0.18,
    "release_prediction": 0.14,
    "operational_readiness": 0.16,
    "governance_compliance": 0.12,
    "supply_chain": 0.10,
    "knowledge_coverage": 0.08,
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


def resolve_unified_risk_policy(repo: str = "", environment: str = "") -> dict[str, Any]:
    custom = _parse_json(settings.unified_risk_policy_json)
    org = repo.split("/", 1)[0] if "/" in repo else repo
    org_block = custom.get(org) if isinstance(custom.get(org), dict) else {}
    repo_block = custom.get(repo) if isinstance(custom.get(repo), dict) else {}

    def _bool(key: str, default: bool) -> bool:
        if key in repo_block:
            return bool(repo_block[key])
        if key in org_block:
            return bool(org_block[key])
        return default

    def _float(key: str, default: float) -> float:
        raw = repo_block.get(key) if key in repo_block else org_block.get(key)
        if raw is None:
            return default
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    weights = dict(DEFAULT_DIMENSION_WEIGHTS)
    custom_weights = repo_block.get("dimension_weights") or org_block.get("dimension_weights")
    if isinstance(custom_weights, dict):
        for key, value in custom_weights.items():
            if key in weights:
                try:
                    weights[key] = float(value)
                except (TypeError, ValueError):
                    pass
    total = sum(weights.values()) or 1.0
    weights = {k: round(v / total, 4) for k, v in weights.items()}

    return {
        "repository": repo or None,
        "organization": org or None,
        "environment": environment or settings.deploy_environment,
        "enabled": _bool("enabled", settings.unified_risk_enabled),
        "max_unified_score": _float("max_unified_score", settings.unified_risk_max_score),
        "block_on_high": _bool("block_on_high", settings.unified_risk_block_on_high),
        "block_on_critical": _bool("block_on_critical", True),
        "require_gate_fusion_pass": _bool("require_gate_fusion_pass", settings.unified_risk_require_gate_fusion_pass),
        "dimension_weights": weights,
        "intelligence_gate_weight": _float("intelligence_gate_weight", 0.35),
    }
