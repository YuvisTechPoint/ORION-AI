import re
from typing import Any

from app.agents.multimodal.base_multimodal_agent import BaseMultimodalAgent
from app.agents.multimodal.log_analysis_agent import scan_log_lines

TRIAGE_SYSTEM_PROMPT = (
    "You are an on-call SRE responding to a production incident. You have received a mix of screenshots, logs, "
    "metrics, and stack traces from an ongoing production issue. Your job is to triage the incident, identify "
    "root cause, determine blast radius, and provide a step-by-step resolution runbook. Return ONLY valid JSON: "
    '`{"incident_severity": "P1"|"P2"|"P3"|"P4", "incident_type": "outage"|"degradation"|"data_loss"|'
    '"security_breach"|"performance", "affected_services": [string], "root_cause": string, "blast_radius": string, '
    '"time_to_resolve_estimate_minutes": int, "immediate_actions": [{"step": int, "action": string, "command": '
    'string|null, "expected_outcome": string}], "rollback_steps": [string], "post_incident_tasks": [string], '
    '"monitoring_checks": [string], "summary": string, "escalate_to_human": bool, "escalation_reason": string|null}`'
)

ESCALATION_SEVERITIES = {"P1", "P2"}

_TYPE_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("security_breach", "P1", re.compile(r"breach|unauthori[sz]ed access|leaked|exfiltrat|compromised", re.I)),
    ("data_loss", "P1", re.compile(r"data loss|deleted rows|corrupt(ed|ion)|dropped table", re.I)),
    ("outage", "P1", re.compile(r"\b(outage|down|unreachable|502|503|504|connection refused|crashloop)\b", re.I)),
    ("performance", "P3", re.compile(r"slow|latency|p9\d|timeout|high cpu|memory", re.I)),
    ("degradation", "P2", re.compile(r"\b(500|error rate|degraded|partial|intermittent)\b", re.I)),
]


def classify_incident(text: str, error_count: int) -> tuple[str, str]:
    for itype, severity, pattern in _TYPE_PATTERNS:
        if pattern.search(text):
            if itype == "performance" and error_count >= 50:
                return "degradation", "P2"
            return itype, severity
    if error_count >= 50:
        return "degradation", "P2"
    return "performance", "P4" if error_count == 0 else "P3"


class ProductionTriageAgent(BaseMultimodalAgent):
    artifact_type = "production_triage"

    def _heuristic(self) -> dict[str, Any]:
        text = self.combined_text()
        scan = scan_log_lines(text)
        itype, severity = classify_incident(text, len(scan["errors"]))
        escalate = severity in ESCALATION_SEVERITIES
        services = scan["components"] or ["unknown"]
        return {
            "incident_severity": severity,
            "incident_type": itype,
            "affected_services": services,
            "root_cause": scan["errors"][-1] if scan["errors"] else "Insufficient evidence; inspect attached screenshots",
            "blast_radius": f"Services: {', '.join(services)}",
            "time_to_resolve_estimate_minutes": {"P1": 60, "P2": 120, "P3": 240, "P4": 480}[severity],
            "immediate_actions": [
                {"step": 1, "action": "Confirm impact on health endpoints", "command": "curl -fsS http://localhost/health",
                 "expected_outcome": "Identify failing services"},
                {"step": 2, "action": "Inspect recent errors", "command": "journalctl -u orion-api -p err --since '30 min ago'",
                 "expected_outcome": "Locate the failing component"},
                {"step": 3, "action": "Roll back the last deployment if it correlates", "command": None,
                 "expected_outcome": "Service restored to last known good image"},
            ],
            "rollback_steps": ["Redeploy the last known good image", "Verify /health and error rates after rollback"],
            "post_incident_tasks": ["Write a blameless postmortem", "Add alerting for the detected failure mode"],
            "monitoring_checks": ["Error rate", "p95 latency", "Health check status"],
            "summary": f"{severity} {itype}: {len(scan['errors'])} error lines across {len(self.artifacts)} artifact(s).",
            "escalate_to_human": escalate,
            "escalation_reason": f"{severity} {itype} detected" if escalate else None,
        }

    async def execute(self) -> dict[str, Any]:
        result = await self._analyze_json(
            TRIAGE_SYSTEM_PROMPT,
            "Triage this production incident using every attached artifact.",
            self._heuristic(),
            required_key="incident_severity",
            max_tokens=4000,
        )
        if str(result.get("incident_severity", "")).upper() == "P1":
            result["escalate_to_human"] = True
            result.setdefault("escalation_reason", "P1 incident")
        return await self._persist(result)
