import os
import stat
import time
import uuid
from pathlib import Path

from app.services.workdir_manager import (
    allocate_checkout_path,
    force_remove_path,
    prepare_run_workspace,
    release_run_workspace,
    resolve_checkout_path,
    sweep_workdir_tree,
)


def test_force_remove_path_clears_readonly_git_objects(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.workdir_manager.settings.pipeline_workdir_cleanup_retries", 3)
    target = tmp_path / "repo" / ".git" / "objects" / "pack"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    os.chmod(target, stat.S_IREAD)
    force_remove_path(tmp_path / "repo")
    assert not (tmp_path / "repo").exists()


def test_allocate_checkout_uses_unique_paths_under_checkouts(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.workdir_manager.settings.pipeline_workdir", str(tmp_path))
    run_id = uuid.uuid4()
    stale = tmp_path / str(run_id)
    stale.mkdir()
    (stale / "locked").write_text("leftover from legacy layout")

    path = allocate_checkout_path(run_id, str(tmp_path))
    assert path.parent.name == "checkouts"
    assert path.parent.parent == stale
    assert not path.exists()

    path2 = allocate_checkout_path(run_id, str(tmp_path))
    assert path2 != path


def test_prepare_run_workspace_is_allocate_alias(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.workdir_manager.settings.pipeline_workdir", str(tmp_path))
    run_id = uuid.uuid4()
    path = prepare_run_workspace(run_id, str(tmp_path))
    assert "checkouts" in path.parts


def test_resolve_checkout_path_finds_git_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.workdir_manager.settings.pipeline_workdir", str(tmp_path))
    run_id = uuid.uuid4()
    checkout = allocate_checkout_path(run_id, str(tmp_path))
    checkout.mkdir()
    (checkout / ".git").mkdir()
    assert resolve_checkout_path(run_id, str(tmp_path)) == checkout.resolve()


def test_release_run_workspace_removes_checkout_and_reports(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.workdir_manager.settings.pipeline_workdir", str(tmp_path))
    run_id = uuid.uuid4()
    checkout = allocate_checkout_path(run_id, str(tmp_path))
    checkout.mkdir()
    (tmp_path / f"{run_id}-reports").mkdir()
    release_run_workspace(run_id, str(tmp_path))
    time.sleep(0.3)
    assert not (tmp_path / str(run_id)).exists()
    assert not (tmp_path / f"{run_id}-reports").exists()


def test_sweep_workdir_tree_keeps_active_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.workdir_manager.settings.pipeline_workdir", str(tmp_path))
    monkeypatch.setattr("app.services.workdir_manager.settings.pipeline_workdir_stale_hours", 0)
    active_id = str(uuid.uuid4())
    stale_id = str(uuid.uuid4())
    (tmp_path / active_id).mkdir()
    stale = tmp_path / stale_id
    stale.mkdir()
    os.utime(stale, (0, 0))
    removed = sweep_workdir_tree(tmp_path, active_run_ids={active_id}, respect_stale_age=True)
    assert removed == 1
    assert (tmp_path / active_id).exists()
    assert not (tmp_path / stale_id).exists()


def test_cleanup_tolerates_missing_dir(tmp_path):
    force_remove_path(tmp_path / "missing")
    assert not (tmp_path / "missing").exists()
