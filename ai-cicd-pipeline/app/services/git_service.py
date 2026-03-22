import asyncio
import shutil
import subprocess
from pathlib import Path
from uuid import UUID


class GitService:
    def __init__(self) -> None:
        self.base = Path("/tmp/pipeline")

    def _run_path(self, run_id: UUID | str) -> Path:
        return self.base / str(run_id)

    async def clone_repo(self, clone_url: str, run_id: UUID | str) -> str:
        path = self._run_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

        def _clone() -> str:
            subprocess.run(
                ["git", "clone", "--depth=1", clone_url, str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
            return str(path)

        return await asyncio.to_thread(_clone)

    async def get_diff(self, repo_path: str) -> str:
        def _diff() -> str:
            try:
                p = subprocess.run(
                    ["git", "-C", repo_path, "diff", "HEAD~1", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if p.returncode == 0 and p.stdout:
                    return p.stdout
            except Exception:
                pass
            p2 = subprocess.run(
                ["git", "-C", repo_path, "show", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            return p2.stdout or ""

        return await asyncio.to_thread(_diff)

    async def get_changed_files(self, repo_path: str) -> list[str]:
        def _names() -> list[str]:
            p = subprocess.run(
                ["git", "-C", repo_path, "diff", "--name-only", "HEAD~1", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            if p.returncode != 0 or not p.stdout.strip():
                return []
            return [line.strip() for line in p.stdout.splitlines() if line.strip()]

        return await asyncio.to_thread(_names)

    def cleanup_repo(self, run_id: UUID | str) -> None:
        path = self._run_path(run_id)
        shutil.rmtree(path, ignore_errors=True)

    async def get_commit_message(self, repo_path: str) -> str:
        def _msg() -> str:
            p = subprocess.run(
                ["git", "-C", repo_path, "log", "-1", "--pretty=%B"],
                capture_output=True,
                text=True,
                check=False,
            )
            return p.stdout.strip()

        return await asyncio.to_thread(_msg)
