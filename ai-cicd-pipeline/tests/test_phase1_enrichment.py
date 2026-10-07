from app.utils.container_security import scan_container_security
from app.utils.iac_security import scan_iac_security
from app.utils.sbom import generate_sbom
from app.utils.secrets_guardian import scan_secrets
from app.utils.service_graph import build_service_graph
from app.utils.test_intelligence import analyze_flaky_tests, select_relevant_tests
from app.utils.release_passport import build_release_passport


def test_service_graph_compose(tmp_path):
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n  api:\n    image: api\n  redis:\n    image: redis\n",
        encoding="utf-8",
    )
    graph = build_service_graph(str(tmp_path), changed_files=["app/main.py"])
    assert graph["node_count"] >= 2
    assert "redis" in graph["nodes"]


def test_sbom_from_requirements(tmp_path, monkeypatch):
    monkeypatch.setattr("app.utils.external_scanners.run_syft", lambda *_a, **_k: None)
    (tmp_path / "requirements.txt").write_text("flask==3.0.0\nrequests>=2.31.0\n", encoding="utf-8")
    sbom = generate_sbom(str(tmp_path), commit="abc123", repo="demo/app")
    assert sbom["stats"]["component_count"] >= 1
    assert "component(s)" in sbom["summary"]
    assert sbom["bomFormat"] == "CycloneDX"


def test_secrets_guardian_detects_github_token(tmp_path):
    (tmp_path / "config.py").write_text('TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz123456"\n', encoding="utf-8")
    report = scan_secrets(str(tmp_path), changed_files=["config.py"])
    assert report["critical_count"] >= 1
    assert report["passed"] is False


def test_container_security_root_user(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\nRUN pip install flask\n", encoding="utf-8")
    report = scan_container_security(str(tmp_path))
    assert report["high_count"] >= 1


def test_iac_open_security_group(tmp_path):
    (tmp_path / "main.tf").write_text('resource "aws_security_group" "x" { cidr = "0.0.0.0/0" }\n', encoding="utf-8")
    report = scan_iac_security(str(tmp_path), changed_files=["main.tf"])
    assert report["critical_count"] >= 1


def test_test_selection_maps_module(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_payment.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (tmp_path / "payment").mkdir()
    (tmp_path / "payment" / "service.py").write_text("x=1\n", encoding="utf-8")
    sel = select_relevant_tests(["payment/service.py"], str(tmp_path))
    assert sel["mode"] == "selected"
    assert any("payment" in t for t in sel["selected_tests"])


def test_flaky_classification():
    hist = [{"tests": [{"nodeid": "t::a", "outcome": "failed"}, {"nodeid": "t::a", "outcome": "passed"}]}]
    current = {"tests": [{"nodeid": "t::a", "outcome": "passed"}]}
    report = analyze_flaky_tests(current, hist)
    assert report["tests_tracked"] >= 1


def test_release_passport_aggregates():
    passport = build_release_passport(
        run_id="00000000-0000-0000-0000-000000000001",
        repo="org/app",
        branch="main",
        commit="deadbeef",
        artifacts={
            "code_analysis": {"severity": "pass"},
            "security_scan": {"highest_severity": "low", "vulnerabilities": []},
            "qa_report": {"verdict": "pass", "test_summary": {"passed": 10, "total": 10}},
            "stress_report": {"performance_verdict": "pass"},
            "approval": {"decision": "approved", "confidence": 0.9},
            "change_risk_report": {"final_risk": 12, "risk_level": "low"},
            "sbom": {"components": [{"name": "flask"}], "stats": {"component_count": 1}},
        },
        deploy_mode="simulate",
        environment="staging",
    )
    assert passport["all_checks_passed"] is True
    assert passport["tests"]["passed"] == 10
