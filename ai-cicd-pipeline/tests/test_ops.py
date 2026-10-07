"""Tests for the systemd-side tooling: journald normalization, the orion CLI and the monitor daemon."""

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.daemon import monitor_daemon
from app.daemon.monitor_daemon import OrionMonitorDaemon
from app.services.journald_service import normalize_entry, priority_to_level

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cli():
    spec = importlib.util.spec_from_file_location("orion_cli", ROOT / "scripts" / "orion_cli.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("priority", "level"), [(0, "CRITICAL"), (2, "CRITICAL"), (3, "ERROR"), (4, "WARNING"), (6, "INFO"), (7, "DEBUG"), (None, "INFO")])
def test_priority_to_level(priority, level):
    assert priority_to_level(priority) == level


def test_normalize_entry():
    entry = normalize_entry(
        {"PRIORITY": "3", "__REALTIME_TIMESTAMP": "1767225600000000", "MESSAGE": [104, 105], "SYSLOG_IDENTIFIER": "uvicorn"},
        "orion-api",
    )
    assert entry == {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "level": "ERROR",
        "service": "orion-api",
        "message": "hi",
        "identifier": "uvicorn",
    }
    assert normalize_entry({"PRIORITY": "junk"}, "x")["level"] == "INFO"


@pytest.mark.parametrize("argv", [["--json", "status"], ["status", "--json"]])
def test_cli_json_flag_in_either_position(cli, argv):
    assert cli.build_parser().parse_args(argv).json is True


def test_cli_json_defaults_off(cli):
    assert cli.build_parser().parse_args(["status"]).json is False


def test_cli_resolve_services(cli):
    assert cli.resolve_services("api") == ["orion-api"]
    assert cli.resolve_services("orion-worker.service") == ["orion-worker"]
    assert len(cli.resolve_services("all")) == 4
    with pytest.raises(SystemExit):
        cli.resolve_services("db")


def test_cli_pg_env_from_url(cli):
    args, env = cli.pg_env_from_url("postgresql+asyncpg://orion:p%40ss@db.internal:6543/aicicd")
    assert args == ["-h", "db.internal", "-p", "6543", "-U", "orion", "-d", "aicicd"]
    assert env["PGPASSWORD"] == "p@ss"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_cli_build_deploy_payload(cli, tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "a.txt").write_text("1")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "first")
    (tmp_path / "a.txt").write_text("2")
    _git(tmp_path, "commit", "-q", "-am", "second commit")
    _git(tmp_path, "remote", "add", "origin", "git@github.com:acme/widgets.git")

    payload = cli.build_deploy_payload(tmp_path)
    assert payload["ref"] == "refs/heads/main"
    assert payload["repository"]["full_name"] == "acme/widgets"
    assert payload["repository"]["clone_url"] == "https://github.com/acme/widgets.git"
    assert payload["head_commit"]["message"] == "second commit"
    assert len(payload["after"]) == 40 and payload["before"] != "0" * 40


def test_cli_status_json_exit_code(cli, capsys):
    def fake_show(unit):
        return {"ActiveState": "failed" if unit == "orion-beat" else "active", "SubState": "running", "MainPID": "0"}

    with patch.object(cli, "systemctl_show", side_effect=fake_show):
        code = cli.main(["--json", "status"])
    assert code == 3
    data = json.loads(capsys.readouterr().out)
    assert {s["service"]: s["active"] for s in data["services"]}["orion-beat"] == "failed"


def _completed(stdout: str = "") -> MagicMock:
    return MagicMock(stdout=stdout, returncode=0, stderr="")


def test_daemon_is_active_requires_exact_output():
    daemon = OrionMonitorDaemon()
    with patch.object(monitor_daemon.subprocess, "run", return_value=_completed("active\n")):
        assert daemon.is_active("orion-api")
    with patch.object(monitor_daemon.subprocess, "run", return_value=_completed("inactive\n")):
        assert not daemon.is_active("orion-api")


def test_daemon_restarts_inactive_services_but_not_itself():
    daemon = OrionMonitorDaemon()
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "is-active":
            return _completed("inactive\n" if cmd[2] == "orion-worker" else "active\n")
        return _completed()

    with patch.object(monitor_daemon.subprocess, "run", side_effect=fake_run), patch.object(daemon, "slack_alert") as alert:
        assert daemon.check_services() == ["orion-worker"]
        assert daemon.check_services() == []

    checked = [c[2] for c in calls if c[1] == "is-active"]
    assert "orion-monitor" not in checked
    assert [c for c in calls if c[1] == "restart"] == [["systemctl", "restart", "orion-worker"]]
    alert.assert_called_once()


def test_daemon_memory_check_restarts_api():
    daemon = OrionMonitorDaemon()
    with (
        patch.object(daemon, "api_rss_bytes", return_value=monitor_daemon.MAX_API_RSS_BYTES + 1),
        patch.object(daemon, "restart") as restart,
    ):
        assert daemon.check_memory() is False
    restart.assert_called_once_with("orion-api", "memory limit exceeded")


def test_daemon_low_disk_vacuums_journal():
    daemon = OrionMonitorDaemon()
    with (
        patch.object(monitor_daemon.shutil, "disk_usage", return_value=MagicMock(free=10)),
        patch.object(monitor_daemon.subprocess, "run", return_value=_completed()) as run,
    ):
        assert daemon.check_disk() is False
    run.assert_called_once()
    assert run.call_args.args[0] == ["journalctl", "--vacuum-size=1G"]


def test_daemon_database_failure_alerts():
    psycopg2 = pytest.importorskip("psycopg2")
    daemon = OrionMonitorDaemon()
    with (
        patch.object(psycopg2, "connect", side_effect=psycopg2.OperationalError("refused")),
        patch.object(daemon, "slack_alert") as alert,
    ):
        assert daemon.check_database() is False
    alert.assert_called_once()


def test_cli_developer_subcommands_registered(cli):
    parser = cli.build_parser()
    for name in ("scan", "test", "risk", "explain", "fix", "intelligence", "runs"):
        assert name in parser.format_help()


def test_cli_api_headers_uses_env(cli, monkeypatch):
    monkeypatch.setenv("ORION_API_KEY", "test-key-123")
    headers = cli.api_headers()
    assert headers["X-ORION-API-Key"] == "test-key-123"


def test_cli_repo_trigger_fields(cli, tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "a.txt").write_text("1")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "first")
    _git(tmp_path, "remote", "add", "origin", "https://github.com/acme/payments.git")

    fields = cli.repo_trigger_fields(tmp_path)
    assert fields["repo_full_name"] == "acme/payments"
    assert fields["branch"] == "main"
    assert fields["clone_url"].endswith("acme/payments.git")


def test_cli_risk_local_git(cli, tmp_path, capsys):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "README.md").write_text("docs")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "docs")

    with patch.object(cli, "resolve_repo", return_value=tmp_path):
        code = cli.main(["risk", "HEAD", "--repo-path", str(tmp_path), "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert "report" in data
    assert data["report"]["final_risk"] is not None


def test_cli_explain_incident_calls_rag(cli, capsys):
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"answer": "rollback recommended", "chunks": []}

    with patch.object(cli, "api_request", return_value=mock_resp) as api:
        code = cli.main(["explain", "incident", "INC-204", "--json"])

    assert code == 0
    api.assert_called_once()
    assert api.call_args.args[1] == "/api/v1/intelligence/rag"
    assert api.call_args.kwargs["params"]["q"] == "incident INC-204"
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True


def test_cli_fix_maps_test_alias(cli, capsys):
    runs = [{"id": "run-1", "status": "blocked_tests", "repo_full_name": "acme/app"}]
    ok_resp = MagicMock(status_code=200, json=lambda: {"status": "resuming", "pipeline_run_id": "run-1"})

    with patch.object(cli, "_list_runs", return_value=runs), patch.object(cli, "api_request", return_value=ok_resp):
        code = cli.main(["fix", "test", "--json"])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["run_id"] == "run-1"
