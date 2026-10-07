"""AI model router — task complexity → model selection."""

from __future__ import annotations

from typing import Any

from app.config import settings


def _complexity_from_artifacts(artifacts: dict[str, dict[str, Any]]) -> str:
    change_risk = artifacts.get("change_risk_report") or {}
    risk = int(change_risk.get("final_risk") or 0)
    diff = artifacts.get("diff") or {}
    diff_len = len(str(diff.get("diff") or ""))
    if risk >= 60 or diff_len > 50000:
        return "high"
    if risk >= 30 or diff_len > 10000:
        return "medium"
    return "low"


def build_model_routing_plan(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    complexity = _complexity_from_artifacts(artifacts)
    small = settings.small_model_slug
    default = settings.anthropic_model

    routes: list[dict[str, Any]] = [
        {
            "task": "lint_explanation",
            "agent": "CodeAnalysisAgent",
            "model": small if complexity == "low" else settings.code_analysis_model,
            "reason": "Small model for trivial diffs; sonnet for complex refactors",
        },
        {
            "task": "security_explanation",
            "agent": "SecurityAgent",
            "model": settings.security_model,
            "reason": "Scanner findings are deterministic; LLM explains only",
        },
        {
            "task": "rca_and_incident",
            "agent": "MonitoringAgent",
            "model": settings.monitoring_model if complexity != "low" else small,
            "reason": "Reasoning model for multi-signal RCA",
        },
        {
            "task": "approval_synthesis",
            "agent": "ApprovalAgent",
            "model": settings.approval_model,
            "reason": "High-stakes gate — always use configured approval model",
        },
        {
            "task": "autonomous_fix",
            "agent": "SoftwareEngineerAgent",
            "model": default if complexity == "high" else settings.code_analysis_model,
            "reason": "Patch generation scales with change complexity",
        },
    ]

    if not settings.model_router_enabled:
        for route in routes:
            agent = route["agent"]
            mapping = {
                "CodeAnalysisAgent": settings.code_analysis_model,
                "SecurityAgent": settings.security_model,
                "MonitoringAgent": settings.monitoring_model,
                "ApprovalAgent": settings.approval_model,
                "SoftwareEngineerAgent": settings.code_analysis_model,
            }
            route["model"] = mapping.get(agent, default)

    return {
        "complexity": complexity,
        "routes": routes,
        "router_enabled": settings.model_router_enabled,
        "small_model": small,
        "default_model": default,
        "summary": f"Model router: complexity={complexity}, {len(routes)} route(s) planned.",
    }
