"""FinOps cost estimation from pipeline run metadata and artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def compute_pipeline_cost(
    *,
    run_id: str,
    repo: str,
    duration_seconds: float | None,
    artifacts: dict[str, dict[str, Any]],
    llm_cost_per_1k_tokens: float = 0.003,
    compute_cost_per_minute: float = 0.008,
) -> dict[str, Any]:
    duration = max(0.0, float(duration_seconds or 0))
    compute_usd = round((duration / 60.0) * compute_cost_per_minute, 4)

    llm_tokens = 0
    token_sources: list[dict[str, Any]] = []
    for key, block in artifacts.items():
        if not isinstance(block, dict):
            continue
        used = int(block.get("tokens_used") or 0)
        if used:
            llm_tokens += used
            token_sources.append({"artifact": key, "tokens": used})

    llm_usd = round((llm_tokens / 1000.0) * llm_cost_per_1k_tokens, 4)
    deploy = artifacts.get("deployment_info") or {}
    docker_usd = 0.02 if deploy and not deploy.get("simulated") and deploy.get("success") else 0.005
    stress_usd = 0.01 if artifacts.get("stress_report") and not (artifacts.get("stress_report") or {}).get("skipped") else 0.0
    storage_usd = 0.001 * len(artifacts)

    breakdown = {
        "compute_usd": compute_usd,
        "llm_usd": llm_usd,
        "docker_build_usd": docker_usd,
        "stress_test_usd": stress_usd,
        "artifact_storage_usd": round(storage_usd, 4),
    }
    total = round(sum(breakdown.values()), 4)

    return {
        "run_id": run_id,
        "repository": repo,
        "total_usd_estimate": total,
        "breakdown": breakdown,
        "llm_tokens": llm_tokens,
        "token_sources": token_sources[:12],
        "duration_seconds": round(duration, 1),
        "currency": "USD",
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "summary": f"Estimated pipeline cost ${total:.4f} ({llm_tokens} LLM tokens, {duration:.0f}s compute).",
    }
