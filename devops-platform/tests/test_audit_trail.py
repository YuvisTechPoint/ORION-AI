from app.services.audit_trail import append_audit_sync, list_audit_events
from app.models import PipelineRun


def test_audit_trail_on_metadata() -> None:
    pipeline = PipelineRun(repo_url="https://github.com/o/r", metadata_json={})
    class FakeSession:
        def commit(self) -> None:
            pass

    append_audit_sync(
        FakeSession(),
        pipeline,
        action="pipeline.retry",
        user={"username": "ops", "roles": ["operator"]},
        outcome="pending",
        details={},
    )
    events = list_audit_events(pipeline)
    assert len(events) == 1
    assert events[0]["action"] == "pipeline.retry"
