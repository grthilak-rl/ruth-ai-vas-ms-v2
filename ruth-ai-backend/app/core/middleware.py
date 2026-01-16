"""Request middleware for Ruth AI Backend.

Provides:
- Request ID propagation middleware
- Request logging middleware with metrics
"""

import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger, set_request_id
from app.core.metrics import record_http_request

logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to propagate request IDs.

    Extracts X-Request-ID header from incoming requests or generates
    a new UUID if not present. Sets the request ID in context for
    logging and adds it to the response headers.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Process request with request ID propagation."""
        # Get or generate request ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid.uuid4())

        # Set in context for logging
        set_request_id(request_id)

        # Store on request state for access in routes
        request.state.request_id = request_id

        # Process request
        response = await call_next(request)

        # Add to response headers
        response.headers["X-Request-ID"] = request_id

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log HTTP requests and record metrics.

    Logs request start and completion with timing information.
    Records HTTP request metrics for Prometheus.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Process request with logging and metrics."""
        start_time = time.perf_counter()

        # Log request start
        logger.info(
            "Request started",
            component="api",
            operation="http_request",
            method=request.method,
            path=request.url.path,
            query=str(request.url.query) if request.url.query else None,
        )

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration_seconds = time.perf_counter() - start_time
        duration_ms = int(duration_seconds * 1000)

        # Log request completion
        logger.info(
            "Request completed",
            component="api",
            operation="http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        # Record metrics (safe - never raises)
        record_http_request(
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration=duration_seconds,
        )

        return response
