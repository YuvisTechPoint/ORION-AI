from core.rule_engine import run_quality_rules, run_security_rules


def test_quality_rules_include_file_path_from_repo_files() -> None:
    findings = run_quality_rules(
        code="",
        diff="",
        config_text="",
        repo_files={"app/main.py": "# TODO\nprint('debug')\n"},
    )

    assert findings
    assert all(item.get("file_path") for item in findings)
    assert any(item["file_path"] == "app/main.py" for item in findings)


def test_security_rules_include_file_path_from_repo_files() -> None:
    findings = run_security_rules(
        code="",
        diff="",
        config_text="",
        repo_files={"src/unsafe.py": "token='abc'\nvalue = eval('1+1')\n"},
    )

    assert findings
    assert all(item.get("file_path") for item in findings)
    assert any(item["file_path"] == "src/unsafe.py" for item in findings)
