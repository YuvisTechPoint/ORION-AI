"""Observability / AIOps intelligence — deploy correlation, anomalies, and service map overlay."""

from __future__ import annotations

import statistics
from typing import Any

from app.config import settings


def correlate_deploy_window(
    *,
    deployment_info: dict[str, Any] | None,
    otel_trace_context: dict[str, Any] | None,
    synthetic_monitoring_report: dict[str, Any] | None,
    stress_report: dict[str, Any] | None,
    error_budget_report: dict[str, Any] | None,
    service_graph: dict[str, Any] | None,
    monitoring_summary: dict[str, Any] | None,
    change_risk_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    deployment = deployment_info or {}
    otel = otel_trace_context or {}
    synthetic = synthetic_monitoring_report or {}
    stress = stress_report or {}
    error_budget = error_budget_report or {}
    graph = service_graph or {}
    monitoring = monitoring_summary or {}
    change_risk = change_risk_report or {}

    deploy_event = {
        "commit": deployment.get("image_tag") or deployment.get("commit"),
        "environment": deployment.get("environment") or settings.deploy_environment,
        "deployed_at": deployment.get("deployed_at"),
        "simulated": deployment.get("simulated", False),
        "success": deployment.get("success"),
        "health_check_passed": deployment.get("health_check_passed"),
    }

    spans = otel.get("spans") or []
    deploy_span = next((s for s in spans if s.get("name") == "pipeline.deploy"), None)
    monitor_span = next((s for s in spans if s.get("name") == "pipeline.monitor"), None)

    timeline: list[dict[str, Any]] = []
    if stress and not stress.get("skipped"):
        timeline.append(
            {
                "phase": "pre_deploy_stress",
                "verdict": stress.get("performance_verdict"),
                "p95_ms": stress.get("p95_ms"),
            }
        )
    if deploy_event.get("deployed_at"):
        timeline.append({"phase": "deploy", "timestamp": deploy_event["deployed_at"], "environment": deploy_event["environment"]})
    if synthetic:
        timeline.append(
            {
                "phase": "post_deploy_synthetic",
                "all_passed": synthetic.get("all_passed"),
                "passed": synthetic.get("passed"),
                "total": synthetic.get("total"),
                "checked_at": synthetic.get("checked_at"),
            }
        )
    if monitoring:
        timeline.append(
            {
                "phase": "runtime_monitoring",
                "checks_performed": monitoring.get("checks_performed"),
                "alerts": monitoring.get("alerts"),
                "final_status": monitoring.get("final_status"),
            }
        )

    blast_radius = {
        "root_service": graph.get("root_service"),
        "changed_services": graph.get("changed_services") or [],
        "downstream_hint": graph.get("downstream_hint") or [],
        "node_count": graph.get("node_count", 0),
    }
    if change_risk.get("final_risk") is not None:
        blast_radius["change_risk_score"] = change_risk.get("final_risk")
        blast_radius["change_risk_level"] = change_risk.get("risk_level")

    confidence = 0.55
    if deploy_event.get("deployed_at") and otel.get("trace_id"):
        confidence += 0.15
    if synthetic.get("checked_at"):
        confidence += 0.15
    if monitoring:
        confidence += 0.1
    if stress and not stress.get("skipped"):
        confidence += 0.05

    return {
        "deploy_event": deploy_event,
        "trace_id": otel.get("trace_id"),
        "deploy_span": deploy_span,
        "monitor_span": monitor_span,
        "timeline": timeline,
        "blast_radius": blast_radius,
        "error_budget_remaining_percent": error_budget.get("error_budget_remaining_percent"),
        "monitoring_status": "available" if monitoring else "pending",
        "correlation_confidence": round(min(confidence, 0.98), 2),
        "summary": (
            f"Deploy correlated to trace {str(otel.get('trace_id', ''))[:12]}…; "
            f"{len(blast_radius.get('changed_services') or [])} service(s) in blast radius; "
            f"monitoring {('available' if monitoring else 'pending')}."
        ),
    }


def detect_metric_anomalies(
    *,
    synthetic_monitoring_report: dict[str, Any] | None,
    stress_report: dict[str, Any] | None,
    historical_synthetic: list[dict[str, Any]] | None = None,
    historical_stress: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    synthetic = synthetic_monitoring_report or {}
    stress = stress_report or {}
    hist_syn = historical_synthetic or []
    hist_stress = historical_stress or []

    anomalies: list[dict[str, Any]] = []

    journey_latencies = [
        float(j.get("latency_ms"))
        for j in synthetic.get("journeys") or []
        if j.get("latency_ms") is not None and j.get("passed")
    ]
    hist_latencies: list[float] = []
    for report in hist_syn:
        for journey in report.get("journeys") or []:
            if journey.get("passed") and journey.get("latency_ms") is not None:
                hist_latencies.append(float(journey["latency_ms"]))

    if journey_latencies and hist_latencies:
        baseline = statistics.median(hist_latencies)
        current = statistics.median(journey_latencies)
        if baseline > 0 and current > baseline * 1.5 and current - baseline > 50:
            anomalies.append(
                {
                    "type": "latency_regression",
                    "severity": "medium",
                    "description": f"synthetic latency {current:.0f}ms vs baseline {baseline:.0f}ms",
                    "current_ms": round(current, 1),
                    "baseline_ms": round(baseline, 1),
                }
            )

    if synthetic and not synthetic.get("all_passed", True):
        failed = [j.get("journey") for j in synthetic.get("journeys") or [] if not j.get("passed")]
        anomalies.append(
            {
                "type": "synthetic_failure",
                "severity": "high",
                "description": f"synthetic journeys failed: {', '.join(str(x) for x in failed) or 'unknown'}",
            }
        )

    p95 = stress.get("p95_ms")
    hist_p95 = [float(r.get("p95_ms")) for r in hist_stress if r.get("p95_ms") is not None]
    if p95 is not None and hist_p95:
        baseline_p95 = statistics.median(hist_p95)
        if float(p95) > max(baseline_p95 * 1.25, baseline_p95 + 200):
            anomalies.append(
                {
                    "type": "stress_p95_spike",
                    "severity": "medium",
                    "description": f"stress p95 {p95}ms vs historical median {baseline_p95:.0f}ms",
                }
            )

    if str(stress.get("performance_verdict", "")).lower() == "fail":
        anomalies.append(
            {
                "type": "stress_verdict_fail",
                "severity": "high",
                "description": "stress test failed before deploy window",
            }
        )

    high = sum(1 for a in anomalies if a.get("severity") == "high")
    verdict = "pass"
    if high:
        verdict = "fail" if settings.observability_anomaly_gate_enabled else "warn"
    elif anomalies:
        verdict = "warn"

    return {
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
        "high_severity_count": high,
        "verdict": verdict,
        "summary": f"{len(anomalies)} metric anomaly signal(s); verdict={verdict}.",
    }


def analyze_log_signals(
    *,
    monitoring_summary: dict[str, Any] | None,
    log_excerpt: str = "",
) -> dict[str, Any]:
    monitoring = monitoring_summary or {}
    assessment = monitoring.get("assessment") or {}
    anomalies = list(assessment.get("anomalies") or [])

    excerpt = (log_excerpt or "").strip()
    error_lines = [ln for ln in excerpt.splitlines() if "error" in ln.lower()][:10]
    if error_lines and not anomalies:
        anomalies.append(
            {
                "type": "log_errors",
                "description": f"{len(error_lines)} error line(s) in excerpt",
                "severity": "medium",
            }
        )

    status = assessment.get("status") or ("healthy" if not error_lines else "degraded")
    action = assessment.get("recommended_action") or "monitor"

    return {
        "status": status,
        "recommended_action": action,
        "anomalies": anomalies,
        "error_line_sample": error_lines[:3],
        "monitoring_checks": monitoring.get("checks_performed"),
        "summary": f"Log/monitoring signals: {status}; action={action}; {len(anomalies)} anomaly item(s).",
    }


def build_runtime_service_map(
    service_graph: dict[str, Any] | None,
    *,
    deployment_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    graph = service_graph or {}
    deployment = deployment_info or {}
    nodes = graph.get("nodes") or {}
    changed = set(graph.get("changed_services") or [])

    runtime_nodes: list[dict[str, Any]] = []
    for name, meta in nodes.items():
        runtime_nodes.append(
            {
                "name": name,
                "type": meta.get("type"),
                "source": meta.get("source"),
                "changed_in_deploy": name in changed,
            }
        )

    return {
        "root_service": graph.get("root_service"),
        "nodes": runtime_nodes,
        "edges": graph.get("edges") or [],
        "node_count": graph.get("node_count", len(runtime_nodes)),
        "edge_count": graph.get("edge_count", len(graph.get("edges") or [])),
        "changed_services": sorted(changed),
        "deploy_environment": deployment.get("environment") or settings.deploy_environment,
        "summary": graph.get("summary") or f"{len(runtime_nodes)} service node(s) mapped for runtime overlay.",
    }


def evaluate_observability_gates(report: dict[str, Any]) -> dict[str, Any]:
    violations: list[str] = []
    correlation = report.get("deploy_correlation") or {}
    if correlation.get("monitoring_status") == "available":
        monitoring = (report.get("log_signals") or {}).get("status")
        if monitoring in {"degraded", "critical"}:
            violations.append(f"runtime monitoring {monitoring}")

    anomalies = report.get("metric_anomalies") or {}
    if anomalies.get("verdict") == "fail":
        violations.extend(
            a.get("description", str(a)) if isinstance(a, dict) else str(a)
            for a in anomalies.get("anomalies") or []
        )
    elif anomalies.get("verdict") == "warn" and anomalies.get("anomalies"):
        violations.append(f"{anomalies.get('anomaly_count', 0)} metric anomaly signal(s)")

    synthetic = (report.get("signals") or {}).get("synthetic_monitoring") or {}
    if synthetic and synthetic.get("all_passed") is False:
        violations.append("post-deploy synthetic checks failed")

    if violations and (
        (anomalies.get("verdict") == "fail" and settings.observability_anomaly_gate_enabled)
        or (report.get("log_signals") or {}).get("status") == "critical"
        or synthetic.get("all_passed") is False
    ):
        gate = "fail"
    elif violations:
        gate = "warn"
    else:
        gate = "pass"
    return {"gate_verdict": gate, "violations": violations}


def build_observability_intelligence_report(
    *,
    deployment_info: dict[str, Any] | None = None,
    otel_trace_context: dict[str, Any] | None = None,
    synthetic_monitoring_report: dict[str, Any] | None = None,
    stress_report: dict[str, Any] | None = None,
    error_budget_report: dict[str, Any] | None = None,
    service_graph: dict[str, Any] | None = None,
    monitoring_summary: dict[str, Any] | None = None,
    change_risk_report: dict[str, Any] | None = None,
    historical_synthetic: list[dict[str, Any]] | None = None,
    historical_stress: list[dict[str, Any]] | None = None,
    log_excerpt: str = "",
) -> dict[str, Any]:
    correlation = correlate_deploy_window(
        deployment_info=deployment_info,
        otel_trace_context=otel_trace_context,
        synthetic_monitoring_report=synthetic_monitoring_report,
        stress_report=stress_report,
        error_budget_report=error_budget_report,
        service_graph=service_graph,
        monitoring_summary=monitoring_summary,
        change_risk_report=change_risk_report,
    )
    metric_anomalies = detect_metric_anomalies(
        synthetic_monitoring_report=synthetic_monitoring_report,
        stress_report=stress_report,
        historical_synthetic=historical_synthetic,
        historical_stress=historical_stress,
    )
    log_signals = analyze_log_signals(monitoring_summary=monitoring_summary, log_excerpt=log_excerpt)
    service_map = build_runtime_service_map(service_graph, deployment_info=deployment_info)

    report: dict[str, Any] = {
        "deploy_correlation": correlation,
        "metric_anomalies": metric_anomalies,
        "log_signals": log_signals,
        "service_map": service_map,
        "signals": {
            "otel_trace_id": (otel_trace_context or {}).get("trace_id"),
            "synthetic_monitoring": synthetic_monitoring_report,
            "stress_verdict": (stress_report or {}).get("performance_verdict"),
            "error_budget_remaining_percent": (error_budget_report or {}).get("error_budget_remaining_percent"),
        },
        "analysis_mode": "heuristic",
    }
    report["gates"] = evaluate_observability_gates(report)
    report["gate_verdict"] = report["gates"]["gate_verdict"]
    report["summary"] = (
        f"Observability {report['gate_verdict']}: "
        f"correlation={correlation.get('correlation_confidence')}, "
        f"anomalies={metric_anomalies.get('anomaly_count', 0)}, "
        f"monitoring={correlation.get('monitoring_status')}."
    )
    return report
