"""Remediation intelligence — L0–L6 autonomy classification and unified fix report."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.utils.remediation_levels import REMEDIATION_LEVELS, level_rank, resolve_max_level
from app.utils.run_diagnostics import build_run_diagnostics


def classify_achieved_level(
    *,
    diagnostics: dict[str, Any] | None = None,
    fix_loop_report: dict[str, Any] | None = None,
    patch_confidence: dict[str, Any] | None = None,
    auto_pr_registry: dict[str, Any] | None = None,
    run_status: str | None = None,
) -> dict[str, Any]:
    diagnostics = diagnostics or {}
    fix_loop = fix_loop_report or {}
    confidence = patch_confidence or fix_loop.get("aggregate_confidence") or {}
    registry = auto_pr_registry or {}

    level = "L0"
    signals: list[str] = []

    if diagnostics.get("remediation_steps") or diagnostics.get("operator_actions"):
        level = "L1"
        signals.append("operator playbook available")

    bundles = fix_loop.get("bundles") or []
    has_patches = any(not b.get("skipped") for b in bundles)
    if has_patches:
        level = "L2"
        signals.append("AI patch bundles generated")

    if fix_loop and has_patches:
        sandbox_ok = all(
            (b.get("sandbox") or {}).get("passed", False)
            for b in bundles
            if not b.get("skipped")
        ) or bool((confidence or {}).get("checks", {}).get("unit_tests"))
        if sandbox_ok or confidence.get("patch_confidence"):
            level = "L3"
            signals.append("sandbox verification completed")

    action = str(confidence.get("action") or "")
    prs = registry.get("pull_requests") or registry.get("prs") or registry.get("branches") or []
    if action == "auto_pr" or prs:
        level = "L4"
        signals.append("auto-PR path eligible or PRs opened")

    if settings.remediation_l5_auto_retry_enabled and run_status in {"blocked_with_prs_sent", "approved"}:
        level = "L5"
        signals.append("L5 auto-retry enabled (policy-gated)")

    if settings.remediation_l6_auto_deploy_enabled and run_status == "deployed":
        level = "L6"
        signals.append("L6 autonomous deploy enabled")

    max_level = resolve_max_level(settings.remediation_autonomy_max_level)
    if level_rank(level) > level_rank(max_level):
        level = max_level
        signals.append(f"capped at configured max {max_level}")

    meta = REMEDIATION_LEVELS.get(level, {})
    return {
        "achieved_level": level,
        "achieved_label": meta.get("label", level),
        "max_allowed_level": max_level,
        "deferred_levels": [k for k, v in REMEDIATION_LEVELS.items() if v.get("deferred")],
        "signals": signals,
        "summary": f"Autonomy level {level} ({meta.get('label', level)}) achieved.",
    }


def build_l0_explain(diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "headline": diagnostics.get("headline"),
        "category": diagnostics.get("category"),
        "evidence": diagnostics.get("evidence") or [],
        "analysis_workflow": diagnostics.get("analysis_workflow") or [],
        "artifacts_to_review": diagnostics.get("artifacts_to_review") or [],
        "summary": diagnostics.get("headline") or "Review pipeline diagnostics and artifacts.",
    }


def build_l1_recommend(diagnostics: dict[str, Any], runbooks: dict[str, Any] | None = None) -> dict[str, Any]:
    runbooks = runbooks or {}
    steps = list(diagnostics.get("remediation_steps") or [])
    for book in (runbooks.get("runbooks") or [])[:3]:
        steps.append(f"Runbook {book.get('runbook_id')}: {book.get('title', book.get('name', 'see runbook'))}")
    return {
        "remediation_steps": steps,
        "operator_actions": diagnostics.get("operator_actions") or [],
        "config_keys": diagnostics.get("config_keys") or [],
        "runbooks": runbooks.get("runbooks") or [],
        "summary": f"{len(steps)} recommended action(s).",
    }


def build_l2_l3_patch(fix_loop_report: dict[str, Any] | None, patch_confidence: dict[str, Any] | None) -> dict[str, Any]:
    fix_loop = fix_loop_report or {}
    confidence = patch_confidence or fix_loop.get("aggregate_confidence") or {}
    bundles = []
    for bundle in fix_loop.get("bundles") or []:
        if bundle.get("skipped"):
            continue
        bundles.append(
            {
                "category": bundle.get("category"),
                "branch": bundle.get("branch"),
                "pr_number": bundle.get("pr_number"),
                "sandbox_passed": (bundle.get("sandbox") or {}).get("passed"),
                "patch_confidence": (bundle.get("patch_confidence") or {}).get("patch_confidence"),
                "action": (bundle.get("patch_confidence") or {}).get("action"),
            }
        )
    return {
        "bundles": bundles,
        "aggregate_confidence": confidence,
        "sandbox_summary": fix_loop.get("summary"),
        "summary": confidence.get("summary") or fix_loop.get("summary") or "No patch loop executed.",
    }


def build_l4_auto_pr(auto_pr_registry: dict[str, Any] | None) -> dict[str, Any]:
    registry = auto_pr_registry or {}
    prs = registry.get("pull_requests") or registry.get("prs") or registry.get("branches") or []
    return {
        "pull_requests": prs,
        "count": len(prs),
        "categories": sorted({p.get("category") for p in prs if p.get("category")}),
        "summary": f"{len(prs)} auto-PR(s) recorded." if prs else "No auto-PRs opened for this run.",
    }


def evaluate_deferred_autonomy(report: dict[str, Any]) -> dict[str, Any]:
    achieved = (report.get("autonomy") or {}).get("achieved_level", "L0")
    notes: list[str] = []
    if level_rank(achieved) >= 4 and not settings.remediation_l5_auto_retry_enabled:
        notes.append("L5 auto-retry disabled — merge fix PR and retry manually.")
    if level_rank(achieved) >= 4 and not settings.remediation_l6_auto_deploy_enabled:
        notes.append("L6 autonomous deploy disabled by policy.")
    if settings.remediation_l5_auto_retry_enabled:
        notes.append("L5 auto-retry may be triggered after fix PR merge (policy-gated).")
    return {
        "l5_enabled": settings.remediation_l5_auto_retry_enabled,
        "l6_enabled": settings.remediation_l6_auto_deploy_enabled,
        "notes": notes,
        "summary": "; ".join(notes) if notes else "L5/L6 remain manual unless enabled in config.",
    }


def evaluate_remediation_gates(report: dict[str, Any]) -> dict[str, Any]:
    violations: list[str] = []
    patch = report.get("patch") or {}
    confidence = patch.get("aggregate_confidence") or {}
    if confidence.get("action") == "reject":
        violations.append("patch confidence below auto-PR threshold")
    if patch.get("bundles") and not confidence.get("checks", {}).get("unit_tests", True):
        violations.append("sandbox unit test check failed")

    autonomy = report.get("autonomy") or {}
    if autonomy.get("achieved_level") == "L4" and not (report.get("auto_pr") or {}).get("count"):
        violations.append("L4 achieved in scoring but no PR URLs recorded")

    if violations and confidence.get("action") == "reject":
        gate = "fail"
    elif violations:
        gate = "warn"
    else:
        gate = "pass"
    return {"gate_verdict": gate, "violations": violations}


def build_remediation_intelligence_report(
    *,
    run: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    fix_loop_report: dict[str, Any] | None = None,
    runbooks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact_list = [{"artifact_type": k, "content": v, "summary": v.get("summary")} for k, v in artifacts.items()]
    diagnostics = build_run_diagnostics(run, artifact_list)

    patch_confidence = artifacts.get("patch_confidence_report") or (fix_loop_report or {}).get("aggregate_confidence")
    auto_pr = artifacts.get("auto_pr_registry")
    runbooks = runbooks or artifacts.get("runbook_execution") or {}

    autonomy = classify_achieved_level(
        diagnostics=diagnostics,
        fix_loop_report=fix_loop_report or artifacts.get("fix_loop_report"),
        patch_confidence=patch_confidence,
        auto_pr_registry=auto_pr,
        run_status=str(run.get("status") or ""),
    )

    report: dict[str, Any] = {
        "autonomy": autonomy,
        "explain": build_l0_explain(diagnostics),
        "recommend": build_l1_recommend(diagnostics, runbooks),
        "patch": build_l2_l3_patch(fix_loop_report or artifacts.get("fix_loop_report"), patch_confidence),
        "auto_pr": build_l4_auto_pr(auto_pr),
        "deferred": evaluate_deferred_autonomy({"autonomy": autonomy}),
        "diagnostics": {
            "status": diagnostics.get("status"),
            "category": diagnostics.get("category"),
            "failed_stage": diagnostics.get("failed_stage"),
        },
        "analysis_mode": "heuristic",
    }
    report["gates"] = evaluate_remediation_gates(report)
    report["gate_verdict"] = report["gates"]["gate_verdict"]
    report["summary"] = (
        f"Remediation {report['gate_verdict']}: level {autonomy['achieved_level']} — "
        f"{report['patch'].get('summary', diagnostics.get('headline', ''))[:120]}"
    )
    return report
