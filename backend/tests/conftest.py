"""Default test environment — avoid requiring local .env auth flags."""

from __future__ import annotations

import os

os.environ["AUTH_ENABLED"] = "false"
os.environ["API_REQUIRE_AUTH"] = "false"
os.environ["MULTIMODAL_AUTH_REQUIRED"] = "false"
os.environ["APP_ENV"] = "dev"
# Force isolated sync SQLite — parent shell may inherit async URL from run_all_stacks.ps1
_test_db = "sqlite:///./test_devops_platform.db"
os.environ["DATABASE_URL"] = _test_db
os.environ["SYNC_DATABASE_URL"] = _test_db
# Stable webhook HMAC secret for tests (avoid .env production webhook secret)
os.environ["GITHUB_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ.setdefault("QUEUE_BACKEND", "memory")
os.environ.setdefault("QA_MODE", "simulated")
os.environ.setdefault("LLM_MODE", "auto")
