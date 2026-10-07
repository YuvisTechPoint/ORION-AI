from core.slo import compute_pipeline_slo


def test_canonical_slo() -> None:
    slo = compute_pipeline_slo([{"status": "completed"}, {"status": "failed"}])
    assert slo["success_rate"] == 0.5
