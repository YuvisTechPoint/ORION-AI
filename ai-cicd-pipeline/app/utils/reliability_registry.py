"""Reliability registry — chaos experiment catalog and org/repo policy defaults."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings

DEFAULT_EXPERIMENTS: list[dict[str, Any]] = [
    {
        "name": "container_kill",
        "description": "Simulate primary container failure and verify restart",
        "severity": "high",
        "category": "availability",
    },
    {
        "name": "latency_injection",
        "description": "Inject 500ms latency on API path",
        "severity": "medium",
        "category": "performance",
    },
    {
        "name": "dependency_failure",
        "description": "Simulate Redis/cache dependency unreachable",
        "severity": "high",
        "category": "dependency",
    },
    {
        "name": "network_partition",
        "description": "Simulate split-brain between app and database",
        "severity": "critical",
        "category": "network",
    },
    {
        "name": "cpu_stress",
        "description": "Simulate CPU saturation under load",
        "severity": "medium",
        "category": "saturation",
    },
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


def list_chaos_experiments() -> list[dict[str, Any]]:
    custom = _parse_json(settings.chaos_policy_json)
    extra = custom.get("experiments")
    if isinstance(extra, list) and extra:
        return [e for e in extra if isinstance(e, dict) and e.get("name")]
    return list(DEFAULT_EXPERIMENTS)


def resolve_reliability_policy(repo: str = "") -> dict[str, Any]:
    custom = _parse_json(settings.chaos_policy_json)
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

    experiments_raw = repo_block.get("experiments") or org_block.get("experiments")
    if isinstance(experiments_raw, list) and experiments_raw:
        experiment_names = [str(e) for e in experiments_raw]
    else:
        experiment_names = [e["name"] for e in list_chaos_experiments()]

    simulated = _bool("simulated", settings.chaos_simulated_default)
    require_synthetic = _bool("require_synthetic_pass", settings.reliability_require_synthetic_pass)
    min_score = _float("min_resilience_score", settings.reliability_min_resilience_score)

    return {
        "repository": repo or None,
        "organization": org or None,
        "simulated": simulated,
        "live_chaos_enabled": settings.chaos_live_enabled,
        "require_synthetic_pass": require_synthetic,
        "min_resilience_score": min_score,
        "experiment_names": experiment_names,
        "experiments": list_chaos_experiments(),
        "summary": (
            f"Reliability policy: simulated={simulated}, "
            f"{len(experiment_names)} experiment(s), min resilience {min_score:.0f}%."
        ),
    }
