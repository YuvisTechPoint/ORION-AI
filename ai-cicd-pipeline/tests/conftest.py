import json
import uuid
from typing import Any

import pytest

from app.main import app


@pytest.fixture(autouse=True)
def _disable_init_db(monkeypatch: pytest.MonkeyPatch) -> None:
    async def noop() -> None:
        return None

    monkeypatch.setattr("app.main.init_db", noop)


@pytest.fixture
def mock_anthropic_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    class Msg:
        content = [
            type(
                "B",
                (),
                {
                    "text": '{"severity":"pass","issues":[],"summary":"ok","good_practices_found":[],"critical_issues_count":0,"warnings_count":0}'
                },
            )()
        ]
        usage = type("U", (), {"output_tokens": 10})()

    class Client:
        messages = type(
            "M",
            (),
            {"create": staticmethod(lambda **kw: Msg())},
        )()

    return Client()


@pytest.fixture
def sample_github_payload() -> dict[str, Any]:
    return {
        "ref": "refs/heads/main",
        "after": "c" * 40,
        "commits": [{"id": "d" * 40, "message": "test"}],
        "repository": {
            "full_name": "acme/demo",
            "clone_url": "https://github.com/acme/demo.git",
        },
        "pusher": {"name": "alice"},
    }


@pytest.fixture
def sample_diff_text() -> str:
    return """diff --git a/app/db.py b/app/db.py
--- a/app/db.py
+++ b/app/db.py
@@ -1,5 +1,8 @@
+import os
 import sqlite3
 
 def get_user(name):
-    q = f"SELECT * FROM users WHERE name = '{name}'"
+    q = f"SELECT * FROM users WHERE name = '{name}'"
     return sqlite3.connect("x").execute(q).fetchall()
+
+def undocumented():
+    return 1
"""


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
