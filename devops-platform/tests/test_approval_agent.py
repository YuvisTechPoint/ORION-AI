from app.agents.approval_agent import ApprovalAgent
from app.utils.gate_fusion import fuse_stage_results


def test_approval_fusion_rejects_failed_qa() -> None:
    fused = fuse_stage_results(qa={"verdict": "fail", "passed": False})
    assert fused["verdict"] == "fail"
    assert "QA failed" in fused["violations"]


def test_approval_schema_fields() -> None:
    assert ApprovalAgent.stage_key == "approval"
