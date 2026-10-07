import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.utils.hmac_validator import validate_github_signature


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(settings.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()


def headers_for(body: bytes, event: str = "push") -> dict[str, str]:
    return {"X-Hub-Signature-256": sign(body), "X-GitHub-Event": event, "Content-Type": "application/json"}


@pytest.fixture
def mocked_side_effects():
    with (
        patch("app.api.routes.webhook.dispatch_pipeline", MagicMock(return_value="inline")) as dispatch,
        patch("app.api.routes.webhook.github_service") as gh,
        patch("app.api.routes.webhook.slack_service") as slack,
    ):
        gh.set_commit_status = AsyncMock(return_value=None)
        gh.safe_commit_status = AsyncMock(return_value=None)
        gh.delete_branch = AsyncMock(return_value=True)
        slack.send_pipeline_start = AsyncMock(return_value=None)
        slack.send_text = AsyncMock(return_value=None)
        yield {"dispatch": dispatch, "github": gh, "slack": slack}


async def test_webhook_valid_signature(async_client, sample_github_payload, mocked_side_effects, db_session):
    body = json.dumps(sample_github_payload).encode()
    res = await async_client.post("/api/v1/webhook/github", content=body, headers=headers_for(body))

    assert res.status_code == 202
    data = res.json()
    assert data["status"] == "accepted"
    assert data["commit_id"] == sample_github_payload["after"]

    run = (await db_session.execute(select(PipelineRun))).scalar_one()
    assert str(run.id) == data["pipeline_run_id"]
    assert run.status == "queued"
    assert run.branch == "main"
    assert run.short_commit_id == sample_github_payload["after"][:8]
    mocked_side_effects["dispatch"].assert_called_once()
    assert str(mocked_side_effects["dispatch"].call_args.args[0]) == data["pipeline_run_id"]
    mocked_side_effects["github"].safe_commit_status.assert_awaited_once()


async def test_webhook_invalid_signature(async_client, sample_github_payload, mocked_side_effects):
    body = json.dumps(sample_github_payload).encode()
    headers = {**headers_for(body), "X-Hub-Signature-256": "sha256=deadbeef"}
    res = await async_client.post("/api/v1/webhook/github", content=body, headers=headers)
    assert res.status_code == 403
    mocked_side_effects["dispatch"].assert_not_called()


async def test_webhook_tag_push(async_client, sample_github_payload, mocked_side_effects):
    payload = {**sample_github_payload, "ref": "refs/tags/v1.0.0"}
    body = json.dumps(payload).encode()
    res = await async_client.post("/api/v1/webhook/github", content=body, headers=headers_for(body))
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"
    mocked_side_effects["dispatch"].assert_not_called()


async def test_webhook_missing_signature_header(async_client, sample_github_payload, mocked_side_effects):
    body = json.dumps(sample_github_payload).encode()
    res = await async_client.post(
        "/api/v1/webhook/github", content=body, headers={"X-GitHub-Event": "push", "Content-Type": "application/json"}
    )
    assert res.status_code == 403


async def test_webhook_invalid_json(async_client, mocked_side_effects):
    body = b"{not-json"
    res = await async_client.post("/api/v1/webhook/github", content=body, headers=headers_for(body))
    assert res.status_code == 400


async def test_webhook_ping(async_client, mocked_side_effects):
    body = json.dumps({"zen": "Keep it logically awesome."}).encode()
    res = await async_client.post("/api/v1/webhook/github", content=body, headers=headers_for(body, "ping"))
    assert res.status_code == 200
    assert res.json()["event"] == "ping"


async def test_webhook_branch_deletion_ignored(async_client, sample_github_payload, mocked_side_effects):
    payload = {**sample_github_payload, "after": "0" * 40}
    body = json.dumps(payload).encode()
    res = await async_client.post("/api/v1/webhook/github", content=body, headers=headers_for(body))
    assert res.json() == {"status": "ignored", "reason": "branch deletion"}


async def test_webhook_payload_missing_repository_returns_400(async_client, mocked_side_effects):
    body = json.dumps({"ref": "refs/heads/main", "after": "a" * 40}).encode()
    res = await async_client.post("/api/v1/webhook/github", content=body, headers=headers_for(body))
    assert res.status_code == 400


def test_signature_helper_rejects_other_schemes():
    assert not validate_github_signature(b"x", "sha1=abc", "s")
    assert not validate_github_signature(b"x", None, "s")


def _pr_event(branch: str, merged: bool = True, action: str = "closed") -> dict[str, Any]:
    return {
        "action": action,
        "pull_request": {"number": 42, "merged": merged, "head": {"ref": branch}},
        "repository": {"full_name": "testuser/testrepo"},
    }


async def _add_registry(db_session, run, branch: str) -> PipelineArtifact:
    art = PipelineArtifact(
        pipeline_run_id=run.id,
        artifact_type="auto_pr_registry",
        content={
            "branches": [
                {"branch_name": branch, "pr_number": 42, "pr_url": "https://github.com/x/pull/42",
                 "category": "security", "merged": False, "deleted": False},
                {"branch_name": "orion/fix-code-quality-abc", "pr_number": 43, "merged": False, "deleted": False},
            ]
        },
    )
    db_session.add(art)
    await db_session.commit()
    return art


async def test_merged_orion_pr_deletes_branch(async_client, mocked_side_effects, db_session, pipeline_run):
    branch = "orion/fix-security-abc12345"
    art = await _add_registry(db_session, pipeline_run, branch)

    body = json.dumps(_pr_event(branch)).encode()
    res = await async_client.post("/api/v1/webhook/github", content=body, headers=headers_for(body, "pull_request"))

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "branch": branch, "branch_deleted": True, "pr_number": 42}
    mocked_side_effects["github"].delete_branch.assert_awaited_once_with("testuser/testrepo", branch)

    await db_session.refresh(art)
    entries = {e["branch_name"]: e for e in art.content["branches"]}
    assert entries[branch]["merged"] is True and entries[branch]["deleted"] is True
    assert entries["orion/fix-code-quality-abc"]["merged"] is False


async def test_dedicated_pr_endpoint(async_client, mocked_side_effects, db_session, pipeline_run):
    branch = "orion/fix-test-failures-abc12345"
    await _add_registry(db_session, pipeline_run, branch)
    body = json.dumps(_pr_event(branch)).encode()
    res = await async_client.post("/api/v1/webhook/github/pr", content=body, headers=headers_for(body, "pull_request"))
    assert res.json()["branch_deleted"] is True


@pytest.mark.parametrize(
    ("event", "reason_fragment"),
    [
        (_pr_event("orion/fix-security-x", merged=False), "closed without merge"),
        (_pr_event("orion/fix-security-x", action="opened"), "action opened"),
        (_pr_event("feature/human-branch"), "not managed by ORION"),
    ],
)
async def test_pr_events_that_do_not_delete(async_client, mocked_side_effects, event, reason_fragment):
    body = json.dumps(event).encode()
    res = await async_client.post("/api/v1/webhook/github", content=body, headers=headers_for(body, "pull_request"))
    assert res.json()["status"] == "ignored"
    assert reason_fragment in res.json()["reason"]
    mocked_side_effects["github"].delete_branch.assert_not_called()
