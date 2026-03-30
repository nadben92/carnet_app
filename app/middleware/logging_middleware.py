"""Middleware HTTP : latence, statut, identifiant de requête."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

access_logger = logging.getLogger("app.http")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        req_id = str(uuid.uuid4())[:8]
        start = time.perf_counter()
        try:
            response = await call_next(request)
            ms = (time.perf_counter() - start) * 1000
            access_logger.info(
                "%s %s %s -> %s %.1fms",
                req_id,
                request.method,
                request.url.path,
                response.status_code,
                ms,
            )
            response.headers["X-Request-ID"] = req_id
            return response
        except Exception:
            ms = (time.perf_counter() - start) * 1000
            access_logger.exception("request_error after %.1fms %s %s", ms, request.method, request.url.path)
            raise
