"""DAST scan against staging — OWASP ZAP baseline when installed, probe heuristic otherwise."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx

from app.config import settings
from app.utils.external_scanners import run_zap_baseline

_RISK_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _risk_from_code(code: str | int | None) -> str:
    mapping = {"0": "info", "1": "low", "2": "medium", "3": "high", "4": "critical"}
    key = str(code or "1")
    return mapping.get(key, "low")


def _heuristic_dast(target_url: str) -> dict[str, Any]:
    """Lightweight staging probe when ZAP is unavailable."""
    findings: list[dict[str, Any]] = []
    base = target_url.rstrip("/")
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            for path in ("/health", "/"):
                url = urljoin(base + "/", path.lstrip("/"))
                try:
                    resp = client.get(url)
                except (httpx.HTTPError, OSError):
                    findings.append(
                        {
                            "name": "staging_unreachable",
                            "severity": "medium",
                            "url": url,
                            "description": "Staging endpoint unreachable during DAST probe",
                        }
                    )
                    continue
                headers = {k.lower(): v for k, v in resp.headers.items()}
                if resp.status_code >= 500:
                    findings.append(
                        {
                            "name": "server_error",
                            "severity": "high",
                            "url": url,
                            "description": f"HTTP {resp.status_code} on staging probe",
                        }
                    )
                for header, recommendation in (
                    ("x-frame-options", "Add X-Frame-Options to reduce clickjacking risk"),
                    ("content-security-policy", "Add Content-Security-Policy header"),
                    ("strict-transport-security", "Add HSTS when serving over HTTPS"),
                ):
                    if header not in headers and url.startswith("https://"):
                        findings.append(
                            {
                                "name": f"missing_{header}",
                                "severity": "low",
                                "url": url,
                                "description": recommendation,
                            }
                        )
    except OSError as exc:
        return {
            "target_url": target_url,
            "scanner": "heuristic",
            "status": "skipped",
            "analysis_mode": "heuristic",
            "verdict": "warn",
            "finding_count": 0,
            "findings": [],
            "summary": f"DAST skipped: {exc}",
            "skipped": True,
        }

    high = sum(1 for f in findings if f.get("severity") in {"high", "critical"})
    medium = sum(1 for f in findings if f.get("severity") == "medium")
    if high:
        verdict = "fail"
    elif medium or findings:
        verdict = "warn"
    else:
        verdict = "pass"

    return {
        "target_url": target_url,
        "scanner": "heuristic",
        "status": "completed",
        "analysis_mode": "heuristic",
        "verdict": verdict,
        "finding_count": len(findings),
        "findings": findings[:50],
        "counts": {"high": high, "medium": medium, "low": len(findings) - high - medium},
        "summary": f"Heuristic DAST {verdict}: {len(findings)} signal(s) on {target_url}",
        "skipped": False,
    }


def _normalize_zap(zap: dict[str, Any], target_url: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for site in zap.get("site") or []:
        if not isinstance(site, dict):
            continue
        for alert in site.get("alerts") or []:
            if not isinstance(alert, dict):
                continue
            severity = _risk_from_code(alert.get("riskcode"))
            findings.append(
                {
                    "name": alert.get("name") or alert.get("alert") or "zap-finding",
                    "severity": severity,
                    "url": alert.get("url") or site.get("@name") or target_url,
                    "description": (alert.get("desc") or alert.get("description") or "")[:500],
                    "plugin_id": alert.get("pluginid"),
                    "scanner": "zap",
                }
            )

    high = sum(1 for f in findings if f.get("severity") in {"high", "critical"})
    medium = sum(1 for f in findings if f.get("severity") == "medium")
    if high:
        verdict = "fail"
    elif medium:
        verdict = "warn"
    else:
        verdict = "pass"

    return {
        "target_url": target_url,
        "scanner": "zap",
        "status": zap.get("status") or "completed",
        "analysis_mode": "zap",
        "verdict": verdict,
        "finding_count": len(findings),
        "findings": findings[:100],
        "counts": {"high": high, "medium": medium, "low": len(findings) - high - medium},
        "summary": f"ZAP baseline {verdict}: {len(findings)} alert(s) on {target_url}",
        "skipped": False,
        "zap_meta": {
            "tool": zap.get("tool"),
            "reason": zap.get("reason"),
        },
    }


def build_dast_report(target_url: str | None = None) -> dict[str, Any]:
    """Run staging DAST; ZAP authoritative when installed."""
    url = (target_url or settings.staging_url or "").strip()
    if not url:
        return {
            "target_url": "",
            "scanner": "none",
            "status": "skipped",
            "analysis_mode": "heuristic",
            "verdict": "warn",
            "finding_count": 0,
            "findings": [],
            "summary": "DAST skipped: STAGING_URL not configured",
            "skipped": True,
        }

    zap = run_zap_baseline(url)
    if zap and zap.get("status") == "ok" and zap.get("report"):
        return _normalize_zap(zap["report"], url)
    if zap and zap.get("status") in {"failed", "skipped"}:
        heuristic = _heuristic_dast(url)
        heuristic["zap_fallback"] = {"status": zap.get("status"), "reason": zap.get("reason")}
        return heuristic
    return _heuristic_dast(url)


def evaluate_dast_gates(report: dict[str, Any]) -> dict[str, Any]:
    verdict = str(report.get("verdict") or "warn").lower()
    counts = report.get("counts") or {}
    high = int(counts.get("high") or 0)
    violations: list[str] = []
    if verdict == "fail" or high > 0:
        violations.append(f"DAST verdict {verdict} with {high} high-severity finding(s)")
    if violations and settings.dast_gate_enabled:
        gate = "fail"
    elif verdict in {"fail", "warn"} or violations:
        gate = "warn"
    else:
        gate = "pass"
    return {
        "gate_verdict": gate,
        "violations": violations,
        "dast_gate_enabled": settings.dast_gate_enabled,
    }
