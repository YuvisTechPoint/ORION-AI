import pytest

from core import slo_alert_notifier as notifier


@pytest.mark.asyncio
async def test_notify_slo_alerts_respects_cooldown(monkeypatch) -> None:
    calls: list[str] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            calls.append(json["text"])
            return FakeResponse()

    monkeypatch.setattr(notifier.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    notifier._last_sent.clear()

    alerts = [{"code": "slo_success_low", "severity": "warning", "message": "low success"}]
    sent = await notifier.notify_slo_alerts(
        "test",
        alerts,
        webhook_url="https://hooks.example.test/slack",
        cooldown_seconds=3600,
    )
    assert sent == 1
    sent_again = await notifier.notify_slo_alerts(
        "test",
        alerts,
        webhook_url="https://hooks.example.test/slack",
        cooldown_seconds=3600,
    )
    assert sent_again == 0
    assert len(calls) == 1
