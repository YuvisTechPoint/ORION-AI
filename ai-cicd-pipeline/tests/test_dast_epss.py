"""Tests for DAST scanning and EPSS enrichment."""

from __future__ import annotations

import json
from unittest.mock import patch

from app.utils.dast_scan import build_dast_report, evaluate_dast_gates
from app.utils.epss import enrich_cve_references, fetch_epss_scores
from app.utils.external_scanners import run_zap_baseline
from app.utils.supply_chain_report import build_supply_chain_report


def test_epss_heuristic_when_api_disabled(monkeypatch):
    monkeypatch.setattr("app.utils.epss.settings.epss_enabled", False)
    scores = fetch_epss_scores([{"cve": "CVE-2024-0001", "severity": "high"}])
    assert scores["CVE-2024-0001"]["source"] == "heuristic"
    assert scores["CVE-2024-0001"]["epss"] >= 0.5


def test_enrich_cve_references_attaches_epss(monkeypatch):
    monkeypatch.setattr("app.utils.epss.settings.epss_enabled", False)
    rows, meta = enrich_cve_references([{"cve": "CVE-2024-0001", "severity": "critical"}])
    assert rows[0]["epss"] is not None
    assert meta["epss_enabled"] is True


def test_zap_parses_baseline_json():
    payload = {
        "site": [
            {
                "@name": "http://localhost:8080",
                "alerts": [
                    {
                        "name": "X-Frame-Options",
                        "riskcode": "2",
                        "url": "http://localhost:8080/",
                        "desc": "Missing anti-clickjacking header",
                    }
                ],
            }
        ]
    }

    with patch(
        "app.utils.dast_scan.run_zap_baseline",
        return_value={"status": "ok", "report": payload, "tool": "zap"},
    ):
        report = build_dast_report("http://localhost:8080")

    assert report["scanner"] == "zap"
    assert report["finding_count"] >= 1


def test_heuristic_dast_unreachable(monkeypatch):
    monkeypatch.setattr("app.utils.external_scanners.run_zap_baseline", lambda *_a, **_k: None)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            raise OSError("connection refused")

    with patch("app.utils.dast_scan.httpx.Client", FakeClient):
        report = build_dast_report("http://127.0.0.1:59999")
    assert report["analysis_mode"] == "heuristic"
    assert report["finding_count"] >= 1


def test_dast_gate_disabled_by_default(monkeypatch):
    monkeypatch.setattr("app.utils.dast_scan.settings.dast_gate_enabled", False)
    gates = evaluate_dast_gates({"verdict": "fail", "counts": {"high": 2}})
    assert gates["gate_verdict"] == "warn"


def test_supply_chain_includes_epss(monkeypatch, tmp_path):
    monkeypatch.setattr("app.utils.epss.settings.epss_enabled", False)
    report = build_supply_chain_report(
        str(tmp_path),
        security_scan={"vulnerabilities": [{"cve": "CVE-2024-9999", "severity": "high"}]},
    )
    assert report["epss_enabled"] is True
    assert report["cve_references"][0].get("epss") is not None
