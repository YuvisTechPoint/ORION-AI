"""Automated root cause analysis from deployments, metrics, and artifacts."""

from __future__ import annotations

from typing import Any


def analyze_root_cause(
    *,
    metrics: dict[str, Any] | None = None,
    artifacts: dict[str, dict[str, Any]] | None = None,
    log_excerpt: str = "",
) -> dict[str, Any]:
    artifacts = artifacts or {}
    metrics = metrics or {}
    deployment = artifacts.get("deployment_info") or {}
    change_risk = artifacts.get("change_risk_report") or {}
    progressive = artifacts.get("progressive_delivery") or {}

    hypotheses: list[dict[str, Any]] = []
    evidence: list[str] = []

    if metrics.get("health_status_code") not in (200, None):
        hypotheses.append(
            {
                "cause": "Health check failure after deployment",
                "confidence": 0.88,
                "component": deployment.get("image_tag") or "staging",
            }
        )
        evidence.append(f"health_status={metrics.get('health_status_code')}")

    if metrics.get("response_time_ms", 0) > 2000:
        hypotheses.append(
            {
                "cause": "Latency regression post-release",
                "confidence": 0.76,
                "component": "api",
            }
        )
        evidence.append(f"p95_proxy={metrics.get('response_time_ms')}ms")

    if progressive and not progressive.get("passed", True):
        hypotheses.append(
            {
                "cause": "Canary/progressive delivery aborted",
                "confidence": 0.82,
                "component": "progressive_delivery",
            }
        )
        evidence.append(progressive.get("summary", "canary failed"))

    risk = int(change_risk.get("final_risk") or 0)
    if risk >= 50:
        hypotheses.append(
            {
                "cause": "High-risk change correlated with incident",
                "confidence": min(0.95, 0.6 + risk / 200),
                "component": ",".join(
                    (change_risk.get("blast_radius_analysis") or {}).get("critical_categories") or []
                )
                or "unknown",
            }
        )
        evidence.append(f"change_risk={risk}/100")

    if "redis" in log_excerpt.lower() or "connection pool" in log_excerpt.lower():
        hypotheses.append(
            {
                "cause": "Redis connection pool exhaustion or latency spike",
                "confidence": 0.84,
                "component": "redis",
            }
        )
        evidence.append("log pattern: redis/pool")

    hypotheses.sort(key=lambda h: h["confidence"], reverse=True)
    top = hypotheses[0] if hypotheses else {
        "cause": "Insufficient correlated evidence — manual investigation required",
        "confidence": 0.35,
        "component": "unknown",
    }

    return {
        "primary_hypothesis": top,
        "hypotheses": hypotheses[:5],
        "evidence": evidence[:10],
        "likely_commit": deployment.get("image_tag") or artifacts.get("metadata", {}).get("commit"),
        "summary": f"RCA: {top['cause']} (confidence {int(top['confidence'] * 100)}%)",
        "analysis_mode": "heuristic",
    }
