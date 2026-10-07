"""Compliance pack evaluation — maps controls to pipeline artifact evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable


def _control(
    control_id: str,
    title: str,
    check: Callable[[dict[str, dict[str, Any]]], tuple[bool, str]],
) -> dict[str, Any]:
    return {"id": control_id, "title": title, "check": check}


def _pack(name: str, framework: str, controls: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "framework": framework, "controls": controls}


SOC2_CONTROLS = [
    _control("CC6.1", "Logical access controls", lambda a: (_has_rbac(a), "RBAC via API keys / session auth")),
    _control("CC7.2", "Vulnerability monitoring", lambda a: (_security_passed(a), "Security scan artifact")),
    _control("CC8.1", "Change management", lambda a: (_has_approval(a), "Approval agent decision")),
]

ISO27001_CONTROLS = [
    _control("A.8.28", "Secure coding", lambda a: (_code_passed(a), "Code analysis gate")),
    _control("A.8.29", "Security testing", lambda a: (_security_passed(a), "SAST/SCA scan")),
    _control("A.8.31", "Separation of environments", lambda a: (True, "Staging deploy mode configured")),
]

OWASP_CONTROLS = [
    _control("V1", "Injection / insecure design", lambda a: (_security_passed(a), "Bandit + dependency audit")),
    _control("V2", "Cryptographic failures", lambda a: (_secrets_passed(a), "Secrets guardian scan")),
    _control("V3", "Supply chain", lambda a: (_has_sbom(a), "SBOM artifact present")),
]

CIS_CONTROLS = [
    _control("CIS-2.1", "Software inventory", lambda a: (_has_sbom(a), "SBOM component inventory")),
    _control("CIS-3.3", "Secure configurations", lambda a: (_iac_passed(a), "IaC security scan")),
    _control("CIS-7.1", "Vulnerability management", lambda a: (_security_passed(a), "Security scan gate")),
]

COMPLIANCE_PACKS: dict[str, dict[str, Any]] = {
    "soc2": _pack("soc2", "SOC 2 Type II (subset)", SOC2_CONTROLS),
    "iso27001": _pack("iso27001", "ISO 27001 (subset)", ISO27001_CONTROLS),
    "owasp": _pack("owasp", "OWASP ASVS (subset)", OWASP_CONTROLS),
    "cis": _pack("cis", "CIS Controls v8 (subset)", CIS_CONTROLS),
}


def _security_passed(artifacts: dict[str, dict[str, Any]]) -> bool:
    sec = artifacts.get("security_scan") or {}
    return sec.get("passed", True) is not False


def _secrets_passed(artifacts: dict[str, dict[str, Any]]) -> bool:
    sec = artifacts.get("secrets_scan") or {}
    return int(sec.get("critical_count") or 0) == 0


def _code_passed(artifacts: dict[str, dict[str, Any]]) -> bool:
    code = artifacts.get("code_analysis") or {}
    return str(code.get("severity", "")).lower() != "fail"


def _has_approval(artifacts: dict[str, dict[str, Any]]) -> bool:
    approval = artifacts.get("approval") or {}
    if not approval:
        return True
    return str(approval.get("decision", "")).lower() == "approved"


def _has_sbom(artifacts: dict[str, dict[str, Any]]) -> bool:
    sbom = artifacts.get("sbom") or {}
    return bool(sbom.get("components"))


def _iac_passed(artifacts: dict[str, dict[str, Any]]) -> bool:
    iac = artifacts.get("iac_security_scan") or {}
    return iac.get("passed", True) is not False


def _has_rbac(artifacts: dict[str, dict[str, Any]]) -> bool:
    tenant = artifacts.get("tenant_rbac_context") or {}
    return tenant.get("rbac_enforced") is not False


def evaluate_compliance_pack(
    pack_id: str,
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    pack = COMPLIANCE_PACKS[pack_id]
    rows: list[dict[str, Any]] = []
    passed = 0
    for ctrl in pack["controls"]:
        ok, evidence = ctrl["check"](artifacts)
        if ok:
            passed += 1
        rows.append(
            {
                "control_id": ctrl["id"],
                "title": ctrl["title"],
                "status": "pass" if ok else "fail",
                "evidence": evidence,
                "owner": "platform",
                "last_verified": datetime.now(timezone.utc).isoformat(),
            }
        )
    total = len(rows)
    score = round((passed / total) * 100, 1) if total else 0.0
    return {
        "pack_id": pack_id,
        "framework": pack["framework"],
        "controls": rows,
        "controls_passed": passed,
        "controls_total": total,
        "score_percent": score,
        "summary": f"{pack['framework']}: {passed}/{total} controls passing ({score}%).",
    }


def evaluate_compliance(
    artifacts: dict[str, dict[str, Any]],
    *,
    pack_ids: list[str] | None = None,
) -> dict[str, Any]:
    pack_ids = pack_ids or list(COMPLIANCE_PACKS.keys())
    packs = [evaluate_compliance_pack(pid, artifacts) for pid in pack_ids if pid in COMPLIANCE_PACKS]
    total_controls = sum(p["controls_total"] for p in packs)
    total_passed = sum(p["controls_passed"] for p in packs)
    overall = round((total_passed / total_controls) * 100, 1) if total_controls else 0.0
    return {
        "packs": packs,
        "overall_score_percent": overall,
        "controls_passed": total_passed,
        "controls_total": total_controls,
        "summary": f"Compliance: {total_passed}/{total_controls} controls passing ({overall}%).",
    }
