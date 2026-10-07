from app.services.slo import compute_pipeline_slo


def test_compute_pipeline_slo_empty() -> None:
    slo = compute_pipeline_slo([])
    assert slo["window_runs"] == 0
    assert slo["success_rate"] == 0.0


class _Run:
    def __init__(self, status: str) -> None:
        self.status = status
        self.created_at = None
        self.completed_at = None


def test_compute_pipeline_slo_rates() -> None:
    runs = [_Run("deployed"), _Run("failed"), _Run("blocked_code")]
    slo = compute_pipeline_slo(runs)
    assert slo["window_runs"] == 3
    assert slo["success_rate"] == round(1 / 3, 3)
