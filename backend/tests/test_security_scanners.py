from __future__ import annotations

import json
from unittest.mock import patch

from core.security_scanners import parse_pip_audit, run_bandit, run_pip_audit, run_security_scanners


def test_parse_pip_audit_extracts_cve() -> None:
    raw = json.dumps(
        {
            "dependencies": [
                {
                    "name": "requests",
                    "version": "2.25.0",
                    "vulns": [
                        {
                            "id": "PYSEC-2021-123",
                            "aliases": ["CVE-2021-12345"],
                            "fix_versions": ["2.26.0"],
                            "description": "HTTP smuggling",
                        }
                    ],
                }
            ]
        }
    )
    findings = parse_pip_audit(raw)
    assert findings is not None
    assert findings[0]["vulnerability_id"] == "CVE-2021-12345"


def test_run_security_scanners_merges_bandit_and_pip_audit(tmp_path) -> None:
    (tmp_path / "main.py").write_text("password = 'secret'\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests==2.25.0\n", encoding="utf-8")

    bandit_payload = {"results": []}
    pip_payload = {
        "dependencies": [
            {
                "name": "requests",
                "version": "2.25.0",
                "vulns": [
                    {
                        "id": "PYSEC-2021-123",
                        "aliases": ["CVE-2021-12345"],
                        "fix_versions": ["2.26.0"],
                        "description": "HTTP smuggling",
                    }
                ],
            }
        ]
    }

    with patch("shared.security_scanners.subprocess.run") as run_cmd:
        run_cmd.side_effect = [
            type("P", (), {"stdout": json.dumps(bandit_payload), "stderr": "", "returncode": 0})(),
            type("P", (), {"stdout": json.dumps(pip_payload), "stderr": "", "returncode": 0})(),
        ]
        report = run_security_scanners(str(tmp_path))

    assert report["analysis_mode"] == "scanner"
    assert report["blocked"] is True
    assert any(i.get("scanner") == "pip-audit" for i in report["issues"])
    assert report["scanners"]["bandit"]["status"] == "ok"
    assert report["scanners"]["dependencies"]["status"] == "ok"


def test_run_bandit_skips_when_tool_missing(tmp_path) -> None:
    issues, status = run_bandit(str(tmp_path))
    assert issues == []
    assert status["status"] == "failed"


def test_run_pip_audit_skips_without_requirements(tmp_path) -> None:
    issues, status = run_pip_audit(str(tmp_path))
    assert issues == []
    assert status["status"] == "skipped"
