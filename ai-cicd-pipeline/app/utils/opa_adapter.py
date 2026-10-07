"""OPA (Open Policy Agent) adapter — optional policy engine backend."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("opa")


def opa_available() -> bool:
    return bool((settings.opa_url or "").strip())


def evaluate_policies_opa(
    artifacts: dict[str, dict[str, Any]],
    *,
    unsigned_image: bool = False,
    package: str | None = None,
) -> dict[str, Any] | None:
    """POST artifact bundle to OPA. Returns None when OPA is unavailable."""
    url = (settings.opa_url or "").strip().rstrip("/")
    if not url:
        return None

    pkg = (package or settings.opa_policy_package or "orion/pipeline").strip().strip("/")
    endpoint = f"{url}/v1/data/{pkg}"
    payload = {
        "input": {
            "artifacts": artifacts,
            "unsigned_image": unsigned_image,
            "environment": settings.deploy_environment,
        }
    }

    try:
        with httpx.Client(timeout=settings.opa_timeout_seconds) as client:
            resp = client.post(endpoint, json=payload)
        if resp.status_code >= 400:
            logger.warning("OPA returned %s: %s", resp.status_code, resp.text[:300])
            return {
                "passed": False,
                "violations": [{"policy": "opa", "rule": "opa_error", "detail": resp.text[:200]}],
                "policies_evaluated": [pkg],
                "violation_count": 1,
                "engine": "opa",
                "summary": f"OPA evaluation failed (HTTP {resp.status_code}).",
            }
        body = resp.json()
        result = body.get("result") if isinstance(body, dict) else {}
        if not isinstance(result, dict):
            result = {}
        violations = result.get("violations") or []
        if not isinstance(violations, list):
            violations = []
        passed = bool(result.get("allow", result.get("passed", len(violations) == 0)))
        return {
            "passed": passed and len(violations) == 0,
            "violations": violations,
            "policies_evaluated": result.get("policies_evaluated") or [pkg],
            "violation_count": len(violations),
            "engine": "opa",
            "summary": result.get("summary")
            or (
                f"OPA policy passed ({pkg})."
                if passed
                else f"OPA blocked: {len(violations)} violation(s)."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("OPA request failed: %s", exc)
        if settings.opa_fail_closed:
            return {
                "passed": False,
                "violations": [{"policy": "opa", "rule": "opa_unreachable", "detail": str(exc)[:200]}],
                "policies_evaluated": [pkg],
                "violation_count": 1,
                "engine": "opa",
                "summary": "OPA unreachable — policy evaluation failed closed.",
            }
        return None
