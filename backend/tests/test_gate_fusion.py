from core.gate_fusion import correlate_logs_with_gates, fuse_stage_results


def test_fuse_stage_results_fail_on_security() -> None:
    fused = fuse_stage_results(
        code={"severity": "pass"},
        security={"highest_severity": "critical"},
        qa={"passed": True},
        stress={"performance_verdict": "pass"},
    )
    assert fused["verdict"] == "fail"
    assert "security risk critical" in fused["violations"]


def test_fuse_stage_results_warn_on_skipped_qa() -> None:
    fused = fuse_stage_results(
        code={"severity": "pass"},
        security={"highest_severity": "low"},
        qa={"skipped": True},
        stress={"performance_verdict": "pass"},
    )
    assert fused["verdict"] in {"warn", "pass"}
    assert "QA skipped" in fused["warnings"]


def test_correlate_logs_with_gates_adds_hints() -> None:
    gate = fuse_stage_results(code={"severity": "fail"})
    correlation = correlate_logs_with_gates("ERROR deployment crashed\nTraceback...", gate)
    assert correlation["gate_verdict"] == "fail"
    assert correlation["correlation_hints"]
