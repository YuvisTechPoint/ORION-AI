"""Tests for repository intelligence heuristics and API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.utils.repository_intelligence import analyze_repository


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    (tmp_path / "requirements.txt").write_text("fastapi==0.115.0\nuvicorn[standard]>=0.30.0\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\nlicense = "MIT"\n', encoding="utf-8")
    (tmp_path / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (tmp_path / ".github" / "CODEOWNERS").write_text("*.py @team-backend\n", encoding="utf-8")
    return tmp_path


def test_analyze_repository_detects_python_stack(sample_repo: Path):
    report = analyze_repository(str(sample_repo), repo="acme/demo")
    assert report["stack"]["languages"][0]["name"] == "python"
    assert any(f["name"] == "fastapi" for f in report["stack"]["frameworks"])
    assert report["licenses"]["primary"] == "MIT"
    assert report["ownership"]["codeowners_found"] is True
    assert report["fingerprint"]["sha256"]
    assert "github_actions" in report["stack"]["ci_systems"]


def test_monorepo_detection(tmp_path: Path):
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - packages/*\n", encoding="utf-8")
    pkg = tmp_path / "packages" / "web"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text('{"name":"web","license":"ISC"}\n', encoding="utf-8")
    report = analyze_repository(str(tmp_path))
    assert report["monorepo"]["detected"] is True
    assert report["monorepo"]["workspace_marker"] == "pnpm-workspace.yaml"


def test_breaking_change_hints_from_openapi_diff(sample_repo: Path):
    diff = """--- openapi.json
+++ openapi.json
@@
-  "/api/v1/users/{id}":
"""
    report = analyze_repository(
        str(sample_repo),
        changed_files=["openapi.json"],
        diff_text=diff,
    )
    hints = report["api_surface"]["breaking_change_hints"]
    assert any(h["path"] == "/api/v1/users/{id}" for h in hints)


def test_repository_intel_api_local_path(sample_repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.api.routes.intelligence.settings.app_env", "development")
    client = TestClient(app)
    resp = client.post(
        "/api/v1/intelligence/repository",
        json={"repo_path": str(sample_repo), "use_llm": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["report"]["stack"]["languages"][0]["name"] == "python"
    assert body["persisted"] is False


def test_repository_intel_api_requires_source():
    client = TestClient(app)
    resp = client.post("/api/v1/intelligence/repository", json={"use_llm": False})
    assert resp.status_code == 400
