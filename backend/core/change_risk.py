"""Heuristic change risk intelligence — shared with ORION stacks."""

from __future__ import annotations

import re
from typing import Any

from core.gate_fusion import fuse_stage_results
from core.text_analysis import diff_stats, files_in_diff

_CRITICAL_PATH_RULES: list[tuple[re.Pattern[str], str, int]] = [
    (re.compile(r"(^|/)(auth|authentication|oauth|jwt|session)(/|$|_|\.)", re.I), "authentication", 18),
    (re.compile(r"(^|/)(payment|payments|billing|checkout|stripe|paypal)(/|$|_|\.)", re.I), "payments", 20),
    (re.compile(r"(^|/)(migrations?|alembic|schema)(/|$|_|\.)", re.I), "database_schema", 22),
    (re.compile(r"(^|/)(dockerfile|docker-compose|k8s|kubernetes|helm|terraform|\.tf)(/|$|_|\.)", re.I), "infrastructure", 16),
    (re.compile(r"(^|/)(middleware|gateway|api/v|routes?)(/|$|_|\.)", re.I), "api_surface", 14),
    (re.compile(r"(requirements|package\.json|poetry\.lock|pnpm-lock|go\.mod)", re.I), "dependencies", 12),
    (re.compile(r"(^|/)(config|settings|secrets?)(/|$|_|\.)", re.I), "configuration", 15),
    (re.compile(r"(^|/)(\.env|credentials|secrets?\.(ya?ml|json))", re.I), "secrets_config", 25),
]

_LOW_RISK_DOC = re.compile(r"^(readme|changelog|license|contributing|\.md$|docs/)", re.I)


def _clamp(value: int | float, lo: int = 0, hi: int = 100) -> int:
    return int(max(lo, min(hi, round(value))))


def _severity_score(raw: str, *, fail: int, warn: int, medium: int = 0) -> int:
    level = str(raw or "").lower()
    if level in {"fail", "critical"}:
        return fail
    if level in {"high"}:
        return fail - 5
    if level in {"warn", "medium"}:
        return warn if level == "warn" else medium
    if level in {"low"}:
        return 8
    return 0


def analyze_changed_paths(changed_files: list[str]) -> dict[str, Any]:
    categories: dict[str, list[str]] = {}
    low_risk_only = True
    for path in changed_files:
        normalized = (path or "").replace("\\", "/").strip()
        if not normalized:
            continue
        if not _LOW_RISK_DOC.search(normalized):
            low_risk_only = False
        for pattern, category, _weight in _CRITICAL_PATH_RULES:
            if pattern.search(normalized):
                categories.setdefault(category, []).append(normalized)

    blast_score = 2 if (low_risk_only and changed_files) else min(35, 5 + len(changed_files) * 2)
    if not (low_risk_only and changed_files):
        for category, paths in categories.items():
            weight = next(w for p, c, w in _CRITICAL_PATH_RULES if c == category)
            blast_score += min(weight, 8 + len(paths) * 3)
    blast_score = _clamp(blast_score)

    level = "high" if blast_score >= 70 else "medium" if blast_score >= 35 else "low"
    recommendations: list[str] = []
    if "payments" in categories or "authentication" in categories:
        recommendations.append("extended integration tests recommended")
    if "database_schema" in categories:
        recommendations.append("staging deployment and migration review required")
    if blast_score >= 50:
        recommendations.append("canary or staged rollout recommended")
    if blast_score >= 65:
        recommendations.append("manual approval recommended")

    return {
        "blast_radius_score": blast_score,
        "blast_radius_level": level,
        "critical_categories": sorted(categories.keys()),
        "critical_files": {k: v[:10] for k, v in categories.items()},
        "low_risk_docs_only": low_risk_only and bool(changed_files),
        "recommendations": recommendations,
    }


def compute_change_risk(
    *,
    diff_text: str = "",
    changed_files: list[str] | None = None,
    code: dict[str, Any] | None = None,
    security: dict[str, Any] | None = None,
    qa: dict[str, Any] | None = None,
    stress: dict[str, Any] | None = None,
    gate_fusion: dict[str, Any] | None = None,
    analysis_mode: str = "heuristic",
) -> dict[str, Any]:
    code = code or {}
    security = security or {}
    qa = qa or {}
    stress = stress or {}

    files = list(changed_files or [])
    if not files and diff_text:
        files = files_in_diff(diff_text)
    stats = diff_stats(diff_text) if diff_text else {"files_changed": len(files), "lines_added": 0, "lines_removed": 0}
    path_analysis = analyze_changed_paths(files)

    code_risk = _severity_score(str(code.get("severity", code.get("overall_severity", ""))), fail=85, warn=35)
    if code.get("critical_issues_count", 0):
        code_risk = _clamp(code_risk + int(code["critical_issues_count"]) * 5)

    security_risk = _severity_score(
        str(security.get("highest_severity", security.get("overall_risk", ""))),
        fail=90,
        warn=40,
        medium=25,
    )
    if security.get("passed") is False or security.get("blocked"):
        security_risk = _clamp(max(security_risk, 75))

    dependency_risk = 0
    if any(r[0].search(f) for f in files for r in _CRITICAL_PATH_RULES if r[1] == "dependencies"):
        dependency_risk = 15

    test_risk = 45 if qa.get("skipped") else 80 if qa.get("passed") is False else 30 if str(qa.get("verdict", "")).lower() == "warn" else 0

    blast_radius = _clamp(path_analysis["blast_radius_score"] + min(25, (int(stats.get("lines_added", 0)) + int(stats.get("lines_removed", 0))) // 50))
    production_risk = _clamp(max(blast_radius, security_risk // 2, code_risk // 2) + (10 if path_analysis["critical_categories"] else 0))
    historical_risk = 0

    fused = gate_fusion or fuse_stage_results(code=code, security=security, qa=qa, stress=stress)
    gate_risk = int(fused.get("risk_score", 0))

    final_risk = _clamp(
        0.15 * code_risk
        + 0.20 * security_risk
        + 0.10 * dependency_risk
        + 0.15 * test_risk
        + 0.20 * blast_radius
        + 0.15 * production_risk
        + 0.05 * historical_risk
    )
    final_risk = max(final_risk, gate_risk // 2)

    ai_confidence = 0.91 if analysis_mode == "llm" else 0.78 if analysis_mode == "simulated" else 0.72
    risk_level = "high" if final_risk >= 60 else "medium" if final_risk >= 35 else "low"

    recommendations = list(path_analysis["recommendations"])
    if fused.get("verdict") == "fail":
        recommendations.insert(0, "gate fusion failed — block deployment")

    return {
        "analysis_mode": analysis_mode,
        "dimensions": {
            "code_risk": code_risk,
            "security_risk": security_risk,
            "dependency_risk": dependency_risk,
            "test_risk": test_risk,
            "blast_radius": blast_radius,
            "production_risk": production_risk,
            "historical_risk": historical_risk,
            "gate_risk": gate_risk,
        },
        "final_risk": final_risk,
        "risk_level": risk_level,
        "ai_confidence": round(ai_confidence, 2),
        "change_summary": {
            "files_changed": stats.get("files_changed", len(files)),
            "lines_added": stats.get("lines_added", 0),
            "lines_removed": stats.get("lines_removed", 0),
            "sample_files": (stats.get("files") or files)[:12],
        },
        "blast_radius_analysis": path_analysis,
        "gate_fusion_verdict": fused.get("verdict"),
        "gate_fusion_violations": fused.get("violations", [])[:6],
        "recommendations": list(dict.fromkeys(recommendations))[:8],
    }
