"""Policy-as-code evaluation against pipeline artifacts (heuristic baseline)."""

from __future__ import annotations

from typing import Any


DEFAULT_POLICIES: list[dict[str, Any]] = [
    {
        "name": "production-security",
        "deny_if": {
            "critical_vulnerabilities": ">0",
            "secrets_detected": ">0",
            "unsigned_image": True,
            "policy_violations": ">0",
        },
        "require": {
            "tests": True,
            "sbom": True,
            "approval": True,
        },
    },
    {
        "name": "high-risk-gate",
        "deny_if": {
            "change_risk_high": True,
            "error_budget_exhausted": True,
        },
        "require": {},
    },
]


def _count_critical_vulns(security: dict[str, Any]) -> int:
    vulns = security.get("vulnerabilities") or []
    return sum(1 for v in vulns if str(v.get("severity", "")).lower() == "critical")


def evaluate_policies(
    artifacts: dict[str, dict[str, Any]],
    *,
    policies: list[dict[str, Any]] | None = None,
    unsigned_image: bool = False,
    strict_requirements: bool = False,
) -> dict[str, Any]:
    policies = policies or DEFAULT_POLICIES
    security = artifacts.get("security_scan") or {}
    secrets = artifacts.get("secrets_scan") or {}
    qa = artifacts.get("qa_report") or {}
    sbom = artifacts.get("sbom") or {}
    approval = artifacts.get("approval") or {}
    change_risk = artifacts.get("change_risk_report") or {}
    error_budget = artifacts.get("error_budget_report") or {}

    critical_vulns = _count_critical_vulns(security)
    secrets_critical = int(secrets.get("critical_count") or 0)
    tests_ok = qa.get("skipped") or str(qa.get("verdict", "")).lower() != "fail"
    has_sbom = bool(sbom.get("components"))
    approved = str(approval.get("decision", "")).lower() == "approved" if approval else True
    risk_high = str(change_risk.get("risk_level", "")).lower() == "high"
    budget_exhausted = bool(error_budget.get("freeze_risky_releases"))

    violations: list[dict[str, Any]] = []
    evaluated: list[str] = []

    for policy in policies:
        name = str(policy.get("name") or "unnamed")
        evaluated.append(name)
        deny = policy.get("deny_if") or {}
        require = policy.get("require") or {}

        if deny.get("critical_vulnerabilities") == ">0" and critical_vulns > 0:
            violations.append(
                {"policy": name, "rule": "critical_vulnerabilities", "detail": f"{critical_vulns} critical CVE(s)"}
            )
        if deny.get("secrets_detected") == ">0" and secrets_critical > 0:
            violations.append(
                {"policy": name, "rule": "secrets_detected", "detail": f"{secrets_critical} secret(s) in diff/repo"}
            )
        if deny.get("unsigned_image") and unsigned_image:
            violations.append({"policy": name, "rule": "unsigned_image", "detail": "Container image is not signed"})
        if deny.get("change_risk_high") and risk_high:
            violations.append(
                {
                    "policy": name,
                    "rule": "change_risk_high",
                    "detail": f"Change risk {change_risk.get('final_risk')}/100",
                }
            )
        if deny.get("error_budget_exhausted") and budget_exhausted:
            violations.append(
                {"policy": name, "rule": "error_budget_exhausted", "detail": error_budget.get("summary", "SLO budget low")}
            )

        if require.get("tests") and not tests_ok:
            violations.append({"policy": name, "rule": "require_tests", "detail": "QA verdict is not pass"})
        if strict_requirements:
            if require.get("sbom") and not has_sbom:
                violations.append({"policy": name, "rule": "require_sbom", "detail": "SBOM artifact missing"})
            if require.get("approval") and approval and not approved:
                violations.append({"policy": name, "rule": "require_approval", "detail": "Approval not granted"})

    passed = len(violations) == 0
    return {
        "passed": passed,
        "violations": violations,
        "policies_evaluated": evaluated,
        "violation_count": len(violations),
        "engine": "orion-heuristic",
        "summary": (
            f"Policy evaluation passed ({len(evaluated)} policy/policies)."
            if passed
            else f"Policy blocked: {len(violations)} violation(s) across {len(evaluated)} policy/policies."
        ),
    }
