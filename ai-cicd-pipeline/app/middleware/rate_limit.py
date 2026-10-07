"""Rate limiting for sensitive ORION endpoints (memory or Redis-backed)."""

from __future__ import annotations

import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.rate_limit_redis import redis_rate_limit_allow, redis_rate_limit_available


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket per client IP for webhook/trigger/multimodal POST routes."""

    PROTECTED_PREFIXES = (
        "/api/v1/webhook/",
        "/api/v1/pipeline/trigger",
        "/api/v1/multimodal/",
    )

    def __init__(
        self,
        app: Any,
        *,
        max_requests: int = 60,
        window_seconds: int = 60,
        redis_url: str | None = None,
        backend: str = "auto",
    ) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.redis_url = (redis_url or "").strip()
        self.backend = (backend or "auto").strip().lower()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _use_redis(self) -> bool:
        if self.backend == "memory":
            return False
        if self.backend == "redis":
            return redis_rate_limit_available(self.redis_url)
        return redis_rate_limit_available(self.redis_url)

    def _client_key(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def _allowed_memory(self, key: str) -> bool:
        now = time.monotonic()
        window = self._hits[key]
        cutoff = now - self.window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self.max_requests:
            return False
        window.append(now)
        return True

    def _allowed(self, key: str) -> bool:
        if self._use_redis():
            verdict = redis_rate_limit_allow(
                self.redis_url,
                key,
                max_requests=self.max_requests,
                window_seconds=self.window_seconds,
                namespace="orion:rate",
            )
            if verdict is not None:
                return verdict
        return self._allowed_memory(key)

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        path = request.url.path
        if request.method == "POST" and any(path.startswith(p) for p in self.PROTECTED_PREFIXES):
            if not self._allowed(self._client_key(request)):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Retry later."},
                    headers={"Retry-After": str(self.window_seconds)},
                )
        return await call_next(request)
