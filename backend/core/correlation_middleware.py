"""HTTP middleware for correlation headers."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.correlation import CORRELATION_HEADER, TRACE_HEADER, resolve_correlation_id, resolve_trace_id


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        cid = resolve_correlation_id(request.headers.get(CORRELATION_HEADER))
        tid = resolve_trace_id(request.headers.get(TRACE_HEADER))
        request.state.correlation_id = cid
        request.state.trace_id = tid
        response = await call_next(request)
        response.headers[CORRELATION_HEADER] = cid
        response.headers[TRACE_HEADER] = tid
        return response
