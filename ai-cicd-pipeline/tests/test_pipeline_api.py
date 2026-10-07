import uuid
from unittest.mock import patch

import pytest

from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun

RUNS = "/api/v1/pipeline/runs"


async def test_health(async_client):
    r = await async_client.get("/api/v1/pipeline/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_list_and_filter_runs(async_client, db_session, pipeline_run):
    db_session.add(
        PipelineRun(
            commit_id="f" * 40, short_commit_id="fffffff", branch="develop", repo_full_name="other/repo",
            clone_url="https://github.com/other/repo.git", pusher="bob", status="deployed",
        )
    )
    await db_session.commit()

    body = (await async_client.get(RUNS)).json()
    assert body["total"] == 2
    assert len(body["items"]) == 2

    body = (await async_client.get(RUNS, params={"status": "deployed"})).json()
    assert [r["branch"] for r in body["items"]] == ["develop"]
    assert (await async_client.get(RUNS, params={"repo": "testuser/testrepo"})).json()["total"] == 1
    assert (await async_client.get(RUNS, params={"limit": 500})).status_code == 422


async def test_get_run_and_404(async_client, pipeline_run):
    r = await async_client.get(f"{RUNS}/{pipeline_run.id}")
    assert r.status_code == 200
    assert r.json()["commit_id"] == pipeline_run.commit_id
    assert (await async_client.get(f"{RUNS}/{uuid.uuid4()}")).status_code == 404
    assert (await async_client.get(f"{RUNS}/not-a-uuid")).status_code == 422


async def test_artifacts(async_client, db_session, pipeline_run):
    db_session.add_all(
        [
            PipelineArtifact(pipeline_run_id=pipeline_run.id, artifact_type="code_analysis", content={"severity": "pass"},
                             raw_output="pylint output"),
            PipelineArtifact(pipeline_run_id=pipeline_run.id, artifact_type="security_scan", content={"highest_severity": "low"}),
        ]
    )
    await db_session.commit()

    listing = (await async_client.get(f"{RUNS}/{pipeline_run.id}/artifacts")).json()
    assert listing["total"] == 2
    assert all("raw_output" not in a for a in listing["items"])

    one = (await async_client.get(f"{RUNS}/{pipeline_run.id}/artifacts/code_analysis")).json()
    assert one["content"] == {"severity": "pass"}
    assert one["raw_output"] == "pylint output"
    assert (await async_client.get(f"{RUNS}/{pipeline_run.id}/artifacts/qa_report")).status_code == 404


@pytest.mark.parametrize(("status", "code"), [("queued", 409), ("deployed", 409), ("failed", 200), ("blocked_security", 200)])
async def test_retry(async_client, db_session, pipeline_run, status, code):
    pipeline_run.status = status
    pipeline_run.error_message = "previous failure"
    await db_session.commit()

    with patch("app.api.routes.pipeline.dispatch_pipeline", return_value="inline") as dispatch:
        r = await async_client.post(f"{RUNS}/{pipeline_run.id}/retry")
    assert r.status_code == code
    if code == 200:
        assert r.json()["status"] == "retrying"
        assert r.json()["executor"] == "inline"
        dispatch.assert_called_once()
        assert str(dispatch.call_args.args[0]) == str(pipeline_run.id)
        await db_session.refresh(pipeline_run)
        assert pipeline_run.status == "queued"
        assert pipeline_run.error_message is None
    else:
        dispatch.assert_not_called()


async def test_cancel(async_client, db_session, pipeline_run):
    r = await async_client.post(f"{RUNS}/{pipeline_run.id}/cancel")
    assert r.json()["cancelled"] is True
    r = await async_client.post(f"{RUNS}/{pipeline_run.id}/cancel")
    assert r.json()["cancelled"] is False
