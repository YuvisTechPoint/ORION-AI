import pytest

from app.utils.text_analysis import (
    classify_log_type,
    diff_stats,
    files_in_diff,
    parse_commit_message,
    redact_secrets,
    run_text_operations,
    sanitize_for_agent,
    similarity_ratio,
    string_metrics,
    truncate_with_context,
)


def test_redact_secrets_masks_tokens():
    raw = "GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    assert "ghp_" not in redact_secrets(raw)
    assert "REDACTED" in redact_secrets(raw)


def test_files_in_diff_and_stats():
    diff = """diff --git a/app/main.py b/app/main.py
--- a/app/main.py
+++ b/app/main.py
@@ -1 +1 @@
-x = 1
+x = 2
"""
    assert files_in_diff(diff) == ["app/main.py"]
    stats = diff_stats(diff)
    assert stats["files_changed"] == 1
    assert stats["lines_added"] >= 1


def test_classify_log_type():
    assert classify_log_type("ERROR connection timed out after 30s") == "server_timeout"
    assert classify_log_type("ModuleNotFoundError: No module named 'flask'") == "build_error"


def test_run_text_operations_bundle():
    text = "ERROR timeout\nWARN slow query"
    out = run_text_operations(text, ["metrics", "classify_log", "errors", "sanitize"])
    assert out["log_type"] == "server_timeout"
    assert out["metrics"]["error_lines"] >= 1
    assert out["error_signatures"]
    assert "sanitized" in out


def test_parse_commit_message_conventional():
    parsed = parse_commit_message("feat(api)!: add webhook dedup\n\nDetails here.")
    assert parsed["conventional"] is True
    assert parsed["type"] == "feat"
    assert parsed["breaking"] is True


def test_truncate_with_context_keeps_both_ends():
    text = "A" * 100 + "MIDDLE" + "B" * 100
    out = truncate_with_context(text, 80)
    assert out.startswith("A")
    assert out.endswith("B")
    assert "truncated" in out


def test_similarity_ratio():
    assert similarity_ratio("hello world", "hello world") == 1.0
    assert similarity_ratio("abc", "xyz") < 0.5


async def test_text_analyze_api(async_client):
    r = await async_client.post(
        "/api/v1/tools/text-analyze",
        json={"text": "ERROR timeout on /health", "operations": ["metrics", "classify_log"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["log_type"] == "server_timeout"
    assert body["metrics"]["lines"] >= 1
