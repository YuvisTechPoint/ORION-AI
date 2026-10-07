"""Isolated workspace for autonomous patch verification (no production credentials)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.utils.tools import repo_env, tool_cmd


@dataclass
class SandboxResult:
    workspace: str
    pytest_exit_code: int
    pytest_output: str
    applied_files: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "pytest_exit_code": self.pytest_exit_code,
            "pytest_output": self.pytest_output[-8000:],
            "applied_files": self.applied_files,
            "passed": self.pytest_exit_code in (0, 5),
        }


class AgentSandbox:
    """Ephemeral copy of a repository for safe autonomous fix verification."""

    def __init__(self) -> None:
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None
        self.workspace: Path | None = None

    def create(self, repo_path: str) -> Path:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="orion-sandbox-")
        dest = Path(self._tmpdir.name)
        shutil.copytree(
            repo_path,
            dest,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".venv", "venv"),
            dirs_exist_ok=True,
        )
        self.workspace = dest
        return dest

    def apply_patches(self, patches: list[dict[str, Any]]) -> list[str]:
        if self.workspace is None:
            raise RuntimeError("sandbox not created")
        applied: list[str] = []
        for patch in patches:
            rel = str(patch.get("file_path", "")).replace("\\", "/")
            content = patch.get("fixed_content")
            if not rel or not isinstance(content, str):
                continue
            target = self.workspace / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            applied.append(rel)
        return applied

    def run_pytest(self, timeout: int = 120) -> tuple[int, str]:
        if self.workspace is None:
            raise RuntimeError("sandbox not created")
        tests = self.workspace / "tests"
        alt = self.workspace / "test"
        if not tests.is_dir() and not alt.is_dir():
            return 0, "no tests directory — sandbox verify skipped"
        cmd = tool_cmd("pytest", str(self.workspace), "--tb=line", "-q", "--timeout=60")
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=str(self.workspace),
                env=repo_env(str(self.workspace)),
            )
            return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            return 124, "pytest timed out in sandbox"
        except (FileNotFoundError, OSError) as exc:
            return 127, f"pytest unavailable in sandbox: {exc}"

    def verify_patches(self, repo_path: str, patches: list[dict[str, Any]]) -> SandboxResult:
        self.create(repo_path)
        applied = self.apply_patches(patches)
        code, output = self.run_pytest()
        return SandboxResult(
            workspace=str(self.workspace),
            pytest_exit_code=code,
            pytest_output=output,
            applied_files=applied,
        )

    def cleanup(self) -> None:
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None
            self.workspace = None

    def __enter__(self) -> "AgentSandbox":
        return self

    def __exit__(self, *args: object) -> None:
        self.cleanup()
