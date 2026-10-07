import asyncio
import subprocess
import time
from pathlib import Path
from uuid import UUID

from app.config import settings
from app.services.workdir_manager import (
    allocate_checkout_path,
    force_remove_path,
    pipeline_root,
    release_run_workspace,
    reports_workspace_path,
    resolve_checkout_path,
)
from app.utils.logger import get_logger

logger = get_logger("git_service")

# Backward-compatible alias used by tests and legacy imports.
force_rmtree = force_remove_path


class GitService:
    def __init__(self, base_dir: str | None = None) -> None:
        self.base = pipeline_root(base_dir)

    async def clone_repo(
        self, clone_url: str, run_id: UUID | str, branch: str | None = None
    ) -> str:
        path = allocate_checkout_path(run_id, str(self.base))

        # depth=2 so `git diff HEAD~1 HEAD` works for the pushed commit.
        cmd = ["git", "clone", "--depth=2"]
        if branch:
            cmd += ["--branch", branch]
        cmd += [clone_url, str(path)]

        def _clone() -> str:
            started = time.time()
            logger.info("cloning %s -> %s", clone_url, path)
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=600,
                )
                if proc.returncode != 0 and branch:
                    logger.warning("clone of branch %s failed, retrying default branch", branch)
                    force_remove_path(path, raise_on_failure=False)
                    proc = subprocess.run(
                        ["git", "clone", "--depth=2", clone_url, str(path)],
                        capture_output=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                        timeout=600,
                    )
                if proc.returncode != 0:
                    force_remove_path(path, raise_on_failure=False)
                    raise RuntimeError(f"git clone failed: {proc.stderr.strip()[:2000]}")
                logger.info("clone complete in %.2fs", time.time() - started)
                return str(path)
            except Exception:
                force_remove_path(path, raise_on_failure=False)
                raise

        return await asyncio.to_thread(_clone)

    async def ensure_repo(
        self, clone_url: str, run_id: UUID | str, branch: str | None = None
    ) -> str:
        existing = resolve_checkout_path(run_id, str(self.base))
        if existing is not None:
            logger.info("reusing existing checkout for run %s at %s", run_id, existing)
            return str(existing)
        return await self.clone_repo(clone_url, run_id, branch=branch)

    async def get_diff(self, repo_path: str) -> str:
        def _diff() -> str:
            p = subprocess.run(
                ["git", "-C", repo_path, "diff", "HEAD~1", "HEAD"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if p.returncode == 0 and p.stdout:
                return p.stdout
            p2 = subprocess.run(
                ["git", "-C", repo_path, "show", "HEAD"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            return p2.stdout or ""

        return await asyncio.to_thread(_diff)

    async def get_changed_files(self, repo_path: str) -> list[str]:
        def _names() -> list[str]:
            p = subprocess.run(
                ["git", "-C", repo_path, "diff", "--name-only", "HEAD~1", "HEAD"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if p.returncode != 0 or not p.stdout.strip():
                p = subprocess.run(
                    ["git", "-C", repo_path, "show", "--name-only", "--pretty=format:", "HEAD"],
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
            return [line.strip() for line in (p.stdout or "").splitlines() if line.strip()]

        return await asyncio.to_thread(_names)

    def reports_dir(self, run_id: UUID | str) -> Path:
        path = reports_workspace_path(run_id, str(self.base))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cleanup_repo(self, run_id: UUID | str) -> None:
        release_run_workspace(run_id, str(self.base))

    async def get_commit_message(self, repo_path: str) -> str:
        def _msg() -> str:
            p = subprocess.run(
                ["git", "-C", repo_path, "log", "-1", "--pretty=%B"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            return p.stdout.strip()

        return await asyncio.to_thread(_msg)
