import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class QARunner:
    """Runs pytest on submitted repository files in an isolated temp directory."""

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds

    def run_pytest(self, repo_files: dict[str, str]) -> dict[str, Any]:
        if not repo_files:
            return {
                "passed": False,
                "exit_code": -1,
                "summary": "No repo_files provided for real QA.",
                "stdout": "",
                "stderr": "repo_files is empty",
            }

        with tempfile.TemporaryDirectory(prefix="qa_repo_") as tmp:
            root = Path(tmp)
            test_file_count = 0
            for rel_path, content in repo_files.items():
                normalized = Path(rel_path)
                if normalized.is_absolute() or ".." in normalized.parts:
                    continue
                target = root / normalized
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                if target.name.startswith("test_") or target.name.endswith("_test.py"):
                    test_file_count += 1

            if test_file_count == 0:
                return {
                    "passed": False,
                    "exit_code": -1,
                    "summary": "No pytest test files found in submitted repo_files.",
                    "stdout": "",
                    "stderr": "Expected files like test_*.py",
                }

            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q"],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
                passed = proc.returncode == 0
                return {
                    "passed": passed,
                    "exit_code": proc.returncode,
                    "summary": "pytest execution complete",
                    "stdout": proc.stdout[-4000:],
                    "stderr": proc.stderr[-4000:],
                }
            except subprocess.TimeoutExpired as exc:
                return {
                    "passed": False,
                    "exit_code": -1,
                    "summary": "pytest timed out",
                    "stdout": (exc.stdout or "")[-4000:],
                    "stderr": (exc.stderr or "")[-4000:],
                }
