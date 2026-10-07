"""Tests for external DevSecOps scanner integration."""

from __future__ import annotations

import json
from unittest.mock import patch

from app.utils.container_security import scan_container_security
from app.utils.external_scanners import run_gitleaks, run_semgrep
from app.utils.iac_security import scan_iac_security
from app.utils.secrets_guardian import scan_secrets
from app.utils.supply_chain_report import build_supply_chain_report


def test_gitleaks_parses_json(tmp_path):
    (tmp_path / "config.py").write_text('KEY = "unused"\n', encoding="utf-8")
    payload = [
        {
            "RuleID": "github-pat",
            "Description": "GitHub token",
            "File": str(tmp_path / "config.py"),
            "StartLine": 1,
        }
    ]

    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = ""

        return Result()

    with patch("app.utils.external_scanners._tool_path", return_value="/usr/bin/gitleaks"), patch(
        "app.utils.external_scanners._run_cmd", side_effect=lambda *a, **k: (0, json.dumps(payload), "")
    ):
        report = run_gitleaks(str(tmp_path))

    assert report["analysis_mode"] == "gitleaks"
    assert report["finding_count"] == 1
    assert report["findings"][0]["scanner"] == "gitleaks"


def test_scan_secrets_falls_back_without_gitleaks(tmp_path):
    (tmp_path / "config.py").write_text('TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz123456"\n', encoding="utf-8")
    with patch("app.utils.external_scanners._tool_path", return_value=None):
        report = scan_secrets(str(tmp_path), changed_files=["config.py"])
    assert report["analysis_mode"] == "heuristic"
    assert report["critical_count"] >= 1
    assert report["external_scanner"]["status"] == "skipped"


def test_semgrep_parses_results(tmp_path):
    (tmp_path / "app.py").write_text("eval('1')\n", encoding="utf-8")
    payload = {
        "results": [
            {
                "check_id": "python.lang.security.audit.eval-detected",
                "path": str(tmp_path / "app.py"),
                "start": {"line": 1},
                "extra": {"severity": "ERROR", "message": "Use of eval detected"},
            }
        ]
    }
    with patch("app.utils.external_scanners._tool_path", return_value="/usr/bin/semgrep"), patch(
        "app.utils.external_scanners._run_cmd", return_value=(0, json.dumps(payload), "")
    ):
        findings, status = run_semgrep(str(tmp_path))
    assert status["status"] == "ok"
    assert findings[0]["severity"] == "high"


def test_container_scan_uses_trivy_when_available(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    payload = {
        "Results": [
            {
                "Target": str(tmp_path / "Dockerfile"),
                "Misconfigurations": [
                    {"ID": "DS002", "Severity": "HIGH", "Title": "Root user", "Description": "No USER"},
                ],
            }
        ]
    }
    with patch("app.utils.external_scanners._tool_path", return_value="/usr/bin/trivy"), patch(
        "app.utils.external_scanners._run_cmd", return_value=(0, json.dumps(payload), "")
    ):
        report = scan_container_security(str(tmp_path))
    assert report["analysis_mode"] == "trivy"
    assert report["high_count"] >= 1


def test_iac_scan_uses_checkov_when_available(tmp_path):
    (tmp_path / "main.tf").write_text('resource "aws_s3_bucket" "x" { acl = "public-read" }\n', encoding="utf-8")
    payload = [
        {
            "results": {
                "failed_checks": [
                    {
                        "check_id": "CKV_AWS_20",
                        "check_name": "S3 public ACL",
                        "file_path": str(tmp_path / "main.tf"),
                        "severity": "CRITICAL",
                    }
                ]
            }
        }
    ]
    with patch("app.utils.external_scanners._tool_path", return_value="/usr/bin/checkov"), patch(
        "app.utils.external_scanners._run_cmd", return_value=(0, json.dumps(payload), "")
    ):
        report = scan_iac_security(str(tmp_path))
    assert report["analysis_mode"] == "checkov"
    assert report["critical_count"] >= 1


def test_supply_chain_report_lockfiles_and_cves(tmp_path):
    (tmp_path / "poetry.lock").write_text("[[package]]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("flask>=3.0\n", encoding="utf-8")
    report = build_supply_chain_report(
        str(tmp_path),
        sbom={"stats": {"component_count": 3}},
        secrets_scan={"critical_count": 0, "scanner": "heuristic"},
        security_scan={
            "vulnerabilities": [{"cve": "CVE-2024-0001", "severity": "high", "type": "vulnerable_dependency", "file": "requirements.txt"}]
        },
    )
    assert report["posture"] == "warn"
    assert len(report["lockfiles"]) == 1
    assert report["cve_references"][0]["cve"] == "CVE-2024-0001"
    assert report["unpinned_requirements"]
