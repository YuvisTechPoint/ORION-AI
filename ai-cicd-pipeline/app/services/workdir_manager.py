"""ORION pipeline workspace lifecycle — Windows-safe cleanup, per-run locks, orphan recovery."""

from __future__ import annotations

import os
import re
import shutil
import stat
import sys
import threading
import time
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("workdir_manager")

_RUN_LOCKS: dict[str, Lock] = {}
_RUN_LOCKS_GUARD = Lock()
_ACTIVE_CHECKOUTS: dict[str, Path] = {}
_UUID_DIR = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_TRASH_PREFIX = ".orion-trash-"
_CHECKOUTS_DIR = "checkouts"
_WIN_LOCKED_ERRNOS = {13, 16, 32}  # permission, busy, sharing violation (Windows)


class WorkdirCleanupError(RuntimeError):
    """Raised when a pipeline workspace cannot be removed after all recovery attempts."""


def _run_lock(run_id: str) -> Lock:
    with _RUN_LOCKS_GUARD:
        if run_id not in _RUN_LOCKS:
            _RUN_LOCKS[run_id] = Lock()
        return _RUN_LOCKS[run_id]


def _chmod_writable(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _chmod_writable_tree(root: Path) -> None:
    if not root.exists():
        return
    for dirpath, _dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames + _dirnames:
            _chmod_writable(Path(dirpath) / name)
    _chmod_writable(root)


def _on_rm_error(func, path, _exc_info) -> None:  # type: ignore[no-untyped-def]
    _chmod_writable(Path(path))
    func(path)


def _is_locked_oserror(exc: OSError) -> bool:
    return exc.errno in _WIN_LOCKED_ERRNOS or getattr(exc, "winerror", None) in _WIN_LOCKED_ERRNOS


def _dir_is_empty(path: Path) -> bool:
    try:
        return not any(path.iterdir())
    except OSError:
        return False


def _rename_to_trash(path: Path, attempts: int) -> bool:
    """Move a locked tree aside; returns True when the original path is gone."""
    for attempt in range(attempts):
        trash = path.parent / f"{_TRASH_PREFIX}{path.name}-{int(time.time() * 1000)}-{attempt}"
        try:
            path.rename(trash)
            logger.info("renamed locked workspace %s -> %s", path.name, trash.name)
            force_remove_path(trash, retries=attempts)
            return True
        except OSError as exc:
            if _is_locked_oserror(exc):
                time.sleep(0.1 * (2**attempt))
                continue
            logger.warning("rename to trash failed for %s: %s", path, exc)
            return False
    return False


def force_remove_path(
    path: Path, *, retries: int | None = None, raise_on_failure: bool = True
) -> bool:
    """Remove a path tree; retries chmod + rename-to-trash on Windows file locks."""
    if not path.exists():
        return True

    attempts = retries if retries is not None else settings.pipeline_workdir_cleanup_retries
    last_err: OSError | None = None

    for attempt in range(attempts):
        try:
            if sys.version_info >= (3, 12):
                shutil.rmtree(path, onexc=_on_rm_error)
            else:
                shutil.rmtree(path, onerror=_on_rm_error)
            if not path.exists():
                return True
        except OSError as exc:
            last_err = exc
            _chmod_writable_tree(path)
            time.sleep(0.1 * (attempt + 1))

    if path.exists() and _rename_to_trash(path, attempts):
        return True

    if path.exists():
        if raise_on_failure:
            raise WorkdirCleanupError(
                f"could not remove pipeline workspace {path}"
                + (f": {last_err}" if last_err else "")
            ) from last_err
        logger.warning("deferred cleanup for locked workspace %s: %s", path, last_err)
        return False
    return True


def pipeline_root(base_dir: str | None = None) -> Path:
    return Path(base_dir or settings.pipeline_workdir)


def run_workspace_path(run_id: UUID | str, base_dir: str | None = None) -> Path:
    return pipeline_root(base_dir) / str(run_id)


def run_checkouts_dir(run_id: UUID | str, base_dir: str | None = None) -> Path:
    return run_workspace_path(run_id, base_dir) / _CHECKOUTS_DIR


def reports_workspace_path(run_id: UUID | str, base_dir: str | None = None) -> Path:
    return pipeline_root(base_dir) / f"{run_id}-reports"


def _iter_checkout_candidates(run_id: UUID | str, base_dir: str | None = None) -> list[Path]:
    rid = str(run_id)
    root = run_workspace_path(run_id, base_dir)
    candidates: list[Path] = []

    active = _ACTIVE_CHECKOUTS.get(rid)
    if active is not None:
        candidates.append(active)

    checkouts = run_checkouts_dir(run_id, base_dir)
    if checkouts.is_dir():
        for child in sorted(checkouts.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if child.is_dir():
                candidates.append(child)

    # Legacy layout: repo cloned directly into {run_id}/ before checkouts/ existed.
    if root.is_dir() and root.name == rid:
        if (root / ".git").is_dir():
            candidates.append(root)

    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(path)
    return ordered


def resolve_checkout_path(run_id: UUID | str, base_dir: str | None = None) -> Path | None:
    """Return the newest usable git checkout for a run, if any."""
    for path in _iter_checkout_candidates(run_id, base_dir):
        if (path / ".git").is_dir():
            return path
    return None


def _prune_checkouts_async(run_id: UUID | str, base_dir: str | None, keep: Path | None) -> None:
    rid = str(run_id)
    root = run_workspace_path(run_id, base_dir)
    keep_resolved = keep.resolve() if keep else None

    def _worker() -> None:
        with _run_lock(rid):
            checkouts = run_checkouts_dir(run_id, base_dir)
            if checkouts.is_dir():
                for child in list(checkouts.iterdir()):
                    if keep_resolved and child.resolve() == keep_resolved:
                        continue
                    force_remove_path(child, raise_on_failure=False)

            # Legacy flat checkout at {run_id}/.git — prune siblings, never delete checkouts/.
            if (root / ".git").is_dir():
                for item in list(root.iterdir()):
                    if item.name in {_CHECKOUTS_DIR}:
                        continue
                    if keep_resolved and item.resolve() == keep_resolved:
                        continue
                    force_remove_path(item, raise_on_failure=False)

    threading.Thread(target=_worker, name=f"orion-workdir-prune-{rid[:8]}", daemon=True).start()


def allocate_checkout_path(run_id: UUID | str, base_dir: str | None = None) -> Path:
    """Return a fresh path for git clone — never blocks on locked prior checkouts (Windows-safe)."""
    rid = str(run_id)
    checkouts = run_checkouts_dir(run_id, base_dir)
    checkouts.mkdir(parents=True, exist_ok=True)
    path = checkouts / f"{time.time_ns()}-{uuid4().hex[:8]}"
    while path.exists():
        path = checkouts / f"{time.time_ns()}-{uuid4().hex[:8]}"

    with _run_lock(rid):
        _ACTIVE_CHECKOUTS[rid] = path
        _prune_checkouts_async(run_id, base_dir, keep=path)

    logger.info("allocated checkout workspace for run %s at %s", rid, path)
    return path


def prepare_run_workspace(run_id: UUID | str, base_dir: str | None = None) -> Path:
    """Backward-compatible alias — always allocates a fresh checkout directory."""
    return allocate_checkout_path(run_id, base_dir)


def release_run_workspace(run_id: UUID | str, base_dir: str | None = None) -> None:
    """Release checkout + reports directories for a pipeline run (best-effort, non-blocking)."""
    rid = str(run_id)
    _ACTIVE_CHECKOUTS.pop(rid, None)

    def _worker() -> None:
        with _run_lock(rid):
            force_remove_path(run_workspace_path(run_id, base_dir), raise_on_failure=False)
            force_remove_path(reports_workspace_path(run_id, base_dir), raise_on_failure=False)
        logger.info("released workspace for run %s", rid)

    threading.Thread(target=_worker, name=f"orion-workdir-release-{rid[:8]}", daemon=True).start()


def _is_stale(path: Path, now: float, max_age_seconds: float) -> bool:
    try:
        return (now - path.stat().st_mtime) >= max_age_seconds
    except OSError:
        return True


def sweep_workdir_tree(
    root: Path,
    *,
    active_run_ids: set[str],
    respect_stale_age: bool,
) -> int:
    """Remove orphan UUID workspaces and leftover trash dirs under the pipeline root."""
    if not root.is_dir():
        return 0

    max_age = settings.pipeline_workdir_stale_hours * 3600
    now = time.time()
    removed = 0

    for child in list(root.iterdir()):
        name = child.name
        try:
            if name.startswith(_TRASH_PREFIX):
                if not respect_stale_age or _is_stale(child, now, max_age):
                    if force_remove_path(child, raise_on_failure=False):
                        removed += 1
                continue

            if name.endswith("-reports"):
                run_part = name[: -len("-reports")]
                if not _UUID_DIR.match(run_part):
                    continue
                if run_part in active_run_ids:
                    continue
                if respect_stale_age and not _is_stale(child, now, max_age):
                    continue
                if force_remove_path(child, raise_on_failure=False):
                    removed += 1
                continue

            if not _UUID_DIR.match(name):
                continue
            if name in active_run_ids:
                continue
            if respect_stale_age and not _is_stale(child, now, max_age):
                continue
            if force_remove_path(child, raise_on_failure=False):
                removed += 1
        except WorkdirCleanupError as exc:
            logger.warning("workspace sweep skipped %s: %s", child, exc)

    return removed


async def recover_pipeline_workdirs_at_startup() -> int:
    """After API restart, drop workspaces for runs that are not about to execute."""
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.pipeline_run import PipelineRun

    active: set[str] = set()
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(PipelineRun.id, PipelineRun.status))).all()
        active = {str(run_id) for run_id, status in rows if status == "queued"}

    removed = sweep_workdir_tree(
        pipeline_root(),
        active_run_ids=active,
        respect_stale_age=False,
    )
    if removed:
        logger.info("startup workspace recovery removed %d director(ies)", removed)
    return removed


def sweep_stale_workdirs(active_run_ids: set[str]) -> int:
    """Periodic sweep for abandoned workspaces (reaper / maintenance)."""
    return sweep_workdir_tree(
        pipeline_root(),
        active_run_ids=active_run_ids,
        respect_stale_age=True,
    )
