import csv
import io
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.agents.multimodal.base_multimodal_agent import BaseMultimodalAgent, as_text
from app.config import settings

PAYMENT_SYSTEM_PROMPT = (
    "You are a payment systems engineer. Analyze the provided payment data, logs, screenshots, and "
    "webhook payloads. Identify all failed transactions, error patterns, potential fraud indicators, "
    "and webhook delivery failures. Return ONLY valid JSON: "
    '`{"failed_transactions": [{"transaction_id": string, "amount": string, "currency": string, '
    '"error_code": string, "error_message": string, "timestamp": string, "recommended_retry": bool}], '
    '"error_patterns": [{"pattern": string, "frequency": int, "severity": "low"|"medium"|"high"|"critical", '
    '"root_cause": string, "fix": string}], "webhook_failures": [{"endpoint": string, "event_type": string, '
    '"failure_reason": string, "retry_count": int}], "fraud_indicators": [string], "total_failed_amount": string, '
    '"summary": string, "immediate_actions": [string], "severity": "low"|"medium"|"high"|"critical"}`'
)

RECONCILIATION_SYSTEM_PROMPT = (
    "You are a payments reconciliation analyst. Compare expected versus actual (settled/captured) amounts "
    "in the provided transaction data. Return ONLY valid JSON: "
    '{"total_expected": string, "total_actual": string, "discrepancy": string, "currency": string, '
    '"status": "balanced"|"discrepancy_found"|"unable_to_determine", '
    '"mismatched_transactions": [{"transaction_id": string, "expected": string, "actual": string, "difference": string}], '
    '"summary": string}'
)

_FAILED_STATES = {"failed", "failure", "declined", "error", "rejected", "chargeback", "disputed"}
_RETRYABLE_CODES = {"timeout", "processing_error", "rate_limit", "network_error", "gateway_timeout", "try_again_later"}


def _col(row: dict[str, str], *names: str) -> str:
    lowered = {k.lower().strip(): v for k, v in row.items() if k}
    for name in names:
        if name in lowered and lowered[name] not in (None, ""):
            return str(lowered[name]).strip()
    return ""


def _amount(value: str) -> Decimal:
    try:
        return Decimal(re.sub(r"[^\d.\-]", "", value) or "0")
    except InvalidOperation:
        return Decimal("0")


def parse_transactions(text: str) -> list[dict[str, str]]:
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or len(reader.fieldnames) < 2:
            return []
        return [dict(r) for r in reader]
    except csv.Error:
        return []


class PaymentAgent(BaseMultimodalAgent):
    artifact_type = "payment_analysis"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.agent_model = settings.multimodal_payment_model

    def _rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for art in self.artifacts:
            if art.get("type") == "csv" or str(art.get("filename", "")).lower().endswith(".csv"):
                rows.extend(parse_transactions(as_text(art.get("content", ""))))
        return rows

    def _heuristic(self) -> dict[str, Any]:
        rows = self._rows()
        failed = []
        patterns: dict[str, int] = {}
        total_failed = Decimal("0")
        currency = ""
        for row in rows:
            status = _col(row, "status", "state", "outcome").lower()
            if status not in _FAILED_STATES:
                continue
            code = _col(row, "error_code", "failure_code", "decline_code", "code") or "unknown"
            amount = _col(row, "amount", "value", "total")
            currency = currency or _col(row, "currency")
            total_failed += _amount(amount)
            patterns[code] = patterns.get(code, 0) + 1
            failed.append(
                {
                    "transaction_id": _col(row, "transaction_id", "id", "txn_id", "payment_id"),
                    "amount": amount,
                    "currency": _col(row, "currency"),
                    "error_code": code,
                    "error_message": _col(row, "error_message", "failure_message", "message", "reason"),
                    "timestamp": _col(row, "timestamp", "created_at", "date", "created"),
                    "recommended_retry": code.lower() in _RETRYABLE_CODES,
                }
            )
        text = self.combined_text().lower()
        webhook_failures = []
        if "webhook" in text and any(k in text for k in ("failed", "timeout", "500", "retry")):
            webhook_failures.append(
                {"endpoint": "unknown", "event_type": "unknown", "failure_reason": "webhook failure mentioned in logs", "retry_count": 0}
            )
        failure_rate = len(failed) / len(rows) if rows else 0.0
        severity = "critical" if failure_rate > 0.25 else "high" if failure_rate > 0.1 else "medium" if failed else "low"
        return {
            "failed_transactions": failed[:200],
            "error_patterns": [
                {
                    "pattern": code,
                    "frequency": count,
                    "severity": "high" if count >= 5 else "medium",
                    "root_cause": "Determined from gateway error code",
                    "fix": "Retry with backoff" if code.lower() in _RETRYABLE_CODES else "Investigate with the payment gateway",
                }
                for code, count in sorted(patterns.items(), key=lambda kv: -kv[1])
            ],
            "webhook_failures": webhook_failures,
            "fraud_indicators": [],
            "total_failed_amount": f"{total_failed} {currency}".strip(),
            "summary": f"{len(failed)} of {len(rows)} transactions failed ({failure_rate:.1%}).",
            "immediate_actions": ["Retry retryable failures with exponential backoff"] if failed else [],
            "severity": severity,
        }

    async def execute(self) -> dict[str, Any]:
        result = await self._analyze_json(
            PAYMENT_SYSTEM_PROMPT,
            "Analyze all provided payment data and return the JSON report.",
            self._heuristic(),
            required_key="failed_transactions",
            max_tokens=4000,
        )
        return await self._persist(result)

    async def generate_reconciliation_report(self) -> dict[str, Any]:
        rows = self._rows()
        expected = actual = Decimal("0")
        mismatched = []
        actual_cols = {"actual_amount", "settled_amount", "captured_amount", "actual"}
        has_actual = bool(rows) and any(k and k.lower().strip() in actual_cols for k in rows[0])
        for row in rows if has_actual else []:
            exp = _amount(_col(row, "expected_amount", "amount", "expected"))
            act = _amount(_col(row, "actual_amount", "settled_amount", "captured_amount", "actual") or "0")
            expected += exp
            actual += act
            if exp != act:
                mismatched.append(
                    {
                        "transaction_id": _col(row, "transaction_id", "id"),
                        "expected": str(exp),
                        "actual": str(act),
                        "difference": str(exp - act),
                    }
                )
        fallback = {
            "total_expected": str(expected),
            "total_actual": str(actual),
            "discrepancy": str(expected - actual),
            "currency": _col(rows[0], "currency") if rows else "",
            "status": "unable_to_determine" if not has_actual else ("balanced" if expected == actual else "discrepancy_found"),
            "mismatched_transactions": mismatched[:200],
            "summary": (
                f"Reconciled {len(rows)} transactions; discrepancy {expected - actual}."
                if has_actual
                else "No actual/settled amount column found; cannot reconcile."
            ),
        }
        result = await self._analyze_json(
            RECONCILIATION_SYSTEM_PROMPT,
            "Produce a reconciliation summary comparing expected vs actual amounts.",
            fallback,
            required_key="status",
        )
        return await self._persist(result, artifact_type="payment_reconciliation")
