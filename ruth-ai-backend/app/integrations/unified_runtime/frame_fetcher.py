"""
Frame Fetcher - Reads frames from VAS's frame tap and converts to base64

Handles:
1. Reading the latest decoded frame from VAS (GET /v2/streams/{id}/frame/latest)
2. Converting to base64 for unified runtime
3. Extracting image metadata (format, dimensions)

The frame comes off the decode VAS already performs to feed mediasoup, so
fetching it costs no RTSP connection and no extra decode. This replaced a
create-snapshot / poll-until-ready / download sequence that opened a fresh
RTSP connection per frame and failed roughly a third of the time under load.
"""

import asyncio
import base64
import os
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import httpx
from PIL import Image
import io

from app.core.logging import get_logger
from app.integrations.vas import VASClient
from app.integrations.vas.exceptions import VASError

logger = get_logger(__name__)

# Reject frames older than this. VAS taps at 2fps by default, so a healthy
# stream is never more than ~500ms stale; this bounds how old a frame we are
# willing to inference on when a pipeline stalls, rather than silently
# reporting detections against a frame from minutes ago.
DEFAULT_MAX_FRAME_AGE_MS = int(os.getenv("RUTH_MAX_FRAME_AGE_MS", "5000"))


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
        max_age_ms: int = DEFAULT_MAX_FRAME_AGE_MS,
    ) -> FrameData:
        """
        Read the latest decoded frame from VAS and encode as base64.

        Args:
            device_id: Device UUID (logging/context only; stream_id is required)
            stream_id: Stream UUID to read the frame tap for
            max_age_ms: Reject frames older than this, in milliseconds

        Returns:
            FrameData with base64-encoded image and metadata

        Raises:
            ValueError: If stream_id is not provided
            VASError: If no sufficiently fresh frame is available
        """
        if not device_id and not stream_id:
            raise ValueError("Either device_id or stream_id must be provided")

        if not stream_id:
            raise ValueError(
                "stream_id is required to read the frame tap. Cannot read frames "
                "from device_id alone — the stream must be started via VAS first."
            )

        try:
            image_bytes, header_width, header_height = (
                await self.vas_client.get_latest_frame(
                    stream_id=str(stream_id),
                    max_age_ms=max_age_ms,
                )
            )

            # Encode to base64 and extract metadata
            frame_data = self._encode_and_extract_metadata(image_bytes)

            # VAS reports the tapped frame's geometry in response headers. It
            # should agree with what we decode here; if it ever doesn't, the
            # decoded values win, because inference coordinates are only
            # meaningful relative to the bytes actually handed to the model.
            if (
                header_width
                and header_height
                and (header_width, header_height)
                != (frame_data.width, frame_data.height)
            ):
                logger.warning(
                    "Frame dimension mismatch between VAS headers and image",
                    stream_id=str(stream_id),
                    header_dimensions=f"{header_width}x{header_height}",
                    decoded_dimensions=f"{frame_data.width}x{frame_data.height}",
                )

            logger.debug(
                "Frame fetched and encoded",
                stream_id=str(stream_id),
                format=frame_data.format,
                dimensions=f"{frame_data.width}x{frame_data.height}",
                size_kb=f"{frame_data.size_kb:.1f}KB",
            )

            return frame_data

        except VASError as e:
            logger.error(
                "Failed to fetch frame from VAS",
                stream_id=str(stream_id),
                error=str(e),
            )
            raise

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
        max_age_ms: int = DEFAULT_MAX_FRAME_AGE_MS,
    ) -> FrameData:
        """
        Fetch frame from a reference string (for backward compatibility).

        Supported formats:
        - "vas://device/{device_id}"
        - "vas://stream/{stream_id}"
        - "vas://snapshot/{snapshot_id}"

        Args:
            frame_reference: Frame reference URI
            max_age_ms: Reject frames older than this, in milliseconds

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
            return await self.fetch_and_encode(
                device_id=UUID(ref_id), max_age_ms=max_age_ms
            )
        elif ref_type == "stream":
            return await self.fetch_and_encode(
                stream_id=UUID(ref_id), max_age_ms=max_age_ms
            )
        elif ref_type == "snapshot":
            # A stored snapshot, not a live frame — this genuinely wants the
            # snapshot API and is unaffected by the move to the frame tap.
            image_bytes = await self.vas_client.get_snapshot_image(ref_id)
            return self._encode_and_extract_metadata(image_bytes)
        else:
            raise ValueError(f"Unsupported reference type: {ref_type}")
