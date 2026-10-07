from core.slo_alerts import evaluate_slo_alerts


def test_evaluate_slo_alerts_success_low() -> None:
    alerts = evaluate_slo_alerts(
        {"window_runs": 10, "success_rate": 0.5, "failure_rate": 0.1, "blocked_rate": 0.1}
    )
    assert any(a["code"] == "slo_success_low" for a in alerts)


def test_evaluate_slo_alerts_insufficient_data() -> None:
    assert evaluate_slo_alerts({"window_runs": 1, "success_rate": 0.0}) == []
