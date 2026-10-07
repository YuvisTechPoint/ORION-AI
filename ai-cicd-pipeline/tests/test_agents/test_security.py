import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.security_agent import SecurityAgent, split_requirements

BANDIT_OUTPUT = {
    "results": [
        {
            "filename": "REPO/app/api/users.py",
            "test_id": "B608",
            "test_name": "hardcoded_sql_expressions",
            "issue_severity": "MEDIUM",
            "issue_confidence": "LOW",
            "issue_text": "Possible SQL injection vector through string-based query construction.",
            "line_number": 31,
            "issue_cwe": {"id": 89},
        },
        {
            "filename": "REPO/app/utils.py",
            "test_id": "B602",
            "test_name": "subprocess_popen_with_shell_equals_true",
            "issue_severity": "HIGH",
            "issue_confidence": "HIGH",
            "issue_text": "subprocess call with shell=True identified.",
            "line_number": 12,
        },
    ]
}


def make_agent(run, db, client, repo: Path) -> SecurityAgent:
    return SecurityAgent(run.id, db, client, str(repo), "+query = f\"SELECT ... '{email}'\"")


def bandit_stdout(repo: Path) -> str:
    return json.dumps(BANDIT_OUTPUT).replace("REPO", repo.as_posix())


async def test_bandit_findings_are_normalized_and_relative(pipeline_run, db_session, tmp_path):
    agent = make_agent(pipeline_run, db_session, None, tmp_path)
    with patch("app.agents.security_agent.subprocess.run", return_value=MagicMock(stdout=bandit_stdout(tmp_path))):
        findings, _, error = agent._run_bandit()
    assert error is None
    assert [f["filename"] for f in findings] == ["app/api/users.py", "app/utils.py"]
    assert findings[0]["cwe"] == 89
    assert findings[1]["issue_severity"] == "HIGH"


def test_split_requirements():
    pinned, unpinned = split_requirements(
        "# comment\nrequests==2.19.0\nuvicorn[standard]==0.30.6 ; python_version>'3.8'\n"
        "flask>=2\n-r other.txt\ndjango\nnumpy==1.26.4  # inline\n"
    )
    assert pinned == ["requests==2.19.0", "uvicorn[standard]==0.30.6 ; python_version>'3.8'", "numpy==1.26.4"]
    assert unpinned == ["flask>=2", "-r other.txt", "django"]


def test_parse_pip_audit_dedupes_and_prefers_cve():
    raw = json.dumps(
        {
            "dependencies": [
                {
                    "name": "requests",
                    "version": "2.19.0",
                    "vulns": [
                        {"id": "PYSEC-2018-28", "fix_versions": ["2.20.0"], "aliases": ["GHSA-x", "CVE-2018-18074"], "description": "leak"},
                        {"id": "PYSEC-2018-28", "fix_versions": ["2.20.0"], "aliases": [], "description": "dup"},
                    ],
                },
                {"name": "idna", "version": "3.7", "vulns": []},
            ]
        }
    )
    findings = SecurityAgent.parse_pip_audit(raw)
    assert findings == [
        {"package": "requests", "installed_version": "2.19.0", "vulnerability_id": "CVE-2018-18074",
         "fix_versions": ["2.20.0"], "description": "leak"}
    ]
    assert SecurityAgent.parse_pip_audit("Traceback: boom") is None


async def test_dependency_audit_reports_vulnerable_pins(pipeline_run, db_session, tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.19.0\nflask\n")
    agent = make_agent(pipeline_run, db_session, None, tmp_path)
    audit = json.dumps({"dependencies": [{"name": "requests", "version": "2.19.0", "vulns": [
        {"id": "PYSEC-2018-28", "fix_versions": ["2.20.0"], "aliases": ["CVE-2018-18074"], "description": "leak"}]}]})
    with patch("app.agents.security_agent.subprocess.run", return_value=MagicMock(stdout=audit, stderr="", returncode=1)) as run:
        findings, _, status = agent._run_dependency_audit(tmp_path / "requirements.txt")
    assert status["status"] == "ok" and status["audited"] == 1 and status["not_audited"] == ["flask"]
    assert findings[0]["vulnerability_id"] == "CVE-2018-18074"
    assert "--disable-pip" in run.call_args.args[0]


async def test_heuristic_mode_reports_highest_severity(pipeline_run, db_session, tmp_path):
    agent = make_agent(pipeline_run, db_session, None, tmp_path)
    with patch("app.agents.security_agent.subprocess.run", return_value=MagicMock(stdout=bandit_stdout(tmp_path))):
        result = await agent.execute()
    assert result["analysis_mode"] == "heuristic"
    assert result["highest_severity"] == "high"
    assert result["total_count"] == 2
    assert result["security_score"] == 100 - 15 - 5


async def test_llm_cannot_downgrade_scanner_severity(pipeline_run, db_session, mock_anthropic_client, tmp_path):
    agent = make_agent(pipeline_run, db_session, mock_anthropic_client, tmp_path)
    llm = {"vulnerabilities": [], "highest_severity": "low", "security_score": 99, "summary": "fine", "immediate_actions": []}
    with (
        patch("app.agents.security_agent.subprocess.run", return_value=MagicMock(stdout=bandit_stdout(tmp_path))),
        patch.object(agent, "_call_claude_json", AsyncMock(return_value=llm)),
    ):
        result = await agent.execute()
    assert result["analysis_mode"] == "llm"
    assert result["highest_severity"] == "high"


async def test_scanner_crash_is_not_fatal(pipeline_run, db_session, tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.20.0\n")
    agent = make_agent(pipeline_run, db_session, None, tmp_path)
    with patch("app.agents.security_agent.subprocess.run", side_effect=FileNotFoundError("bandit")):
        result = await agent.execute()
    assert result["total_count"] == 0
    assert result["scanners"]["bandit"]["status"] == "failed"
    assert result["scanners"]["dependencies"]["status"] == "failed"
    assert "Scanner(s) failed: bandit, dependencies" in result["summary"]
