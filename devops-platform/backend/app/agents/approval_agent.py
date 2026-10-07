"""LLM + rule-based deployment approval for devops-platform."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.base_agent import AgentInput, AgentOutput, BaseAgent
from app.utils.gate_fusion import fuse_stage_results


class ApprovalSchema(BaseModel):
    decision: str = "approved"
    confidence: float = 0.85
    reason: str = "All gates passed"
    risk_level: str = "low"
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed: bool = True


class ApprovalAgent(BaseAgent):
    stage_key = "approval"
    response_model = ApprovalSchema

    def run(self, inp: AgentInput) -> AgentOutput:
        ctx = inp.context
        fused = fuse_stage_results(
            code=ctx.get("code_analysis") or {},
            security=ctx.get("security") or {},
            qa=ctx.get("qa") or {},
            stress=ctx.get("stress") or {},
        )

        if fused["verdict"] == "fail":
            out = ApprovalSchema(
                decision="rejected",
                confidence=1.0,
                reason="; ".join(fused["violations"]) or "Gate fusion failed",
                risk_level="high",
                violations=fused["violations"],
                warnings=fused["warnings"],
                passed=False,
            )
            self.write_log(inp.pipeline_id, "APPROVAL", "BLOCKED", out.reason)
            return AgentOutput(
                passed=False,
                summary=out.reason,
                artifacts={"approval": out.model_dump(), "gate_fusion": fused},
                next_context={"approval": out.model_dump(), "gate_fusion": fused},
            )

        prompt = f"""You are a principal engineer approving deployment. Gates already passed rule engine.
Return ONLY JSON:
{{"decision":"approved"|"rejected","confidence":0.0-1.0,"reason":string,"risk_level":"low"|"medium"|"high","violations":[],"warnings":[]}}

Gate fusion summary:
{fused}

Reject only if risk_level would be high from subtle concerns in the summary."""

        self.write_log(inp.pipeline_id, "APPROVAL", "INFO", "Running approval agent with gate fusion context")
        try:
            data = self._call_llm(prompt, ApprovalSchema)
            out = ApprovalSchema.model_validate(data)
        except Exception:
            out = ApprovalSchema(
                decision="approved",
                confidence=0.8,
                reason=fused["recommended_action"],
                risk_level="medium" if fused["warnings"] else "low",
                warnings=fused["warnings"],
                passed=True,
            )

        out.violations = fused["violations"]
        if out.warnings is None:
            out.warnings = fused["warnings"]
        out.passed = out.decision.lower() == "approved"
        level = "INFO" if out.passed else "BLOCKED"
        self.write_log(inp.pipeline_id, "APPROVAL", level, out.reason)
        return AgentOutput(
            passed=out.passed,
            summary=out.reason,
            artifacts={"approval": out.model_dump(), "gate_fusion": fused},
            next_context={"approval": out.model_dump(), "gate_fusion": fused},
        )
