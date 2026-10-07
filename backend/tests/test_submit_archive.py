"""Tests for POST /submit-archive."""

from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

from api.routes import get_orchestrator
from main import app


def _make_zip(content: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in content.items():
            zf.writestr(name, text)
    return buf.getvalue()


def test_submit_archive_accepts_zip() -> None:
    class FakeState:
        pipeline_id = "archive-test-001"
        current_stage = "dev"
        status = "running"

    class FakeOrchestrator:
        settings = type("S", (), {"qa_mode": "simulated"})()

        async def submit_code(self, request, github_token=None):
            return FakeState()

    app.dependency_overrides[get_orchestrator] = lambda: FakeOrchestrator()
    client = TestClient(app)
    try:
        payload = _make_zip({"main.py": "print('hello')\n", "tests/test_main.py": "def test_ok(): assert True\n"})
        response = client.post(
            "/submit-archive",
            data={"repo_name": "demo-archive", "force_real": "false"},
            files={"archive": ("project.zip", payload, "application/zip")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["pipeline_id"] == "archive-test-001"
    finally:
        app.dependency_overrides.clear()
