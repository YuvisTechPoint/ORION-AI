"""ORION Release Passport — aggregated evidence for a production-ready run."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_release_passport(
    *,
    run_id: str,
    repo: str,
    branch: str,
    commit: str,
    artifacts: dict[str, dict[str, Any]],
    deploy_mode: str,
    environment: str,
) -> dict[str, Any]:
    code = artifacts.get("code_analysis") or {}
    security = artifacts.get("security_scan") or {}
    qa = artifacts.get("qa_report") or {}
    stress = artifacts.get("stress_report") or {}
    approval = artifacts.get("approval") or {}
    change_risk = artifacts.get("change_risk_report") or {}
    sbom = artifacts.get("sbom") or {}
    secrets = artifacts.get("secrets_scan") or {}
    container = artifacts.get("container_security_scan") or {}
    iac = artifacts.get("iac_security_scan") or {}
    service_graph = artifacts.get("service_graph") or {}
    test_intel = artifacts.get("test_intelligence") or {}

    qa_summary = qa.get("test_summary") or {}
    tests_passed = int(qa_summary.get("passed", 0) or 0)
    tests_total = int(qa_summary.get("total", 0) or 0)

    sec_vulns = security.get("vulnerabilities") or []
    critical_sec = sum(1 for v in sec_vulns if str(v.get("severity", "")).lower() == "critical")

    checks = {
        "code_analysis": str(code.get("severity", "unknown")).lower() != "fail",
        "security_scan": security.get("passed", True) is not False and critical_sec == 0,
        "qa": str(qa.get("verdict", "")).lower() != "fail",
        "stress": str(stress.get("performance_verdict", "")).lower() != "fail",
        "approval": str(approval.get("decision", "")).lower() == "approved",
        "secrets": secrets.get("passed", True) is not False,
        "container": container.get("passed", True) is not False,
        "iac": iac.get("passed", True) is not False,
        "sbom_generated": bool(sbom.get("components")),
    }

    evidence_count = sum(1 for k in artifacts if k not in {"diff", "audit_trail"})
    passport_status = "PASS" if all(checks.values()) else "WARN"
    risk_score = change_risk.get("final_risk", "—")
    risk_level = change_risk.get("risk_level", "unknown")

    return {
        "release_id": f"REL-{run_id[:8]}",
        "run_id": run_id,
        "repository": repo,
        "branch": branch,
        "commit": commit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": environment,
        "deploy_mode": deploy_mode,
        "risk": {
            "final_score": change_risk.get("final_risk"),
            "level": change_risk.get("risk_level"),
            "ai_confidence": change_risk.get("ai_confidence"),
        },
        "tests": {
            "passed": tests_passed,
            "total": tests_total,
            "mode": test_intel.get("mode", "full_suite"),
            "flaky_count": (test_intel.get("flaky_analysis") or {}).get("flaky_count", 0),
        },
        "security": {
            "critical": critical_sec,
            "highest_severity": security.get("highest_severity", "none"),
            "secrets_critical": secrets.get("critical_count", 0),
            "container_critical": container.get("critical_count", 0),
            "iac_critical": iac.get("critical_count", 0),
        },
        "sbom": {
            "generated": bool(sbom.get("components")),
            "component_count": (
                (sbom.get("stats") or {}).get("component_count")
                or len(sbom.get("components") or [])
            ),
        },
        "service_graph": {
            "node_count": service_graph.get("node_count", 0),
            "changed_services": service_graph.get("changed_services", []),
        },
        "approval": {
            "decision": approval.get("decision"),
            "confidence": approval.get("confidence"),
        },
        "checks": checks,
        "all_checks_passed": all(checks.values()),
        "contract_testing": artifacts.get("contract_test_report") or {},
        "preview_environment": artifacts.get("preview_environment") or {},
        "progressive_delivery": artifacts.get("progressive_delivery") or {},
        "evidence_artifact_count": evidence_count,
        "rollback_available": bool(artifacts.get("last_known_good_image") or artifacts.get("deployment_info")),
        "summary": (
            f"Release passport {passport_status}: {evidence_count} evidence artifact(s), "
            f"risk {risk_score}/100 ({risk_level}), {tests_passed}/{tests_total} tests."
        ),
    }
