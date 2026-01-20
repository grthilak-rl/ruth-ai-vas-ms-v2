"""
Unified Runtime HTTP Client

Async client for communicating with the Unified AI Runtime.
"""

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.core.logging import get_logger
from .schemas import UnifiedInferenceRequest, UnifiedInferenceResponse
from .config import get_unified_runtime_config

logger = get_logger(__name__)


class UnifiedRuntimeError(Exception):
    """Base exception for unified runtime errors."""
    pass


class UnifiedRuntimeConnectionError(UnifiedRuntimeError):
    """Failed to connect to unified runtime."""
    pass


class UnifiedRuntimeTimeoutError(UnifiedRuntimeError):
    """Unified runtime request timed out."""
    pass


class UnifiedRuntimeModelNotFoundError(UnifiedRuntimeError):
    """Model not found in unified runtime."""
    pass


class UnifiedRuntimeInferenceError(UnifiedRuntimeError):
    """Inference failed in unified runtime."""
    pass


class UnifiedRuntimeClient:
    """
    Async HTTP client for Unified AI Runtime.

    Usage:
        async with UnifiedRuntimeClient() as client:
            result = await client.submit_inference(
                model_id="fall_detection",
                frame_base64=frame_data.base64_data,
                ...
            )
    """

    def __init__(
        self,
        runtime_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        """
        Initialize unified runtime client.

        Args:
            runtime_url: Runtime base URL (defaults to config)
            timeout: Request timeout in seconds (defaults to config)
        """
        config = get_unified_runtime_config()

        self.runtime_url = (runtime_url or config.unified_runtime_url).rstrip("/")
        self.timeout = timeout or config.unified_runtime_timeout

        self._client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        """Initialize HTTP client connection."""
        if self._client is not None:
            return

        self._client = httpx.AsyncClient(
            base_url=self.runtime_url,
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
        )

        logger.info("Unified runtime client connected", url=self.runtime_url)

    async def close(self) -> None:
        """Close HTTP client connection."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("Unified runtime client closed")

    async def __aenter__(self) -> "UnifiedRuntimeClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def check_health(self) -> Dict[str, Any]:
        """
        Check unified runtime health.

        Returns:
            Health status dictionary

        Raises:
            UnifiedRuntimeConnectionError: If health check fails
        """
        if not self._client:
            await self.connect()

        try:
            response = await self._client.get("/health")
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            raise UnifiedRuntimeConnectionError(f"Failed to connect: {e}")
        except httpx.TimeoutException as e:
            raise UnifiedRuntimeTimeoutError(f"Health check timed out: {e}")
        except httpx.HTTPStatusError as e:
            raise UnifiedRuntimeError(f"Health check failed: {e}")

    async def get_capabilities(self) -> Dict[str, Any]:
        """
        Get runtime capabilities and available models.

        Returns:
            Capabilities dictionary

        Raises:
            UnifiedRuntimeConnectionError: If request fails
        """
        if not self._client:
            await self.connect()

        try:
            response = await self._client.get("/capabilities")
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            raise UnifiedRuntimeConnectionError(f"Failed to connect: {e}")
        except httpx.TimeoutException as e:
            raise UnifiedRuntimeTimeoutError(f"Capabilities request timed out: {e}")

    async def submit_inference(
        self,
        model_id: str,
        frame_base64: str,
        stream_id: UUID,
        device_id: Optional[UUID] = None,
        model_version: Optional[str] = None,
        frame_format: str = "jpeg",
        frame_width: Optional[int] = None,
        frame_height: Optional[int] = None,
        timestamp: Optional[datetime] = None,
        priority: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> UnifiedInferenceResponse:
        """
        Submit inference request to unified runtime.

        Args:
            model_id: Target model identifier
            frame_base64: Base64-encoded frame data
            stream_id: Source stream UUID
            device_id: Source device UUID
            model_version: Specific model version
            frame_format: Image format (jpeg, png)
            frame_width: Image width in pixels
            frame_height: Image height in pixels
            timestamp: Frame capture timestamp
            priority: Request priority (0-10)
            metadata: Additional metadata
            config: Model-specific configuration (e.g., tank corners, ROI)

        Returns:
            Inference response

        Raises:
            UnifiedRuntimeModelNotFoundError: Model not available
            UnifiedRuntimeInferenceError: Inference failed
        """
        if not self._client:
            await self.connect()

        # Build request
        request = UnifiedInferenceRequest(
            stream_id=stream_id,
            device_id=device_id,
            model_id=model_id,
            model_version=model_version,
            frame_base64=frame_base64,
            frame_format=frame_format,
            frame_width=frame_width,
            frame_height=frame_height,
            timestamp=timestamp or datetime.utcnow(),
            priority=priority,
            metadata=metadata or {},
            config=config,
        )

        logger.debug(
            "Submitting inference request",
            model_id=model_id,
            stream_id=str(stream_id),
            frame_size_kb=len(frame_base64) / 1024,
        )

        try:
            response = await self._client.post(
                "/inference",
                json=request.model_dump(mode="json"),
            )

            if response.status_code == 404:
                raise UnifiedRuntimeModelNotFoundError(
                    f"Model not found: {model_id}:{model_version or 'latest'}"
                )

            if response.status_code == 503:
                raise UnifiedRuntimeError("Unified runtime service unavailable")

            response.raise_for_status()

            # Parse response
            result = UnifiedInferenceResponse.model_validate(response.json())

            logger.info(
                "Inference completed",
                model_id=result.model_id,
                model_version=result.model_version,
                status=result.status,
                inference_time_ms=result.inference_time_ms,
            )

            return result

        except httpx.ConnectError as e:
            raise UnifiedRuntimeConnectionError(f"Failed to connect: {e}")
        except httpx.TimeoutException as e:
            raise UnifiedRuntimeTimeoutError(f"Inference timed out: {e}")
        except ValidationError as e:
            raise UnifiedRuntimeInferenceError(f"Invalid response: {e}")
        except httpx.HTTPStatusError as e:
            raise UnifiedRuntimeInferenceError(f"Inference failed: {e}")
