"""
Ruth AI Runtime - Backend Integration Client

Provides HTTP client for push-based capability registration and health reporting
from AI Runtime to Ruth AI Backend.

This implements the BackendClientProtocol from reporting.py with actual HTTP calls.

Design Principles:
- Push-based: Runtime pushes state to backend, no polling
- Failure tolerant: Backend outages don't crash runtime
- Idempotent: Safe to retry registration calls
- Observable: All calls logged with correlation IDs

Endpoints Called:
- POST /internal/v1/ai-runtime/register - Register runtime and capabilities
- POST /internal/v1/ai-runtime/health - Push health update
- DELETE /internal/v1/ai-runtime/deregister - Deregister on shutdown

Usage:
    from ai.runtime.backend_client import HTTPBackendClient

    client = HTTPBackendClient(
        backend_url="http://backend:8080",
        runtime_id="runtime-001",
    )

    # Register capabilities
    success = client.register_capabilities(report, correlation_id)

    # Push health update
    success = client.push_health(health_payload, correlation_id)

    # Deregister on shutdown
    client.deregister(correlation_id)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from ai.runtime.reporting import (
    BackendClientProtocol,
    FullCapabilityReport,
    HealthStatus,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass
class BackendClientConfig:
    """Configuration for the backend client."""

    # Backend URL
    backend_url: str = "http://localhost:8080"

    # Timeouts (seconds)
    connect_timeout: float = 5.0
    read_timeout: float = 10.0
    write_timeout: float = 10.0

    # Retry configuration
    max_retries: int = 3
    retry_delay_base: float = 1.0
    retry_delay_max: float = 10.0

    # Authentication
    api_key: Optional[str] = None
    service_token: Optional[str] = None

    # Headers
    extra_headers: Dict[str, str] = field(default_factory=dict)


# =============================================================================
# HTTP BACKEND CLIENT
# =============================================================================


class HTTPBackendClient:
    """
    HTTP client for Backend ↔ AI Runtime communication.

    Implements BackendClientProtocol for push-based capability registration.

    This client handles:
    - Runtime registration with backend
    - Capability announcement
    - Health status pushing
    - Graceful deregistration on shutdown
    """

    # Internal endpoints (not exposed publicly)
    REGISTER_ENDPOINT = "/internal/v1/ai-runtime/register"
    HEALTH_ENDPOINT = "/internal/v1/ai-runtime/health"
    DEREGISTER_ENDPOINT = "/internal/v1/ai-runtime/deregister"

    def __init__(
        self,
        config: Optional[BackendClientConfig] = None,
        runtime_id: Optional[str] = None,
    ):
        """
        Initialize the backend client.

        Args:
            config: Client configuration
            runtime_id: Unique identifier for this runtime instance
        """
        self.config = config or BackendClientConfig()
        self.runtime_id = runtime_id or "unknown"

        # Create HTTP client with timeout configuration
        timeout = httpx.Timeout(
            self.config.read_timeout,  # Default timeout
            connect=self.config.connect_timeout,
            read=self.config.read_timeout,
            write=self.config.write_timeout,
            pool=self.config.connect_timeout,
        )

        self._client = httpx.Client(
            base_url=self.config.backend_url,
            timeout=timeout,
            headers=self._build_headers(),
        )

        # Track registration state
        self._registered = False
        self._last_registration_time: Optional[datetime] = None
        self._last_health_push_time: Optional[datetime] = None

        logger.info(
            "HTTPBackendClient initialized",
            extra={
                "runtime_id": self.runtime_id,
                "backend_url": self.config.backend_url,
            },
        )

    def _build_headers(self) -> Dict[str, str]:
        """Build request headers."""
        headers = {
            "Content-Type": "application/json",
            "X-Runtime-ID": self.runtime_id,
            "User-Agent": f"ruth-ai-runtime/{self.runtime_id}",
        }

        # Add authentication if configured
        if self.config.api_key:
            headers["X-API-Key"] = self.config.api_key
        if self.config.service_token:
            headers["Authorization"] = f"Bearer {self.config.service_token}"

        # Add extra headers
        headers.update(self.config.extra_headers)

        return headers

    def register_capabilities(
        self,
        report: FullCapabilityReport,
        correlation_id: str,
    ) -> bool:
        """
        Push capability report to backend.

        This registers the runtime and announces available models.
        Safe to call multiple times (idempotent).

        Args:
            report: Full capability report with models and capacity
            correlation_id: Correlation ID for tracing

        Returns:
            True if registration successful
        """
        payload = {
            "runtime_id": report.runtime_id,
            "timestamp": report.timestamp.isoformat(),
            "runtime_health": report.runtime_health.value,
            "summary": {
                "total_models": report.total_models,
                "healthy_models": report.healthy_models,
                "total_versions": report.total_versions,
                "ready_versions": report.ready_versions,
            },
            "models": [m.to_dict() for m in report.models],
            "capacity": report.capacity.to_dict(),
        }

        return self._post_with_retry(
            endpoint=self.REGISTER_ENDPOINT,
            payload=payload,
            correlation_id=correlation_id,
            operation="register_capabilities",
        )

    def deregister_version(
        self,
        model_id: str,
        version: str,
        correlation_id: str,
    ) -> bool:
        """
        Notify backend that a version is no longer available.

        Args:
            model_id: Model identifier
            version: Version string
            correlation_id: Correlation ID for tracing

        Returns:
            True if deregistration successful
        """
        payload = {
            "runtime_id": self.runtime_id,
            "model_id": model_id,
            "version": version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": "version_unloaded",
        }

        return self._post_with_retry(
            endpoint=f"{self.DEREGISTER_ENDPOINT}/version",
            payload=payload,
            correlation_id=correlation_id,
            operation="deregister_version",
        )

    def push_health(
        self,
        runtime_health: HealthStatus,
        model_healths: Dict[str, HealthStatus],
        correlation_id: str,
    ) -> bool:
        """
        Push health status update to backend.

        This is a lightweight update that only sends health status,
        not full capabilities.

        Args:
            runtime_health: Overall runtime health status
            model_healths: Health status per model (model_id -> health)
            correlation_id: Correlation ID for tracing

        Returns:
            True if health push successful
        """
        payload = {
            "runtime_id": self.runtime_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "runtime_health": runtime_health.value,
            "models": {
                model_id: health.value
                for model_id, health in model_healths.items()
            },
        }

        success = self._post_with_retry(
            endpoint=self.HEALTH_ENDPOINT,
            payload=payload,
            correlation_id=correlation_id,
            operation="push_health",
        )

        if success:
            self._last_health_push_time = datetime.now(timezone.utc)

        return success

    def deregister(self, correlation_id: str) -> bool:
        """
        Deregister runtime from backend (graceful shutdown).

        Args:
            correlation_id: Correlation ID for tracing

        Returns:
            True if deregistration successful
        """
        payload = {
            "runtime_id": self.runtime_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": "graceful_shutdown",
        }

        success = self._post_with_retry(
            endpoint=self.DEREGISTER_ENDPOINT,
            payload=payload,
            correlation_id=correlation_id,
            operation="deregister",
            max_retries=1,  # Don't retry much on shutdown
        )

        if success:
            self._registered = False

        return success

    def _post_with_retry(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        correlation_id: str,
        operation: str,
        max_retries: Optional[int] = None,
    ) -> bool:
        """
        POST request with retry logic.

        Args:
            endpoint: API endpoint path
            payload: Request payload
            correlation_id: Correlation ID for tracing
            operation: Operation name for logging
            max_retries: Override default max retries

        Returns:
            True if request successful
        """
        retries = max_retries if max_retries is not None else self.config.max_retries
        retry_delay = self.config.retry_delay_base

        for attempt in range(retries + 1):
            try:
                response = self._client.post(
                    endpoint,
                    json=payload,
                    headers={"X-Correlation-ID": correlation_id},
                )

                if response.status_code in (200, 201, 202, 204):
                    logger.info(
                        f"Backend {operation} successful",
                        extra={
                            "correlation_id": correlation_id,
                            "endpoint": endpoint,
                            "status_code": response.status_code,
                            "attempt": attempt + 1,
                        },
                    )

                    if operation == "register_capabilities":
                        self._registered = True
                        self._last_registration_time = datetime.now(timezone.utc)

                    return True

                # Log non-success response
                logger.warning(
                    f"Backend {operation} failed with status {response.status_code}",
                    extra={
                        "correlation_id": correlation_id,
                        "endpoint": endpoint,
                        "status_code": response.status_code,
                        "response_body": response.text[:500],
                        "attempt": attempt + 1,
                    },
                )

                # Don't retry on client errors (4xx)
                if 400 <= response.status_code < 500:
                    return False

            except httpx.ConnectError as e:
                logger.warning(
                    f"Backend {operation} connection error",
                    extra={
                        "correlation_id": correlation_id,
                        "endpoint": endpoint,
                        "error": str(e),
                        "attempt": attempt + 1,
                    },
                )

            except httpx.TimeoutException as e:
                logger.warning(
                    f"Backend {operation} timeout",
                    extra={
                        "correlation_id": correlation_id,
                        "endpoint": endpoint,
                        "error": str(e),
                        "attempt": attempt + 1,
                    },
                )

            except Exception as e:
                logger.error(
                    f"Backend {operation} unexpected error",
                    extra={
                        "correlation_id": correlation_id,
                        "endpoint": endpoint,
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "attempt": attempt + 1,
                    },
                )

            # Retry with backoff
            if attempt < retries:
                logger.debug(
                    f"Retrying {operation} in {retry_delay:.1f}s",
                    extra={"correlation_id": correlation_id},
                )
                time.sleep(retry_delay)
                retry_delay = min(
                    retry_delay * 2,
                    self.config.retry_delay_max,
                )

        logger.error(
            f"Backend {operation} failed after {retries + 1} attempts",
            extra={
                "correlation_id": correlation_id,
                "endpoint": endpoint,
            },
        )
        return False

    def is_registered(self) -> bool:
        """Check if runtime is currently registered with backend."""
        return self._registered

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()
        logger.info("HTTPBackendClient closed")

    def __enter__(self) -> "HTTPBackendClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()


# =============================================================================
# ASYNC CLIENT (for FastAPI integration)
# =============================================================================


class AsyncHTTPBackendClient:
    """
    Async HTTP client for Backend ↔ AI Runtime communication.

    Same interface as HTTPBackendClient but uses async/await.
    Preferred for use within FastAPI async endpoints.
    """

    REGISTER_ENDPOINT = "/internal/v1/ai-runtime/register"
    HEALTH_ENDPOINT = "/internal/v1/ai-runtime/health"
    DEREGISTER_ENDPOINT = "/internal/v1/ai-runtime/deregister"

    def __init__(
        self,
        config: Optional[BackendClientConfig] = None,
        runtime_id: Optional[str] = None,
    ):
        """Initialize the async backend client."""
        self.config = config or BackendClientConfig()
        self.runtime_id = runtime_id or "unknown"

        timeout = httpx.Timeout(
            self.config.read_timeout,  # Default timeout
            connect=self.config.connect_timeout,
            read=self.config.read_timeout,
            write=self.config.write_timeout,
            pool=self.config.connect_timeout,
        )

        self._client = httpx.AsyncClient(
            base_url=self.config.backend_url,
            timeout=timeout,
            headers=self._build_headers(),
        )

        self._registered = False
        self._last_registration_time: Optional[datetime] = None

        logger.info(
            "AsyncHTTPBackendClient initialized",
            extra={
                "runtime_id": self.runtime_id,
                "backend_url": self.config.backend_url,
            },
        )

    def _build_headers(self) -> Dict[str, str]:
        """Build request headers."""
        headers = {
            "Content-Type": "application/json",
            "X-Runtime-ID": self.runtime_id,
            "User-Agent": f"ruth-ai-runtime/{self.runtime_id}",
        }

        if self.config.api_key:
            headers["X-API-Key"] = self.config.api_key
        if self.config.service_token:
            headers["Authorization"] = f"Bearer {self.config.service_token}"

        headers.update(self.config.extra_headers)
        return headers

    async def register_capabilities(
        self,
        report: FullCapabilityReport,
        correlation_id: str,
    ) -> bool:
        """Push capability report to backend (async)."""
        payload = {
            "runtime_id": report.runtime_id,
            "timestamp": report.timestamp.isoformat(),
            "runtime_health": report.runtime_health.value,
            "summary": {
                "total_models": report.total_models,
                "healthy_models": report.healthy_models,
                "total_versions": report.total_versions,
                "ready_versions": report.ready_versions,
            },
            "models": [m.to_dict() for m in report.models],
            "capacity": report.capacity.to_dict(),
        }

        return await self._post_with_retry(
            endpoint=self.REGISTER_ENDPOINT,
            payload=payload,
            correlation_id=correlation_id,
            operation="register_capabilities",
        )

    async def deregister_version(
        self,
        model_id: str,
        version: str,
        correlation_id: str,
    ) -> bool:
        """Notify backend that a version is no longer available (async)."""
        payload = {
            "runtime_id": self.runtime_id,
            "model_id": model_id,
            "version": version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": "version_unloaded",
        }

        return await self._post_with_retry(
            endpoint=f"{self.DEREGISTER_ENDPOINT}/version",
            payload=payload,
            correlation_id=correlation_id,
            operation="deregister_version",
        )

    async def push_health(
        self,
        runtime_health: HealthStatus,
        model_healths: Dict[str, HealthStatus],
        correlation_id: str,
    ) -> bool:
        """Push health status update to backend (async)."""
        payload = {
            "runtime_id": self.runtime_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "runtime_health": runtime_health.value,
            "models": {
                model_id: health.value
                for model_id, health in model_healths.items()
            },
        }

        return await self._post_with_retry(
            endpoint=self.HEALTH_ENDPOINT,
            payload=payload,
            correlation_id=correlation_id,
            operation="push_health",
        )

    async def deregister(self, correlation_id: str) -> bool:
        """Deregister runtime from backend (async)."""
        payload = {
            "runtime_id": self.runtime_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": "graceful_shutdown",
        }

        success = await self._post_with_retry(
            endpoint=self.DEREGISTER_ENDPOINT,
            payload=payload,
            correlation_id=correlation_id,
            operation="deregister",
            max_retries=1,
        )

        if success:
            self._registered = False

        return success

    async def _post_with_retry(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        correlation_id: str,
        operation: str,
        max_retries: Optional[int] = None,
    ) -> bool:
        """POST request with retry logic (async)."""
        import asyncio

        retries = max_retries if max_retries is not None else self.config.max_retries
        retry_delay = self.config.retry_delay_base

        for attempt in range(retries + 1):
            try:
                response = await self._client.post(
                    endpoint,
                    json=payload,
                    headers={"X-Correlation-ID": correlation_id},
                )

                if response.status_code in (200, 201, 202, 204):
                    logger.info(
                        f"Backend {operation} successful",
                        extra={
                            "correlation_id": correlation_id,
                            "endpoint": endpoint,
                            "status_code": response.status_code,
                            "attempt": attempt + 1,
                        },
                    )

                    if operation == "register_capabilities":
                        self._registered = True
                        self._last_registration_time = datetime.now(timezone.utc)

                    return True

                logger.warning(
                    f"Backend {operation} failed with status {response.status_code}",
                    extra={
                        "correlation_id": correlation_id,
                        "endpoint": endpoint,
                        "status_code": response.status_code,
                        "attempt": attempt + 1,
                    },
                )

                if 400 <= response.status_code < 500:
                    return False

            except httpx.ConnectError as e:
                logger.warning(
                    f"Backend {operation} connection error",
                    extra={
                        "correlation_id": correlation_id,
                        "error": str(e),
                        "attempt": attempt + 1,
                    },
                )

            except httpx.TimeoutException as e:
                logger.warning(
                    f"Backend {operation} timeout",
                    extra={
                        "correlation_id": correlation_id,
                        "error": str(e),
                        "attempt": attempt + 1,
                    },
                )

            except Exception as e:
                logger.error(
                    f"Backend {operation} unexpected error",
                    extra={
                        "correlation_id": correlation_id,
                        "error": str(e),
                        "attempt": attempt + 1,
                    },
                )

            if attempt < retries:
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, self.config.retry_delay_max)

        return False

    def is_registered(self) -> bool:
        """Check if runtime is currently registered."""
        return self._registered

    async def close(self) -> None:
        """Close the async HTTP client."""
        await self._client.aclose()
        logger.info("AsyncHTTPBackendClient closed")

    async def __aenter__(self) -> "AsyncHTTPBackendClient":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()


# =============================================================================
# FACTORY FUNCTION
# =============================================================================


def create_backend_client(
    backend_url: str,
    runtime_id: str,
    api_key: Optional[str] = None,
    service_token: Optional[str] = None,
    async_client: bool = False,
) -> HTTPBackendClient | AsyncHTTPBackendClient:
    """
    Create a backend client.

    Args:
        backend_url: Backend service URL
        runtime_id: Unique runtime identifier
        api_key: Optional API key for authentication
        service_token: Optional service token for authentication
        async_client: If True, return AsyncHTTPBackendClient

    Returns:
        HTTPBackendClient or AsyncHTTPBackendClient

    Example:
        # Sync client (for use in threads)
        client = create_backend_client(
            backend_url="http://backend:8080",
            runtime_id="runtime-001",
        )

        # Async client (for FastAPI)
        client = create_backend_client(
            backend_url="http://backend:8080",
            runtime_id="runtime-001",
            async_client=True,
        )
    """
    config = BackendClientConfig(
        backend_url=backend_url,
        api_key=api_key,
        service_token=service_token,
    )

    if async_client:
        return AsyncHTTPBackendClient(config=config, runtime_id=runtime_id)
    else:
        return HTTPBackendClient(config=config, runtime_id=runtime_id)
