from __future__ import annotations

from typing import Any

from agents.multimodal.base_multimodal_agent import BaseMultimodalAgent


class ProductionTriageAgent(BaseMultimodalAgent):
    def __init__(self, llm_client: Any, artifacts: list[dict[str, Any]]) -> None:
        super().__init__(llm_client=llm_client, name="production_triage_multimodal", artifacts=artifacts)

    def execute(self) -> dict[str, Any]:
        system_prompt = (
            "You are an on-call SRE responding to a production incident. You have received a mix of screenshots, logs, "
            "metrics, and stack traces from an ongoing production issue. Your job is to triage the incident, identify root cause, "
            "determine blast radius, and provide a step-by-step resolution runbook. Return ONLY valid JSON: "
            "{\"incident_severity\": \"P1\"|\"P2\"|\"P3\"|\"P4\", "
            "\"incident_type\": \"outage\"|\"degradation\"|\"data_loss\"|\"security_breach\"|\"performance\", "
            "\"affected_services\": [string], \"root_cause\": string, \"blast_radius\": string, "
            "\"time_to_resolve_estimate_minutes\": int, \"immediate_actions\": [{\"step\": int, \"action\": string, \"command\": string|null, \"expected_outcome\": string}], "
            "\"rollback_steps\": [string], \"post_incident_tasks\": [string], \"monitoring_checks\": [string], "
            "\"summary\": string, \"escalate_to_human\": bool, \"escalation_reason\": string|null}"
        )
        text_prompt = "Triage the uploaded production incident artifacts and return only the requested JSON schema."
        raw, _ = self._call_claude_multimodal(system_prompt=system_prompt, text_prompt=text_prompt, max_tokens=3000)
        parsed = self._parse_json(raw)
        return self._normalize_triage_payload(parsed)

    def _normalize_triage_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed_severity = {"P1", "P2", "P3", "P4"}
        allowed_types = {"outage", "degradation", "data_loss", "security_breach", "performance"}

        def _as_str(value: Any, default: str = "") -> str:
            return value if isinstance(value, str) else default

        def _as_int(value: Any, default: int = 0) -> int:
            if isinstance(value, bool):
                return default
            if isinstance(value, int):
                return value
            try:
                return int(str(value))
            except Exception:  # noqa: BLE001
                return default

        affected_services_raw = payload.get("affected_services", [])
        affected_services = [str(item) for item in affected_services_raw] if isinstance(affected_services_raw, list) else []

        immediate_actions: list[dict[str, Any]] = []
        immediate_actions_raw = payload.get("immediate_actions", [])
        if isinstance(immediate_actions_raw, list):
            for index, item in enumerate(immediate_actions_raw, start=1):
                if not isinstance(item, dict):
                    continue
                immediate_actions.append(
                    {
                        "step": _as_int(item.get("step"), index),
                        "action": _as_str(item.get("action"), "investigate"),
                        "command": item.get("command") if isinstance(item.get("command"), str) or item.get("command") is None else None,
                        "expected_outcome": _as_str(item.get("expected_outcome"), "issue impact reduced"),
                    }
                )

        rollback_steps_raw = payload.get("rollback_steps", [])
        rollback_steps = [str(item) for item in rollback_steps_raw] if isinstance(rollback_steps_raw, list) else []

        post_incident_tasks_raw = payload.get("post_incident_tasks", [])
        post_incident_tasks = [str(item) for item in post_incident_tasks_raw] if isinstance(post_incident_tasks_raw, list) else []

        monitoring_checks_raw = payload.get("monitoring_checks", [])
        monitoring_checks = [str(item) for item in monitoring_checks_raw] if isinstance(monitoring_checks_raw, list) else []

        incident_severity = _as_str(payload.get("incident_severity"), "P3")
        incident_type = _as_str(payload.get("incident_type"), "degradation")
        escalation_reason = payload.get("escalation_reason")
        if escalation_reason is not None and not isinstance(escalation_reason, str):
            escalation_reason = str(escalation_reason)

        return {
            "incident_severity": incident_severity if incident_severity in allowed_severity else "P3",
            "incident_type": incident_type if incident_type in allowed_types else "degradation",
            "affected_services": affected_services,
            "root_cause": _as_str(payload.get("root_cause"), "unknown"),
            "blast_radius": _as_str(payload.get("blast_radius"), "unknown"),
            "time_to_resolve_estimate_minutes": _as_int(payload.get("time_to_resolve_estimate_minutes"), 60),
            "immediate_actions": immediate_actions,
            "rollback_steps": rollback_steps,
            "post_incident_tasks": post_incident_tasks,
            "monitoring_checks": monitoring_checks,
            "summary": _as_str(payload.get("summary"), "Triage completed"),
            "escalate_to_human": bool(payload.get("escalate_to_human", False)),
            "escalation_reason": escalation_reason,
        }
