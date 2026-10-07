from app.utils.gate_fusion import fuse_stage_results


def test_fuse_stage_results_stress_p95_fail() -> None:
    fused = fuse_stage_results(
        code={"severity": "pass"},
        security={"highest_severity": "low"},
        qa={"passed": True},
        stress={"p95_ms": 2500, "performance_verdict": "pass"},
    )
    assert fused["verdict"] == "fail"
    assert any("p95" in v for v in fused["violations"])
