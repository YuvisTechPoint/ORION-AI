"""EPSS enrichment for CVE references — FIRST.org API with severity heuristic fallback."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings

_SEVERITY_EPSS = {
    "critical": 0.82,
    "high": 0.55,
    "medium": 0.28,
    "low": 0.10,
    "none": 0.04,
}


def _heuristic_epss(cve: str, severity: str | None = None) -> dict[str, Any]:
    level = str(severity or "medium").lower()
    score = _SEVERITY_EPSS.get(level, 0.2)
    return {
        "cve": cve,
        "epss": score,
        "percentile": min(99.0, score * 100),
        "source": "heuristic",
    }


def fetch_epss_scores(
    cve_entries: list[dict[str, Any]],
    *,
    enabled: bool | None = None,
) -> dict[str, dict[str, Any]]:
    """Return map of CVE id -> EPSS record for the given CVE reference rows."""
    use_api = settings.epss_enabled if enabled is None else enabled
    cves = []
    severity_by_cve: dict[str, str] = {}
    for row in cve_entries:
        if not isinstance(row, dict):
            continue
        cve = str(row.get("cve") or "").strip().upper()
        if not cve.startswith("CVE-"):
            continue
        cves.append(cve)
        if row.get("severity"):
            severity_by_cve[cve] = str(row.get("severity"))

    if not cves:
        return {}

    if not use_api:
        return {cve: _heuristic_epss(cve, severity_by_cve.get(cve)) for cve in cves}

    out: dict[str, dict[str, Any]] = {}
    try:
        batch = cves[:50]
        resp = httpx.get(
            "https://api.first.org/data/v1/epss",
            params={"cve": ",".join(batch)},
            timeout=15.0,
        )
        resp.raise_for_status()
        payload = resp.json()
        for row in payload.get("data") or []:
            if not isinstance(row, dict):
                continue
            cve = str(row.get("cve") or "").upper()
            if not cve:
                continue
            try:
                epss = float(row.get("epss") or 0)
            except (TypeError, ValueError):
                epss = 0.0
            try:
                percentile = float(row.get("percentile") or 0) * 100
            except (TypeError, ValueError):
                percentile = epss * 100
            out[cve] = {
                "cve": cve,
                "epss": round(epss, 5),
                "percentile": round(percentile, 2),
                "source": "first.org",
            }
    except (httpx.HTTPError, OSError, ValueError):
        for cve in cves:
            out[cve] = _heuristic_epss(cve, severity_by_cve.get(cve))
        return out

    for cve in cves:
        if cve not in out:
            out[cve] = _heuristic_epss(cve, severity_by_cve.get(cve))
    return out


def enrich_cve_references(
    cve_entries: list[dict[str, Any]],
    *,
    enabled: bool | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach epss + epss_percentile to each CVE row; return summary metadata."""
    scores = fetch_epss_scores(cve_entries, enabled=enabled)
    enriched: list[dict[str, Any]] = []
    high_exploit = 0
    for row in cve_entries:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        cve = str(item.get("cve") or "").upper()
        epss_row = scores.get(cve) or {}
        if epss_row:
            item["epss"] = epss_row.get("epss")
            item["epss_percentile"] = epss_row.get("percentile")
            item["epss_source"] = epss_row.get("source")
            if float(epss_row.get("epss") or 0) >= 0.5:
                high_exploit += 1
        enriched.append(item)

    sources = {v.get("source") for v in scores.values() if v.get("source")}
    meta = {
        "epss_enabled": bool(scores),
        "epss_source": "first.org" if "first.org" in sources else "heuristic",
        "cve_count": len(enriched),
        "high_exploit_probability_count": high_exploit,
    }
    return enriched, meta
