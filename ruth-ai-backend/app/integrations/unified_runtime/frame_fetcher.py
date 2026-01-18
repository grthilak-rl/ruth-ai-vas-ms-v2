"""
Frame Fetcher - Fetches frames from VAS and converts to base64

Handles:
1. Creating snapshots from VAS devices
2. Downloading snapshot image data
3. Converting to base64 for unified runtime
4. Extracting image metadata (format, dimensions)
"""

import asyncio
import base64
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import httpx
from PIL import Image
import io

from app.core.logging import get_logger
from app.integrations.vas import VASClient
from app.integrations.vas.exceptions import VASError
from app.integrations.vas.models import SnapshotCreateRequest

logger = get_logger(__name__)


@dataclass
class FrameData:
    """Frame data with base64 encoding and metadata."""

    base64_data: str
    format: str  # "jpeg", "png", etc.
    width: int
    height: int
    size_bytes: int

    @property
    def size_kb(self) -> float:
        """Size in kilobytes."""
        return self.size_bytes / 1024

    @property
    def size_mb(self) -> float:
        """Size in megabytes."""
        return self.size_bytes / (1024 * 1024)


class FrameFetcher:
    """
    Fetches frames from VAS and encodes them for unified runtime.

    Usage:
        frame_fetcher = FrameFetcher(vas_client)
        frame_data = await frame_fetcher.fetch_and_encode(device_id)

        # Send to unified runtime
        await runtime_client.submit_inference(
            model_id="fall_detection",
            frame_base64=frame_data.base64_data,
            ...
        )
    """

    def __init__(self, vas_client: VASClient):
        """
        Initialize frame fetcher.

        Args:
            vas_client: Connected VAS client instance
        """
        self.vas_client = vas_client

    async def fetch_and_encode(
        self,
        device_id: Optional[UUID] = None,
        stream_id: Optional[UUID] = None,
        timeout: float = 10.0,
    ) -> FrameData:
        """
        Fetch a frame from VAS and encode as base64.

        Args:
            device_id: Device UUID to capture snapshot from
            stream_id: Stream UUID to capture from (alternative to device_id)
            timeout: Snapshot creation timeout in seconds

        Returns:
            FrameData with base64-encoded image and metadata

        Raises:
            ValueError: If neither device_id nor stream_id provided
            VASError: If snapshot creation or download fails
        """
        if not device_id and not stream_id:
            raise ValueError("Either device_id or stream_id must be provided")

        # Create snapshot via VAS
        logger.debug(
            "Creating snapshot",
            device_id=str(device_id) if device_id else None,
            stream_id=str(stream_id) if stream_id else None,
        )

        snapshot_request = SnapshotCreateRequest(
            label=f"ai_inference_{device_id or stream_id}",
            metadata={"source": "unified_runtime", "purpose": "inference"},
        )

        try:
            # Create snapshot
            if device_id:
                snapshot = await self.vas_client.create_snapshot_from_device(
                    device_id=str(device_id),
                    request=snapshot_request,
                )
            else:
                snapshot = await self.vas_client.create_snapshot(
                    stream_id=str(stream_id),
                    request=snapshot_request,
                )

            logger.debug("Snapshot created", snapshot_id=snapshot.id)

            # Wait for snapshot to be ready
            snapshot = await self.vas_client.wait_for_snapshot_ready(
                snapshot_id=snapshot.id,
                timeout=timeout,
            )

            # Download snapshot image
            image_bytes = await self._download_snapshot_image(snapshot.id)

            # Encode to base64 and extract metadata
            frame_data = self._encode_and_extract_metadata(image_bytes)

            logger.info(
                "Frame fetched and encoded",
                snapshot_id=snapshot.id,
                format=frame_data.format,
                dimensions=f"{frame_data.width}x{frame_data.height}",
                size_kb=f"{frame_data.size_kb:.1f}KB",
            )

            return frame_data

        except VASError as e:
            logger.error("Failed to fetch frame from VAS", error=str(e))
            raise

    async def _download_snapshot_image(self, snapshot_id: str) -> bytes:
        """
        Download snapshot image from VAS.

        Args:
            snapshot_id: Snapshot UUID

        Returns:
            Raw image bytes

        Raises:
            VASError: If download fails
        """
        image_data = bytearray()

        async with self.vas_client.download_snapshot_image(snapshot_id) as response:
            async for chunk in response.aiter_bytes(chunk_size=8192):
                image_data.extend(chunk)

        return bytes(image_data)

    def _encode_and_extract_metadata(self, image_bytes: bytes) -> FrameData:
        """
        Encode image to base64 and extract metadata.

        Args:
            image_bytes: Raw image bytes

        Returns:
            FrameData with base64 encoding and metadata

        Raises:
            ValueError: If image cannot be decoded
        """
        # Open image to extract metadata
        try:
            image = Image.open(io.BytesIO(image_bytes))
            width, height = image.size
            image_format = (image.format or "JPEG").lower()
        except Exception as e:
            logger.error("Failed to decode image", error=str(e))
            raise ValueError(f"Invalid image data: {e}")

        # Encode to base64
        base64_data = base64.b64encode(image_bytes).decode("utf-8")

        return FrameData(
            base64_data=base64_data,
            format=image_format,
            width=width,
            height=height,
            size_bytes=len(image_bytes),
        )

    async def fetch_and_encode_from_reference(
        self,
        frame_reference: str,
        timeout: float = 10.0,
    ) -> FrameData:
        """
        Fetch frame from a reference string (for backward compatibility).

        Supported formats:
        - "vas://device/{device_id}"
        - "vas://stream/{stream_id}"
        - "vas://snapshot/{snapshot_id}"

        Args:
            frame_reference: Frame reference URI
            timeout: Fetch timeout in seconds

        Returns:
            FrameData with base64 encoding

        Raises:
            ValueError: If reference format is invalid
        """
        if not frame_reference.startswith("vas://"):
            raise ValueError(f"Invalid frame reference: {frame_reference}")

        parts = frame_reference.replace("vas://", "").split("/")
        if len(parts) != 2:
            raise ValueError(f"Invalid frame reference format: {frame_reference}")

        ref_type, ref_id = parts

        if ref_type == "device":
            return await self.fetch_and_encode(device_id=UUID(ref_id), timeout=timeout)
        elif ref_type == "stream":
            return await self.fetch_and_encode(stream_id=UUID(ref_id), timeout=timeout)
        elif ref_type == "snapshot":
            # Direct snapshot download
            image_bytes = await self._download_snapshot_image(ref_id)
            return self._encode_and_extract_metadata(image_bytes)
        else:
            raise ValueError(f"Unsupported reference type: {ref_type}")
