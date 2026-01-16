"""AI Runtime async client.

Provides async interface for backend to communicate with AI Runtime.
Supports gRPC (primary) and REST (fallback) transports.

The backend uses this client to:
- Register/refresh runtime capabilities
- Submit inference requests
- Check runtime health

This client is transport-agnostic to callers - they don't need to
know whether gRPC or REST is being used.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.core.logging import get_logger

from .exceptions import (
    AIRuntimeCapabilityError,
    AIRuntimeConnectionError,
    AIRuntimeError,
    AIRuntimeInvalidResponseError,
    AIRuntimeModelNotFoundError,
    AIRuntimeOverloadedError,
    AIRuntimeProtocolError,
    AIRuntimeTimeoutError,
    AIRuntimeUnavailableError,
)
from .models import (
    CapabilityRegistrationRequest,
    CapabilityRegistrationResponse,
    HealthCheckResponse,
    InferenceRequest,
    InferenceResponse,
    InferenceStatus,
    RuntimeCapabilities,
    RuntimeHealth,
    RuntimeStatus,
)

logger = get_logger(__name__)


# Default configuration
DEFAULT_INFERENCE_TIMEOUT = 0.1  # 100ms
DEFAULT_HEALTH_TIMEOUT = 1.0  # 1s
DEFAULT_CONNECT_TIMEOUT = 5.0  # 5s
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_BASE = 0.1  # 100ms base
DEFAULT_RETRY_BACKOFF_MAX = 2.0  # 2s max


class AIRuntimeClient:
    """Async client for AI Runtime communication.

    Supports gRPC (primary) and REST (fallback) transports.
    Manages capability caching, retries, and health checks.

    Usage:
        async with AIRuntimeClient(runtime_url) as client:
            # Check health
            health = await client.check_health()

            # Submit inference
            response = await client.submit_inference(
                stream_id=stream_uuid,
                frame_reference="vas://frame/123",
                timestamp=datetime.utcnow()
            )

    Or manually manage lifecycle:
        client = AIRuntimeClient(runtime_url)
        await client.connect()
        try:
            health = await client.check_health()
        finally:
            await client.close()
    """

    def __init__(
        self,
        runtime_url: str,
        *,
        inference_timeout: float = DEFAULT_INFERENCE_TIMEOUT,
        health_timeout: float = DEFAULT_HEALTH_TIMEOUT,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_base: float = DEFAULT_RETRY_BACKOFF_BASE,
        retry_backoff_max: float = DEFAULT_RETRY_BACKOFF_MAX,
        prefer_grpc: bool = True,
    ) -> None:
        """Initialize AI Runtime client.

        Args:
            runtime_url: AI Runtime URL (http:// for REST, grpc:// for gRPC)
            inference_timeout: Timeout for inference requests (seconds)
            health_timeout: Timeout for health checks (seconds)
            connect_timeout: Timeout for initial connection (seconds)
            max_retries: Maximum retry attempts
            retry_backoff_base: Base delay for exponential backoff
            retry_backoff_max: Maximum backoff delay
            prefer_grpc: Prefer gRPC if URL supports both
        """
        self.runtime_url = runtime_url.rstrip("/")
        self.inference_timeout = inference_timeout
        self.health_timeout = health_timeout
        self.connect_timeout = connect_timeout
        self.max_retries = max_retries
        self.retry_backoff_base = retry_backoff_base
        self.retry_backoff_max = retry_backoff_max
        self.prefer_grpc = prefer_grpc

        # Determine transport
        self._use_grpc = prefer_grpc and runtime_url.startswith("grpc://")
        self._http_url = self._normalize_http_url(runtime_url)

        # State
        self._http_client: httpx.AsyncClient | None = None
        self._grpc_channel: Any | None = None  # Type: grpc.aio.Channel
        self._capabilities: RuntimeCapabilities | None = None
        self._capabilities_refreshed_at: float = 0
        self._connected = False

    def _normalize_http_url(self, url: str) -> str:
        """Convert URL to HTTP format for REST fallback."""
        if url.startswith("grpc://"):
            # Convert grpc:// to http://
            return url.replace("grpc://", "http://", 1)
        if url.startswith("grpcs://"):
            return url.replace("grpcs://", "https://", 1)
        return url

    async def connect(self) -> None:
        """Initialize client connections."""
        if self._connected:
            return

        # Initialize HTTP client (always available as fallback)
        self._http_client = httpx.AsyncClient(
            base_url=self._http_url,
            timeout=httpx.Timeout(
                connect=self.connect_timeout,
                read=self.inference_timeout,
                write=self.connect_timeout,
                pool=self.connect_timeout,
            ),
            follow_redirects=True,
        )

        # Initialize gRPC if preferred and available
        if self._use_grpc:
            try:
                await self._init_grpc()
            except Exception as e:
                logger.warning(
                    "gRPC initialization failed, falling back to REST",
                    error=str(e),
                )
                self._use_grpc = False

        self._connected = True
        logger.info(
            "AI Runtime client connected",
            url=self.runtime_url,
            transport="grpc" if self._use_grpc else "rest",
        )

    async def _init_grpc(self) -> None:
        """Initialize gRPC channel.

        Note: This is a placeholder for gRPC support.
        Actual implementation requires generated protobuf stubs.
        """
        # gRPC support will be implemented when protobuf definitions
        # are available from AI Runtime. For now, fall back to REST.
        #
        # Implementation would look like:
        # import grpc
        # from grpc import aio
        # from . import ai_runtime_pb2_grpc
        #
        # self._grpc_channel = aio.insecure_channel(self._grpc_target)
        # self._grpc_stub = ai_runtime_pb2_grpc.AIRuntimeStub(self._grpc_channel)
        raise NotImplementedError("gRPC support requires protobuf definitions")

    async def close(self) -> None:
        """Close client connections and clean up resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        if self._grpc_channel:
            await self._grpc_channel.close()
            self._grpc_channel = None

        self._connected = False
        self._capabilities = None
        logger.info("AI Runtime client closed")

    async def __aenter__(self) -> "AIRuntimeClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------

    async def check_health(self, include_models: bool = True) -> RuntimeHealth:
        """Check AI Runtime health.

        Args:
            include_models: Include per-model health status

        Returns:
            Runtime health status

        Raises:
            AIRuntimeUnavailableError: Runtime not reachable
            AIRuntimeTimeoutError: Health check timed out
        """
        if self._use_grpc:
            return await self._check_health_grpc(include_models)
        return await self._check_health_rest(include_models)

    async def _check_health_grpc(self, include_models: bool) -> RuntimeHealth:
        """Check health via gRPC."""
        # Placeholder for gRPC health check
        # Would use grpc.health.v1 or custom health service
        raise NotImplementedError("gRPC health check not yet implemented")

    async def _check_health_rest(self, include_models: bool) -> RuntimeHealth:
        """Check health via REST API."""
        if not self._http_client:
            raise AIRuntimeConnectionError("Client not connected")

        try:
            response = await self._http_client.get(
                "/health",
                params={"include_models": str(include_models).lower()},
                timeout=self.health_timeout,
            )

            if response.status_code == 503:
                raise AIRuntimeUnavailableError(
                    "AI Runtime service unavailable",
                    endpoint=f"{self._http_url}/health",
                )

            if not response.is_success:
                raise AIRuntimeProtocolError(
                    f"Health check failed with status {response.status_code}",
                    status_code=response.status_code,
                    protocol="rest",
                )

            data = response.json()

            # Handle both wrapped and unwrapped responses
            if "health" in data:
                health_data = data["health"]
            else:
                health_data = data

            return RuntimeHealth.model_validate(health_data)

        except httpx.ConnectError as e:
            raise AIRuntimeConnectionError(
                f"Failed to connect to AI Runtime: {e}",
                endpoint=f"{self._http_url}/health",
            ) from e

        except httpx.TimeoutException as e:
            raise AIRuntimeTimeoutError(
                "Health check timed out",
                timeout_seconds=self.health_timeout,
                operation="health_check",
            ) from e

        except ValidationError as e:
            raise AIRuntimeInvalidResponseError(
                f"Invalid health response: {e}",
                expected="RuntimeHealth",
            ) from e

    async def is_healthy(self) -> bool:
        """Quick health check returning boolean.

        Returns:
            True if runtime is healthy, False otherwise
        """
        try:
            health = await self.check_health(include_models=False)
            return health.is_healthy
        except AIRuntimeError:
            return False

    # -------------------------------------------------------------------------
    # Capability Management
    # -------------------------------------------------------------------------

    async def get_capabilities(
        self,
        force_refresh: bool = False,
        cache_ttl: float = 60.0,
    ) -> RuntimeCapabilities:
        """Get AI Runtime capabilities.

        Capabilities are cached to avoid repeated requests.

        Args:
            force_refresh: Force refresh even if cached
            cache_ttl: Cache time-to-live in seconds

        Returns:
            Runtime capabilities

        Raises:
            AIRuntimeUnavailableError: Runtime not reachable
        """
        now = time.time()

        if (
            not force_refresh
            and self._capabilities
            and (now - self._capabilities_refreshed_at) < cache_ttl
        ):
            return self._capabilities

        # Fetch fresh capabilities
        capabilities = await self._fetch_capabilities()
        self._capabilities = capabilities
        self._capabilities_refreshed_at = now

        return capabilities

    async def _fetch_capabilities(self) -> RuntimeCapabilities:
        """Fetch capabilities from runtime."""
        if self._use_grpc:
            return await self._fetch_capabilities_grpc()
        return await self._fetch_capabilities_rest()

    async def _fetch_capabilities_grpc(self) -> RuntimeCapabilities:
        """Fetch capabilities via gRPC."""
        raise NotImplementedError("gRPC capabilities not yet implemented")

    async def _fetch_capabilities_rest(self) -> RuntimeCapabilities:
        """Fetch capabilities via REST API."""
        if not self._http_client:
            raise AIRuntimeConnectionError("Client not connected")

        try:
            response = await self._http_client.get(
                "/capabilities",
                timeout=self.health_timeout,
            )

            if not response.is_success:
                raise AIRuntimeProtocolError(
                    f"Failed to get capabilities: {response.status_code}",
                    status_code=response.status_code,
                    protocol="rest",
                )

            data = response.json()

            # Handle wrapped response
            if "capabilities" in data:
                cap_data = data["capabilities"]
            else:
                cap_data = data

            capabilities = RuntimeCapabilities.model_validate(cap_data)
            capabilities.registered_at = datetime.now(timezone.utc)

            logger.info(
                "Fetched AI Runtime capabilities",
                runtime_id=capabilities.runtime_id,
                models=[m.model_id for m in capabilities.supported_models],
                hardware=capabilities.hardware_type.value,
            )

            return capabilities

        except httpx.ConnectError as e:
            raise AIRuntimeConnectionError(
                f"Failed to connect to AI Runtime: {e}",
            ) from e

        except httpx.TimeoutException as e:
            raise AIRuntimeTimeoutError(
                "Capabilities request timed out",
                timeout_seconds=self.health_timeout,
                operation="get_capabilities",
            ) from e

        except ValidationError as e:
            raise AIRuntimeInvalidResponseError(
                f"Invalid capabilities response: {e}",
                expected="RuntimeCapabilities",
            ) from e

    async def register_capabilities(
        self,
        capabilities: RuntimeCapabilities,
    ) -> CapabilityRegistrationResponse:
        """Register runtime capabilities with backend.

        This is called BY the runtime TO the backend.
        The backend client exposes this for completeness.

        Args:
            capabilities: Runtime capabilities to register

        Returns:
            Registration response
        """
        if self._use_grpc:
            return await self._register_capabilities_grpc(capabilities)
        return await self._register_capabilities_rest(capabilities)

    async def _register_capabilities_grpc(
        self,
        capabilities: RuntimeCapabilities,
    ) -> CapabilityRegistrationResponse:
        """Register capabilities via gRPC."""
        raise NotImplementedError("gRPC registration not yet implemented")

    async def _register_capabilities_rest(
        self,
        capabilities: RuntimeCapabilities,
    ) -> CapabilityRegistrationResponse:
        """Register capabilities via REST API."""
        if not self._http_client:
            raise AIRuntimeConnectionError("Client not connected")

        request = CapabilityRegistrationRequest(capabilities=capabilities)

        try:
            response = await self._http_client.post(
                "/capabilities/register",
                json=request.model_dump(mode="json"),
                timeout=self.health_timeout,
            )

            if not response.is_success:
                raise AIRuntimeProtocolError(
                    f"Capability registration failed: {response.status_code}",
                    status_code=response.status_code,
                    protocol="rest",
                )

            return CapabilityRegistrationResponse.model_validate(response.json())

        except httpx.ConnectError as e:
            raise AIRuntimeConnectionError(
                f"Failed to connect for registration: {e}",
            ) from e

    def has_model(self, model_id: str, version: str | None = None) -> bool:
        """Check if cached capabilities include a model.

        Args:
            model_id: Model identifier
            version: Specific version (optional)

        Returns:
            True if model is available
        """
        if not self._capabilities:
            return False
        return self._capabilities.has_model(model_id, version)

    # -------------------------------------------------------------------------
    # Inference Submission
    # -------------------------------------------------------------------------

    async def submit_inference(
        self,
        stream_id: UUID,
        frame_reference: str,
        timestamp: datetime,
        *,
        device_id: UUID | None = None,
        model_id: str = "fall_detection",
        model_version: str | None = None,
        priority: int = 0,
        metadata: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> InferenceResponse:
        """Submit inference request to AI Runtime.

        The backend submits frame REFERENCES, not raw frames.
        Frame references are opaque identifiers managed by VAS.

        Args:
            stream_id: Source stream identifier
            frame_reference: Opaque frame reference (VAS-managed)
            timestamp: Frame timestamp
            device_id: Source device identifier (optional)
            model_id: Target model identifier
            model_version: Specific model version (optional)
            priority: Request priority (0-10)
            metadata: Additional metadata
            timeout: Override inference timeout

        Returns:
            Inference response with detections

        Raises:
            AIRuntimeModelNotFoundError: Model not available
            AIRuntimeTimeoutError: Inference timed out
            AIRuntimeOverloadedError: Runtime at capacity
        """
        import uuid

        request = InferenceRequest(
            request_id=uuid.uuid4(),
            stream_id=stream_id,
            device_id=device_id,
            frame_reference=frame_reference,
            timestamp=timestamp,
            model_id=model_id,
            model_version=model_version,
            priority=priority,
            metadata=metadata or {},
        )

        # Check model availability if capabilities cached
        if self._capabilities and not self._capabilities.has_model(model_id):
            available = [m.model_id for m in self._capabilities.supported_models]
            raise AIRuntimeModelNotFoundError(
                model_id=model_id,
                model_version=model_version,
                runtime_id=self._capabilities.runtime_id,
                available_models=available,
            )

        if self._use_grpc:
            return await self._submit_inference_grpc(request, timeout)
        return await self._submit_inference_rest(request, timeout)

    async def _submit_inference_grpc(
        self,
        request: InferenceRequest,
        timeout: float | None,
    ) -> InferenceResponse:
        """Submit inference via gRPC."""
        raise NotImplementedError("gRPC inference not yet implemented")

    async def _submit_inference_rest(
        self,
        request: InferenceRequest,
        timeout: float | None,
    ) -> InferenceResponse:
        """Submit inference via REST API with retry logic."""
        if not self._http_client:
            raise AIRuntimeConnectionError("Client not connected")

        inference_timeout = timeout or self.inference_timeout
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self._http_client.post(
                    "/inference",
                    json=request.model_dump(mode="json"),
                    timeout=inference_timeout,
                )

                # Handle specific error codes
                if response.status_code == 404:
                    raise AIRuntimeModelNotFoundError(
                        model_id=request.model_id,
                        model_version=request.model_version,
                    )

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    raise AIRuntimeOverloadedError(
                        "AI Runtime is overloaded",
                        retry_after_seconds=float(retry_after) if retry_after else None,
                    )

                if response.status_code == 503:
                    raise AIRuntimeUnavailableError(
                        "AI Runtime service unavailable",
                    )

                if not response.is_success:
                    raise AIRuntimeProtocolError(
                        f"Inference failed: {response.status_code}",
                        status_code=response.status_code,
                        protocol="rest",
                    )

                return InferenceResponse.model_validate(response.json())

            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                last_error = AIRuntimeConnectionError(
                    f"Connection failed: {e}",
                    endpoint=f"{self._http_url}/inference",
                )
                if attempt < self.max_retries:
                    delay = min(
                        self.retry_backoff_base * (2**attempt),
                        self.retry_backoff_max,
                    )
                    logger.warning(
                        "Inference connection failed, retrying",
                        attempt=attempt + 1,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                    continue
                raise last_error from e

            except httpx.TimeoutException as e:
                last_error = AIRuntimeTimeoutError(
                    "Inference timed out",
                    timeout_seconds=inference_timeout,
                    operation="submit_inference",
                )
                # Don't retry timeouts by default - inference may have succeeded
                raise last_error from e

            except ValidationError as e:
                raise AIRuntimeInvalidResponseError(
                    f"Invalid inference response: {e}",
                    expected="InferenceResponse",
                ) from e

            except AIRuntimeOverloadedError:
                # Retry overloaded errors with backoff
                if attempt < self.max_retries:
                    delay = min(
                        self.retry_backoff_base * (2**attempt),
                        self.retry_backoff_max,
                    )
                    logger.warning(
                        "AI Runtime overloaded, retrying",
                        attempt=attempt + 1,
                        delay=delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        # Should not reach here, but handle it
        if last_error:
            raise last_error
        raise AIRuntimeError("Inference failed after all retries")

    async def submit_inference_batch(
        self,
        requests: list[InferenceRequest],
        *,
        timeout: float | None = None,
    ) -> list[InferenceResponse]:
        """Submit batch of inference requests.

        Args:
            requests: List of inference requests
            timeout: Override timeout for batch

        Returns:
            List of inference responses

        Note: This is a convenience method that submits requests
        concurrently. For true batching optimization, the AI Runtime
        should expose a batch endpoint.
        """
        if not requests:
            return []

        # Submit all requests concurrently
        tasks = [
            self._submit_inference_rest(req, timeout)
            for req in requests
        ]

        # Gather results, allowing partial failures
        results = await asyncio.gather(*tasks, return_exceptions=True)

        responses: list[InferenceResponse] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # Create failed response for exceptions
                responses.append(
                    InferenceResponse(
                        request_id=requests[i].request_id,
                        stream_id=requests[i].stream_id,
                        device_id=requests[i].device_id,
                        status=InferenceStatus.FAILED,
                        timestamp=requests[i].timestamp,
                        model_id=requests[i].model_id,
                        error=str(result),
                    )
                )
            else:
                responses.append(result)

        return responses

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    async def wait_for_ready(
        self,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
    ) -> RuntimeHealth:
        """Wait for AI Runtime to become ready.

        Args:
            timeout: Maximum wait time in seconds
            poll_interval: Time between health checks

        Returns:
            Runtime health when ready

        Raises:
            AIRuntimeTimeoutError: If timeout reached
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                health = await self.check_health(include_models=False)

                if health.status == RuntimeStatus.READY:
                    return health

                if health.status == RuntimeStatus.ERROR:
                    raise AIRuntimeUnavailableError(
                        f"AI Runtime in error state: {health.error}",
                        runtime_id=health.runtime_id,
                    )

            except AIRuntimeConnectionError:
                # Runtime not yet available, keep waiting
                pass

            await asyncio.sleep(poll_interval)

        raise AIRuntimeTimeoutError(
            "Timeout waiting for AI Runtime to become ready",
            timeout_seconds=timeout,
            operation="wait_for_ready",
        )

    @property
    def runtime_id(self) -> str | None:
        """Get cached runtime ID if available."""
        return self._capabilities.runtime_id if self._capabilities else None

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected
