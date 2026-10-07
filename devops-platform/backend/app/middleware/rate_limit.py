"""Rate limiting for devops-platform sensitive routes."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    PROTECTED_PREFIXES = ("/webhook/", "/api/pipeline/trigger", "/api/multimodal/")

    def __init__(self, app: Any, *, max_requests: int = 60, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _client_key(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        path = request.url.path
        if request.method == "POST" and any(path.startswith(p) for p in self.PROTECTED_PREFIXES):
            now = time.monotonic()
            key = self._client_key(request)
            window = self._hits[key]
            cutoff = now - self.window_seconds
            while window and window[0] < cutoff:
                window.popleft()
            if len(window) >= self.max_requests:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                    headers={"Retry-After": str(self.window_seconds)},
                )
            window.append(now)
        return await call_next(request)
