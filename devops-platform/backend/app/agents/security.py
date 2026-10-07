from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.base_agent import AgentInput, AgentOutput, BaseAgent
from app.config import get_settings


class VulnerabilityItem(BaseModel):
    id: str = ""
    title: str = ""
    severity: str = "low"
    cve: str | None = None
    description: str = ""
    affected_code: str = ""


class SecuritySchema(BaseModel):
    vulnerabilities: list[VulnerabilityItem] = Field(default_factory=list)
    overall_risk: str = "low"
    passed: bool = True
    scanners: dict | None = None
    analysis_mode: str = "llm"
    highest_severity: str = "none"


_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "none": 0}


def _max_severity(current: str, new: str) -> str:
    return new if _SEVERITY_RANK.get(new, 0) > _SEVERITY_RANK.get(current, 0) else current


def _scanner_issues_to_vulns(issues: list[dict]) -> list[VulnerabilityItem]:
    vulns: list[VulnerabilityItem] = []
    for idx, issue in enumerate(issues):
        sev = str(issue.get("severity", "low")).lower()
        vulns.append(
            VulnerabilityItem(
                id=f"scanner-{issue.get('scanner', 'scan')}-{idx}",
                title=str(issue.get("type") or "security finding"),
                severity=sev,
                cve=issue.get("cve"),
                description=str(issue.get("snippet") or issue.get("fix") or ""),
                affected_code=str(issue.get("file_path") or ""),
            )
        )
    return vulns


class SecurityAgent(BaseAgent):
    stage_key = "security"

    response_model = SecuritySchema

    def run(self, inp: AgentInput) -> AgentOutput:
        settings = get_settings()
        scanner_report: dict = {}
        scanner_vulns: list[VulnerabilityItem] = []
        scanner_blocked = False
        highest = "none"

        repo_path = str(inp.context.get("temp_dir") or "")
        if settings.security_scanners_enabled and repo_path:
            from app.utils.security_scanners import run_security_scanners

            scanner_report = run_security_scanners(repo_path)
            scanner_vulns = _scanner_issues_to_vulns(scanner_report.get("issues") or [])
            scanner_blocked = bool(scanner_report.get("blocked"))
            highest = str(scanner_report.get("highest_severity") or "none")

        snapshot = inp.context.get("code_snapshot") or {}
        files = snapshot.get("files") or []
        brief = "\n".join(f"--- {f.get('path')} ---\n{f.get('content', '')[:3500]}" for f in files[:5])

        llm_vulns: list[VulnerabilityItem] = []
        overall_risk = highest if scanner_vulns else "low"
        passed = not scanner_blocked

        if brief.strip():
            prompt = f"""You are an application security auditor. Scan for security issues. Respond ONLY with JSON:
{{
  "vulnerabilities": [{{"id": string, "title": string, "severity": "low"|"medium"|"high"|"critical", "cve": string|null, "description": string, "affected_code": string}}],
  "overall_risk": "low"|"medium"|"high"|"critical",
  "passed": boolean
}}

Code:
{brief}

Rules: Scanner findings are authoritative — do not downgrade severity reported by bandit/pip-audit."""

            self.write_log(inp.pipeline_id, "DEV", "INFO", "Starting LLM security enrichment")
            data = self._call_llm(prompt, SecuritySchema)
            llm_out = SecuritySchema.model_validate(data)
            llm_vulns = llm_out.vulnerabilities
            if not scanner_vulns:
                overall_risk = llm_out.overall_risk
                passed = llm_out.passed

        merged: list[VulnerabilityItem] = list(scanner_vulns)
        seen = {(v.title, v.affected_code) for v in scanner_vulns}
        for v in llm_vulns:
            key = (v.title, v.affected_code)
            if key not in seen:
                merged.append(v)
                seen.add(key)
                overall_risk = _max_severity(overall_risk, v.severity)

        critical_vuln = any(v.severity in {"critical", "high"} for v in merged)
        if critical_vuln or overall_risk in {"critical", "high"}:
            passed = False

        out = SecuritySchema(
            vulnerabilities=merged,
            overall_risk=overall_risk,
            passed=passed,
            scanners=scanner_report.get("scanners") if scanner_report else None,
            analysis_mode="scanner+llm" if scanner_vulns and llm_vulns else ("scanner" if scanner_vulns else "llm"),
            highest_severity=overall_risk if overall_risk != "low" else highest,
        )

        for v in out.vulnerabilities:
            self.write_log(
                inp.pipeline_id,
                "DEV",
                "WARNING" if v.severity in ("high", "critical") else "INFO",
                f"[{v.severity.upper()}] {v.title}: {v.description[:500]}",
            )

        payload = out.model_dump()
        self.emit_artifact(inp.pipeline_id, "security", payload)

        if not out.passed:
            self.write_log(
                inp.pipeline_id,
                "DEV",
                "BLOCKED",
                "Pipeline blocked by security findings",
                artifact=payload,
            )

        return AgentOutput(
            passed=out.passed,
            summary=scanner_report.get("summary")
            or f"Overall risk {out.overall_risk}, {len(out.vulnerabilities)} findings",
            artifacts={"security": payload},
            next_context={"security": payload},
        )
