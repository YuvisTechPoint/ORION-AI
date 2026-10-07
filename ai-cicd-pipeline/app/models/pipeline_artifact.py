import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.pipeline_run import PipelineRun

VALID_ARTIFACT_TYPES = frozenset(
    {
        "diff",
        "metadata",
        "code_analysis",
        "code_review_intelligence",
        "security_scan",
        "qa_report",
        "stress_report",
        "performance_intelligence",
        "deployment_intelligence",
        "observability_intelligence",
        "incident_intelligence",
        "remediation_intelligence",
        "policy_intelligence",
        "enterprise_approval",
        "approval_intelligence",
        "approval",
        "deployment_info",
        "monitoring_alert",
        "monitoring_summary",
        "last_known_good_image",
        "full_scan_combined",
        "change_risk_report",
        "service_graph",
        "sbom",
        "supply_chain_report",
        "secrets_scan",
        "dast_report",
        "container_security_scan",
        "iac_security_scan",
        "test_intelligence",
        "repository_intelligence",
        "release_passport",
        "release_intelligence",
        "developer_ux_intelligence",
        "iam_intelligence",
        "reliability_intelligence",
        "dr_intelligence",
        "knowledge_graph_intelligence",
        "autopilot_intelligence",
        "unified_risk_intelligence",
        "patch_confidence_report",
        "fix_loop_report",
        "contract_test_report",
        "test_generation_report",
        "preview_environment",
        "progressive_delivery",
        "rollback_intelligence",
        "pr_intelligence",
        "evidence_graph",
        "incident_commander_report",
        "rca_report",
        "incident_timeline",
        "postmortem_report",
        "runbook_execution",
        "otel_trace_context",
        "error_budget_report",
        "synthetic_monitoring_report",
        "chaos_report",
        "policy_evaluation",
        "compliance_report",
        "signed_build_report",
        "tenant_rbac_context",
        "cost_report",
        "finops_intelligence",
        "sso_readiness",
        "prompt_injection_scan",
        "agent_registry_snapshot",
        "agent_mesh_snapshot",
        "agent_mesh_intelligence",
        "ai_governance_intelligence",
        "agent_permissions_report",
        "sandbox_policy_report",
        "model_routing_plan",
        "prompt_registry_snapshot",
        "agent_eval_report",
        "ai_cost_optimization",
        "decision_ledger",
        "devops_rag_context",
        "rag_intelligence",
        "agent_memory_snapshot",
        "auto_pr_registry",
        "audit_trail",
        "kubernetes_manifest_scan",
        "cloud_intelligence",
        "service_catalog",
        "service_catalog_intelligence",
        "ci_build_log_analysis",
        "metrics_snapshot_analysis",
        "multimodal_intelligence",
        "payment_analysis",
        "payment_reconciliation",
        "git_log_analysis",
        "log_analysis",
        "github_log_analysis",
        "dockerfile_analysis",
        "production_triage",
    }
)


class PipelineArtifact(Base):
    __tablename__ = "pipeline_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        index=True,
    )
    artifact_type: Mapped[str] = mapped_column(String(50), index=True)
    content: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    pipeline_run: Mapped["PipelineRun"] = relationship(
        "PipelineRun", back_populates="artifacts"
    )

    def __repr__(self) -> str:
        return f"<PipelineArtifact type={self.artifact_type} run={self.pipeline_run_id}>"
