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
        self._provider = (settings.llm_provider or "openai").strip().lower()
        self._hf_api_url = settings.hf_api_url.rstrip("/")
        try:
            parsed = json.loads(settings.llm_agent_models_json or "{}")
            self._agent_models = parsed if isinstance(parsed, dict) else {}
        except Exception:
            self._agent_models = {}
        self._disabled_after_auth_failure = False

    def _model_for_agent(self, agent_name: str | None) -> str:
        if not agent_name:
            return self._model
        selected = self._agent_models.get(agent_name)
        return str(selected).strip() if selected else self._model

    def _parse_structured_output(self, content: str, raw_fallback: Any | None = None) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
            return {"summary": "LLM returned non-dict JSON", "value": parsed}
        except Exception:
            if raw_fallback is not None:
                return {"summary": "LLM returned non-JSON content", "value": content, "raw": raw_fallback}
            return {"summary": "LLM returned non-JSON content", "value": content}

    def _generate_via_huggingface(
        self,
        prompt: str,
        max_retries: int,
        backoff_seconds: float,
        agent_name: str | None,
    ) -> dict[str, Any]:
        if self._disabled_after_auth_failure:
            return {
                "summary": "LLM disabled after authorization failure",
                "issues": [
                    {
                        "type": "llm_auth_error",
                        "severity": "high",
                        "line": "n/a",
                        "fix": "Update LLM_API_KEY (Hugging Face token) and restart backend",
                    }
                ],
            }

        model = self._model_for_agent(agent_name)
        url = f"{self._hf_api_url}/{model}"
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        payload = {
            "inputs": prompt,
            "parameters": {
                "return_full_text": False,
                "temperature": 0.0,
                "max_new_tokens": 1536,
            },
        }

        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                with httpx.Client(timeout=60.0) as client:
                    resp = client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()

                generated_text = ""
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    generated_text = str(data[0].get("generated_text", ""))
                elif isinstance(data, dict):
                    generated_text = str(data.get("generated_text", "") or data.get("summary_text", "") or data.get("text", ""))

                return self._parse_structured_output(generated_text or json.dumps(data), raw_fallback=data)

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status_code = exc.response.status_code if exc.response is not None else None
                LOGGER.warning("Hugging Face LLM call attempt %s failed: %s", attempt, exc)
                if status_code in {401, 403}:
                    self._disabled_after_auth_failure = True
                    break
                if attempt < max_retries:
                    time.sleep(backoff_seconds * (2 ** (attempt - 1)))
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                LOGGER.warning("Hugging Face LLM call attempt %s failed: %s", attempt, exc)
                if attempt < max_retries:
                    time.sleep(backoff_seconds * (2 ** (attempt - 1)))

        LOGGER.exception("Hugging Face LLM request failed after %s attempts: %s", max_retries, last_exc)
        return {
            "summary": "LLM call failed after retries",
            "issues": [
                {
                    "type": "llm_call_error",
                    "severity": "high",
                    "line": "n/a",
                    "fix": "Verify Hugging Face token, model id, and network connectivity",
                }
            ],
        }

    def generate(
        self,
        prompt: str,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Call the LLM and return structured JSON.

        Always returns a dict. On error, returns an explanatory fallback dict.
        """
        if not self._api_key:
            LOGGER.debug("LLM_API_KEY not configured — returning deterministic mock output")
            return {"summary": "Mock response (no API key)", "issues": [], "next_action": "continue"}

        if self._provider == "huggingface":
            return self._generate_via_huggingface(
                prompt,
                max_retries=max_retries,
                backoff_seconds=backoff_seconds,
                agent_name=agent_name,
            )

        model = self._model_for_agent(agent_name)

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
            "model": model,
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

                return self._parse_structured_output(str(content), raw_fallback=data)

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
