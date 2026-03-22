from __future__ import annotations

from typing import Any

from app.agents.multimodal.base_multimodal_agent import BaseMultimodalAgent


class PaymentAgent(BaseMultimodalAgent):
    """Multimodal agent for payment system analysis."""

    def __init__(self, anthropic_client: Any, artifacts: list[dict[str, Any]]) -> None:
        super().__init__(anthropic_client=anthropic_client, artifacts=artifacts)

    async def execute(self) -> dict:
        system_prompt = (
            "You are a payment systems engineer and financial data analyst specializing in transaction debugging, reconciliation, fraud detection, and payment gateway integration. "
            "You will receive CSV exports of transaction logs, screenshots of payment dashboards, webhook payloads, and error reports. Analyze everything and return ONLY valid JSON in this exact schema: "
            "{\"analysis_type\": \"payment\", \"severity\": \"low\"|\"medium\"|\"high\"|\"critical\", \"total_transactions_analyzed\": int, \"failed_transactions\": [{\"transaction_id\": string, \"amount\": string, \"currency\": string, \"gateway\": string, \"error_code\": string, \"error_message\": string, \"timestamp\": string, \"customer_id\": string|null, \"recommended_action\": \"retry\"|\"refund\"|\"investigate\"|\"escalate\", \"retry_safe\": bool}], \"error_patterns\": [{\"pattern\": string, \"frequency\": int, \"affected_transactions\": int, \"total_amount_affected\": string, \"severity\": string, \"root_cause\": string, \"fix\": string}], \"webhook_failures\": [{\"endpoint\": string, \"event_type\": string, \"failure_reason\": string, \"retry_count\": int, \"last_attempt\": string, \"fix\": string}], \"fraud_indicators\": [{\"indicator\": string, \"risk_level\": \"low\"|\"medium\"|\"high\", \"affected_transactions\": [string], \"recommended_action\": string}], \"reconciliation_summary\": {\"total_amount_expected\": string, \"total_amount_received\": string, \"discrepancy\": string, \"currency\": string, \"reconciliation_status\": \"balanced\"|\"discrepancy_found\"|\"unable_to_determine\"}, \"gateway_health\": {\"stripe\": string|null, \"razorpay\": string|null, \"paypal\": string|null, \"other\": string|null}, \"immediate_actions\": [string], \"summary\": string, \"total_failed_amount\": string, \"success_rate_percent\": float}"
        )
        user_prompt = (
            "Analyze all provided payment data including CSV transaction logs, error screenshots, and webhook payloads. "
            "Identify all failed transactions, error patterns, fraud indicators, webhook failures, and reconciliation discrepancies. Provide actionable fixes for each issue."
        )
        return await self._analyze(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=4000)
