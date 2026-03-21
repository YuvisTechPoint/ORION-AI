from __future__ import annotations

import json
from typing import Any

from agents.multimodal.base_multimodal_agent import BaseMultimodalAgent


class PaymentAgent(BaseMultimodalAgent):
    def __init__(self, llm_client: Any, artifacts: list[dict[str, Any]]) -> None:
        super().__init__(llm_client=llm_client, name="payment_multimodal", artifacts=artifacts)

    def execute(self) -> dict[str, Any]:
        system_prompt = (
            "You are a payment systems engineer. Analyze the provided payment data, logs, screenshots, and webhook payloads. "
            "Identify all failed transactions, error patterns, potential fraud indicators, and webhook delivery failures. "
            "Return ONLY valid JSON: "
            "{\"failed_transactions\": [{\"transaction_id\": string, \"amount\": string, \"currency\": string, \"error_code\": string, \"error_message\": string, \"timestamp\": string, \"recommended_retry\": bool}], "
            "\"error_patterns\": [{\"pattern\": string, \"frequency\": int, \"severity\": \"low\"|\"medium\"|\"high\"|\"critical\", \"root_cause\": string, \"fix\": string}], "
            "\"webhook_failures\": [{\"endpoint\": string, \"event_type\": string, \"failure_reason\": string, \"retry_count\": int}], "
            "\"fraud_indicators\": [string], \"total_failed_amount\": string, \"summary\": string, \"immediate_actions\": [string], \"severity\": \"low\"|\"medium\"|\"high\"|\"critical\"}"
        )
        text_prompt = "Analyze uploaded payment artifacts and return the exact schema requested."
        raw, _ = self._call_claude_multimodal(system_prompt=system_prompt, text_prompt=text_prompt, max_tokens=3000)
        parsed = self._parse_json(raw)
        normalized = self._normalize_payment_payload(parsed)
        normalized.setdefault("artifact_type", "payment_analysis")
        return normalized

    def generate_reconciliation_report(self, csv_text: str) -> dict[str, Any]:
        system_prompt = (
            "You are a payment reconciliation expert. Compare expected and actual transaction totals and identify mismatches. "
            "Return ONLY valid JSON with keys: summary, expected_total, actual_total, discrepancy, mismatched_rows, recommendations."
        )
        text_prompt = json.dumps({"csv_data": csv_text[:50000]})
        raw, _ = self._call_claude_multimodal(system_prompt=system_prompt, text_prompt=text_prompt, max_tokens=2000)
        return self._parse_json(raw)

    def _normalize_payment_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed_severity = {"low", "medium", "high", "critical"}

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

        failed_transactions: list[dict[str, Any]] = []
        for item in payload.get("failed_transactions", []):
            if not isinstance(item, dict):
                continue
            failed_transactions.append(
                {
                    "transaction_id": _as_str(item.get("transaction_id"), "unknown"),
                    "amount": _as_str(item.get("amount"), "0"),
                    "currency": _as_str(item.get("currency"), "unknown"),
                    "error_code": _as_str(item.get("error_code"), "unknown"),
                    "error_message": _as_str(item.get("error_message"), "not provided"),
                    "timestamp": _as_str(item.get("timestamp"), "unknown"),
                    "recommended_retry": bool(item.get("recommended_retry", False)),
                }
            )

        error_patterns: list[dict[str, Any]] = []
        for item in payload.get("error_patterns", []):
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity", "low")).lower()
            error_patterns.append(
                {
                    "pattern": _as_str(item.get("pattern"), "unknown"),
                    "frequency": _as_int(item.get("frequency"), 0),
                    "severity": severity if severity in allowed_severity else "low",
                    "root_cause": _as_str(item.get("root_cause"), "unknown"),
                    "fix": _as_str(item.get("fix"), "manual triage required"),
                }
            )

        webhook_failures: list[dict[str, Any]] = []
        for item in payload.get("webhook_failures", []):
            if not isinstance(item, dict):
                continue
            webhook_failures.append(
                {
                    "endpoint": _as_str(item.get("endpoint"), "unknown"),
                    "event_type": _as_str(item.get("event_type"), "unknown"),
                    "failure_reason": _as_str(item.get("failure_reason"), "unknown"),
                    "retry_count": _as_int(item.get("retry_count"), 0),
                }
            )

        fraud_indicators_raw = payload.get("fraud_indicators", [])
        fraud_indicators = [str(item) for item in fraud_indicators_raw] if isinstance(fraud_indicators_raw, list) else []

        immediate_actions_raw = payload.get("immediate_actions", [])
        immediate_actions = [str(item) for item in immediate_actions_raw] if isinstance(immediate_actions_raw, list) else []

        severity = str(payload.get("severity", "low")).lower()
        return {
            "failed_transactions": failed_transactions,
            "error_patterns": error_patterns,
            "webhook_failures": webhook_failures,
            "fraud_indicators": fraud_indicators,
            "total_failed_amount": _as_str(payload.get("total_failed_amount"), "0"),
            "summary": _as_str(payload.get("summary"), "Payment analysis completed"),
            "immediate_actions": immediate_actions,
            "severity": severity if severity in allowed_severity else "low",
        }
