import json

from core.db import Base, SessionLocal, engine
from models.db_models import WebhookDelivery
from services.webhook_ledger import find_delivery, record_delivery


def test_webhook_delivery_idempotency() -> None:
    WebhookDelivery.__table__.create(bind=engine, checkfirst=True)
    db = SessionLocal()
    try:
        body = {"status": "accepted", "pipeline_id": "run-1"}
        record_delivery(
            db,
            delivery_id="delivery-abc",
            event_type="push",
            repo_full_name="owner/repo",
            pipeline_id="run-1",
            status="accepted",
            response_body=body,
        )
        prior = find_delivery(db, "delivery-abc")
        assert prior is not None
        assert json.loads(prior.response_body or "{}") == body
    finally:
        db.close()
        WebhookDelivery.__table__.drop(bind=engine, checkfirst=True)
