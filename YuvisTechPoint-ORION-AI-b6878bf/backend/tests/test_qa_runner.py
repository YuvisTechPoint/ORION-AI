from services.qa_runner import QARunner


def test_qa_runner_passes_for_valid_tests() -> None:
    runner = QARunner(timeout_seconds=10)
    repo_files = {
        "test_sample.py": "def test_ok():\n    assert 1 + 1 == 2\n",
    }
    result = runner.run_pytest(repo_files)
    assert result["passed"] is True
    assert result["exit_code"] == 0


def test_qa_runner_fails_without_tests() -> None:
    runner = QARunner(timeout_seconds=10)
    repo_files = {
        "app.py": "print('hello')\n",
    }
    result = runner.run_pytest(repo_files)
    assert result["passed"] is False
    assert result["exit_code"] == -1
