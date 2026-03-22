import json
import logging
import time
from typing import Any

import httpx

from core.config import Settings

LOGGER = logging.getLogger(__name__)


class LLMClient:
    """Generic LLM API wrapper returning structured JSON.

    - Reads API key and base URL from settings
    - Retries failed requests with exponential backoff
    - Always returns a dict (structured JSON) so callers don't need to parse strings
    """

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.llm_api_key
        self._base_url = settings.llm_base_url
        self._model = settings.llm_model
        self._disabled_after_auth_failure = False

    def generate(self, prompt: str, max_retries: int = 3, backoff_seconds: float = 1.0) -> dict[str, Any]:
        """Call the LLM and return structured JSON.

        Always returns a dict. On error, returns an explanatory fallback dict.
        """
        if not self._api_key:
            LOGGER.debug("LLM_API_KEY not configured — returning deterministic mock output")
            return {"summary": "Mock response (no API key)", "issues": [], "next_action": "continue"}

        if self._disabled_after_auth_failure:
            return {
                "summary": "LLM disabled after authorization failure",
                "issues": [
                    {
                        "type": "llm_auth_error",
                        "severity": "high",
                        "line": "n/a",
                        "fix": "Update LLM_API_KEY with a valid key and restart backend",
                    }
                ],
            }

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.post(self._base_url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()

                # Standard OpenAI-like response with choices -> message -> content
                content = None
                try:
                    content = data["choices"][0]["message"]["content"]
                except Exception:
                    # Some LLMs return 'text' or 'choices' differently
                    content = data.get("content") or data.get("text") or json.dumps(data)

                # Try to parse JSON content; if parsing fails, return wrapped content
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        return parsed
                    return {"summary": "LLM returned non-dict JSON", "value": parsed}
                except Exception:
                    return {"summary": "LLM returned non-JSON content", "value": content}

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status_code = exc.response.status_code if exc.response is not None else None
                LOGGER.warning("LLM call attempt %s failed: %s", attempt, exc)
                if status_code in {401, 403}:
                    self._disabled_after_auth_failure = True
                    break
                if attempt < max_retries:
                    sleep_for = backoff_seconds * (2 ** (attempt - 1))
                    time.sleep(sleep_for)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                LOGGER.warning("LLM call attempt %s failed: %s", attempt, exc)
                if attempt < max_retries:
                    sleep_for = backoff_seconds * (2 ** (attempt - 1))
                    time.sleep(sleep_for)

        LOGGER.exception("LLM request failed after %s attempts: %s", max_retries, last_exc)
        return {
            "summary": "LLM call failed after retries",
            "issues": [
                {
                    "type": "llm_call_error",
                    "severity": "high",
                    "line": "n/a",
                    "fix": "Verify API key, model, network connectivity, and base URL",
                }
            ],
        }
