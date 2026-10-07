"""Multi-layer code review intelligence (L0–L7) with bug-prediction heuristics."""

from __future__ import annotations

from typing import Any

from app.utils.change_risk import analyze_changed_paths
from app.utils.gate_fusion import fuse_stage_results

_LAYER_WEIGHTS = {
    "L0_syntax": 0.10,
    "L1_static": 0.12,
    "L2_semantic": 0.14,
    "L3_architecture": 0.12,
    "L4_security": 0.14,
    "L5_performance": 0.10,
    "L6_maintainability": 0.10,
    "L7_production_risk": 0.18,
}

_SYNTAX_TYPES = frozenset({"syntax-error", "undefined-name", "parse-error", "invalid-syntax"})
_STATIC_TYPES = frozenset(
    {
        "unused-import",
        "unused-variable",
        "pylint",
        "convention",
        "refactor",
        "warning",
        "ast",
    }
)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(max(lo, min(hi, round(value))))


def _layer(verdict: str, score: int, findings: list[dict[str, Any]], summary: str) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "score": _clamp(score),
        "finding_count": len(findings),
        "findings": findings[:12],
        "summary": summary,
    }


def _severity_to_score(raw: str, *, fail: int = 25, warn: int = 55, pass_score: int = 92) -> tuple[int, str]:
    level = str(raw or "").lower()
    if level in {"fail", "critical", "high"}:
        return fail, "fail"
    if level in {"warn", "medium"}:
        return warn, "warn"
    if level in {"low"}:
        return 75, "warn"
    return pass_score, "pass"


def _build_l0_syntax(code: dict[str, Any]) -> dict[str, Any]:
    issues = code.get("issues") or []
    syntax = [
        i
        for i in issues
        if isinstance(i, dict) and str(i.get("type") or "").lower() in _SYNTAX_TYPES
    ]
    count = len(syntax)
    if count >= 3:
        verdict, score = "fail", max(10, 100 - count * 30)
    elif count >= 1:
        verdict, score = "warn", max(40, 100 - count * 20)
    else:
        verdict, score = "pass", 100
    summary = f"{count} syntax-level issue(s)" if count else "No syntax blockers detected"
    return _layer(verdict, score, syntax, summary)


def _build_l1_static(code: dict[str, Any]) -> dict[str, Any]:
    issues = code.get("issues") or []
    static = [
        i
        for i in issues
        if isinstance(i, dict)
        and (
            str(i.get("type") or "").lower() in _STATIC_TYPES
            or str(i.get("type") or "").startswith("pylint")
        )
    ]
    errors = int(code.get("critical_issues_count") or 0)
    warnings = int(code.get("warnings_count") or 0)
    count = len(static) + errors
    if errors >= 3 or count >= 8:
        verdict, score = "fail", max(15, 100 - count * 8)
    elif errors >= 1 or count >= 3:
        verdict, score = "warn", max(45, 100 - count * 6)
    else:
        verdict, score = "pass", max(70, 100 - warnings * 2)
    summary = f"{count} static analysis signal(s); {warnings} warning(s)"
    return _layer(verdict, score, static[:12], summary)


def _build_l2_semantic(code: dict[str, Any]) -> dict[str, Any]:
    score, verdict = _severity_to_score(str(code.get("severity") or "pass"))
    practices = code.get("good_practices_found") or []
    findings: list[dict[str, Any]] = []
    if code.get("summary"):
        findings.append({"type": "review_summary", "description": str(code.get("summary"))[:400]})
    for practice in practices[:5]:
        if isinstance(practice, str):
            findings.append({"type": "good_practice", "description": practice})
    mode = str(code.get("analysis_mode") or "heuristic")
    summary = f"Semantic review {verdict} ({mode})"
    if practices:
        summary += f"; {len(practices)} good practice(s) noted"
    return _layer(verdict, score, findings, summary)


def _build_l3_architecture(
    service_graph: dict[str, Any],
    repository_intelligence: dict[str, Any],
    changed_files: list[str],
) -> dict[str, Any]:
    path_intel = analyze_changed_paths(changed_files or [])
    nodes = int(service_graph.get("node_count") or len(service_graph.get("nodes") or {}))
    changed_services = service_graph.get("changed_services") or []
    blast = path_intel.get("blast_radius_score") or 0
    stack = repository_intelligence.get("stack") or repository_intelligence.get("primary_stack") or "unknown"
    findings: list[dict[str, Any]] = []
    for category, paths in (path_intel.get("critical_files") or {}).items():
        findings.append({"type": "critical_path", "category": category, "files": paths[:5]})
    if changed_services:
        findings.append({"type": "service_touch", "services": changed_services[:8]})
    score = _clamp(100 - int(blast) * 0.6 - len(changed_services) * 4 - max(0, nodes - 12))
    if blast >= 70 or len(changed_services) >= 4:
        verdict = "fail"
    elif blast >= 35 or path_intel.get("critical_categories"):
        verdict = "warn"
    else:
        verdict = "pass"
    summary = f"Architecture {verdict}: stack={stack}, {nodes} service(s), blast={blast}/100"
    return _layer(verdict, score, findings, summary)


def _build_l4_security(security: dict[str, Any]) -> dict[str, Any]:
    vulns = security.get("vulnerabilities") or []
    score, verdict = _severity_to_score(str(security.get("highest_severity") or "none"), fail=20, warn=50)
    findings = [
        {
            "type": v.get("type") or "vulnerability",
            "severity": v.get("severity"),
            "file": v.get("file"),
            "line": v.get("line"),
            "description": (v.get("recommendation") or v.get("message") or "")[:200],
        }
        for v in vulns[:10]
        if isinstance(v, dict)
    ]
    summary = f"Security advisory {verdict}: highest={security.get('highest_severity', 'none')}, {len(vulns)} finding(s)"
    return _layer(verdict, score, findings, summary)


def _build_l5_performance(
    stress: dict[str, Any],
    performance_intelligence: dict[str, Any],
) -> dict[str, Any]:
    perf_verdict = str(stress.get("performance_verdict") or "").lower()
    if perf_verdict == "fail":
        score, verdict = 25, "fail"
    elif perf_verdict == "warn":
        score, verdict = 55, "warn"
    elif perf_verdict == "pass":
        score, verdict = 90, "pass"
    else:
        score, verdict = 80, "pass"

    baseline = performance_intelligence.get("baseline_comparison") or {}
    if performance_intelligence.get("gate_verdict") == "fail":
        score, verdict = min(score, 30), "fail"
    elif performance_intelligence.get("gate_verdict") == "warn" and verdict == "pass":
        score, verdict = 60, "warn"

    findings: list[dict[str, Any]] = []
    if stress.get("p95_ms") is not None:
        findings.append(
            {
                "type": "latency",
                "p95_ms": stress.get("p95_ms"),
                "error_rate_pct": stress.get("error_rate_pct"),
            }
        )
    if baseline.get("violations"):
        findings.append({"type": "baseline_regression", "violations": baseline.get("violations")[:5]})

    if not findings and stress.get("skipped"):
        summary = "Performance layer skipped (no stress run)"
        return _layer("pass", 85, [], summary)

    summary = f"Performance {verdict}: p95={stress.get('p95_ms', 'n/a')}ms"
    return _layer(verdict, score, findings, summary)


def _build_l6_maintainability(code: dict[str, Any], qa: dict[str, Any], changed_files: list[str]) -> dict[str, Any]:
    warnings = int(code.get("warnings_count") or 0)
    doc_issues = [
        i
        for i in (code.get("issues") or [])
        if isinstance(i, dict) and "docstring" in str(i.get("type") or "").lower()
    ]
    test_skipped = bool(qa.get("skipped"))
    file_count = len(changed_files or [])
    score = _clamp(100 - warnings * 3 - len(doc_issues) * 5 - max(0, file_count - 15) * 2)
    if warnings >= 8 or len(doc_issues) >= 5:
        verdict = "fail"
    elif warnings >= 3 or file_count >= 20:
        verdict = "warn"
    else:
        verdict = "pass"
    findings = doc_issues[:8]
    if test_skipped:
        findings.append({"type": "qa_simulated", "description": "QA checks were simulated or skipped"})
    summary = f"Maintainability {verdict}: {warnings} lint warning(s), {file_count} changed file(s)"
    return _layer(verdict, score, findings, summary)


def _build_l7_production_risk(change_risk: dict[str, Any]) -> dict[str, Any]:
    final_risk = int(change_risk.get("final_risk") or change_risk.get("orion_change_risk_score") or 0)
    score = _clamp(100 - final_risk)
    level = str(change_risk.get("risk_level") or "").lower()
    if final_risk >= 70 or level in {"high", "critical"}:
        verdict = "fail"
    elif final_risk >= 40 or level == "medium":
        verdict = "warn"
    else:
        verdict = "pass"
    findings: list[dict[str, Any]] = []
    for dim, value in (change_risk.get("dimensions") or {}).items():
        if isinstance(value, (int, float)) and value >= 50:
            findings.append({"type": "risk_dimension", "dimension": dim, "score": value})
    recs = change_risk.get("recommendations") or []
    if recs:
        findings.append({"type": "recommendations", "items": recs[:6]})
    summary = f"Production risk {verdict}: ORION score {final_risk}/100 ({level or 'n/a'})"
    return _layer(verdict, score, findings, summary)


def predict_bug_probability(
    *,
    layers: dict[str, dict[str, Any]],
    change_risk: dict[str, Any],
    code: dict[str, Any],
    security: dict[str, Any],
    qa: dict[str, Any],
) -> dict[str, Any]:
    """Heuristic bug-likelihood estimate for the change set (0–1 probability)."""
    factors: list[dict[str, Any]] = []
    probability = 0.12

    final_risk = int(change_risk.get("final_risk") or 0)
    if final_risk:
        delta = min(0.45, final_risk / 220.0)
        probability += delta
        factors.append({"signal": "change_risk", "weight": round(delta, 3), "value": final_risk})

    for layer_id in ("L0_syntax", "L1_static", "L2_semantic"):
        layer = layers.get(layer_id) or {}
        if layer.get("verdict") == "fail":
            probability += 0.12
            factors.append({"signal": layer_id, "weight": 0.12, "verdict": "fail"})
        elif layer.get("verdict") == "warn":
            probability += 0.05
            factors.append({"signal": layer_id, "weight": 0.05, "verdict": "warn"})

    if str(code.get("severity") or "").lower() == "fail":
        probability += 0.1
        factors.append({"signal": "code_severity", "weight": 0.1, "value": "fail"})

    if str(security.get("highest_severity") or "").lower() in {"critical", "high"}:
        probability += 0.08
        factors.append({"signal": "security", "weight": 0.08, "value": security.get("highest_severity")})

    if str(qa.get("verdict") or "").lower() == "fail":
        probability += 0.15
        factors.append({"signal": "qa_fail", "weight": 0.15})

    probability = round(min(0.98, max(0.02, probability)), 3)
    confidence = 0.75
    if str(code.get("analysis_mode") or "") == "llm":
        confidence = 0.88
    if not change_risk:
        confidence -= 0.1

    return {
        "probability": probability,
        "probability_percent": int(probability * 100),
        "confidence": confidence,
        "risk_band": "high" if probability >= 0.65 else "medium" if probability >= 0.35 else "low",
        "factors": factors,
    }


def evaluate_code_review_gates(report: dict[str, Any]) -> dict[str, Any]:
    layers = report.get("layers") or {}
    violations: list[str] = []
    warnings: list[str] = []

    for layer_id, layer in layers.items():
        verdict = str(layer.get("verdict") or "").lower()
        if verdict == "fail":
            violations.append(f"{layer_id} failed")
        elif verdict == "warn":
            warnings.append(f"{layer_id} warnings")

    bug = report.get("bug_prediction") or {}
    if bug.get("risk_band") == "high":
        violations.append("bug prediction band high")
    elif bug.get("risk_band") == "medium":
        warnings.append("elevated bug prediction")

    overall = int(report.get("overall_score") or 0)
    if overall < 50:
        violations.append(f"overall score {overall} below threshold")
    elif overall < 70:
        warnings.append(f"overall score {overall} marginal")

    if violations:
        gate = "fail"
    elif warnings:
        gate = "warn"
    else:
        gate = "pass"

    return {
        "gate_verdict": gate,
        "violations": violations,
        "warnings": warnings,
        "recommended_action": (
            "Block merge and remediate failing review layers"
            if gate == "fail"
            else "Proceed with human review on flagged layers"
            if gate == "warn"
            else "Approve from code-review intelligence perspective"
        ),
    }


def build_code_review_intelligence_report(
    *,
    code_analysis: dict[str, Any] | None = None,
    security_scan: dict[str, Any] | None = None,
    qa_report: dict[str, Any] | None = None,
    service_graph: dict[str, Any] | None = None,
    repository_intelligence: dict[str, Any] | None = None,
    change_risk_report: dict[str, Any] | None = None,
    stress_report: dict[str, Any] | None = None,
    performance_intelligence: dict[str, Any] | None = None,
    changed_files: list[str] | None = None,
) -> dict[str, Any]:
    code = code_analysis or {}
    security = security_scan or {}
    qa = qa_report or {}
    graph = service_graph or {}
    repo_intel = repository_intelligence or {}
    change_risk = change_risk_report or {}
    stress = stress_report or {}
    perf_intel = performance_intelligence or {}
    files = changed_files or []

    layers = {
        "L0_syntax": _build_l0_syntax(code),
        "L1_static": _build_l1_static(code),
        "L2_semantic": _build_l2_semantic(code),
        "L3_architecture": _build_l3_architecture(graph, repo_intel, files),
        "L4_security": _build_l4_security(security),
        "L5_performance": _build_l5_performance(stress, perf_intel),
        "L6_maintainability": _build_l6_maintainability(code, qa, files),
        "L7_production_risk": _build_l7_production_risk(change_risk),
    }

    overall = 0.0
    for layer_id, weight in _LAYER_WEIGHTS.items():
        overall += (layers[layer_id].get("score") or 0) * weight

    modes = {str(code.get("analysis_mode") or "heuristic")}
    if security.get("analysis_mode"):
        modes.add(str(security.get("analysis_mode")))
    analysis_mode = "hybrid" if "llm" in modes and "heuristic" in modes else ("llm" if "llm" in modes else "heuristic")

    fused = fuse_stage_results(code=code, security=security, qa=qa, stress=stress)

    report: dict[str, Any] = {
        "layers": layers,
        "overall_score": _clamp(overall),
        "gate_fusion": {
            "verdict": fused.get("verdict"),
            "risk_score": fused.get("risk_score"),
        },
        "analysis_mode": analysis_mode,
    }
    report["bug_prediction"] = predict_bug_probability(
        layers=layers,
        change_risk=change_risk,
        code=code,
        security=security,
        qa=qa,
    )
    gates = evaluate_code_review_gates(report)
    report["gates"] = gates
    report["gate_verdict"] = gates["gate_verdict"]
    report["recommended_actions"] = gates["violations"][:5] + gates["warnings"][:3]
    report["summary"] = (
        f"Code review {gates['gate_verdict']}: score {report['overall_score']}/100, "
        f"bug risk {report['bug_prediction']['probability_percent']}% "
        f"({report['bug_prediction']['risk_band']})"
    )
    return report
