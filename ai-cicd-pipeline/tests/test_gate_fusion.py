from app.utils.gate_fusion import correlate_logs_with_gates, fuse_stage_results


def test_orion_gate_fusion_pass() -> None:
    fused = fuse_stage_results(
        code={"severity": "pass"},
        security={"highest_severity": "low"},
        qa={"verdict": "pass"},
        stress={"performance_verdict": "pass"},
    )
    assert fused["verdict"] == "pass"


def test_orion_correlate_logs() -> None:
    gate = fuse_stage_results(code={"severity": "fail"})
    out = correlate_logs_with_gates("ERROR OSError: deployment failed", gate)
    assert out["gate_verdict"] == "fail"
