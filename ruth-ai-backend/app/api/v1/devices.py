"""Device API endpoints.

From API Contract - Device & Stream APIs:
- GET    /devices
- GET    /devices/{id}
- POST   /devices/{id}/start-inference
- POST   /devices/{id}/stop-inference

These endpoints delegate to DeviceService and StreamService.
No business logic is implemented here.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.deps import DeviceServiceDep, StreamServiceDep, VASClientDep
from app.integrations.vas import VASError, VASNotFoundError
from app.schemas import (
    Device,
    DeviceDetailResponse,
    DeviceListResponse,
    DeviceStreaming,
    ErrorResponse,
    InferenceStartRequest,
    InferenceStartResponse,
    InferenceStopResponse,
)
from app.services import (
    DeviceInactiveError,
    DeviceNotFoundError,
    StreamAlreadyActiveError,
    StreamNotActiveError,
    StreamStartError,
    StreamStopError,
)

router = APIRouter(tags=["Devices"])
logger = get_logger(__name__)


@router.get(
    "/devices",
    response_model=DeviceListResponse,
    status_code=status.HTTP_200_OK,
    summary="List devices",
    description="Returns all registered devices/cameras.",
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def list_devices(
    device_service: DeviceServiceDep,
    stream_service: StreamServiceDep,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 100,
) -> DeviceListResponse:
    """List all devices.

    Args:
        device_service: Injected DeviceService
        stream_service: Injected StreamService
        active_only: Only return active devices
        skip: Pagination offset
        limit: Maximum results

    Returns:
        List of devices with total count (F6-aligned response)
    """
    devices = await device_service.list_devices(
        active_only=active_only,
        skip=skip,
        limit=limit,
    )
    total = await device_service.count_devices(active_only=active_only)

    logger.info("Listing devices", total=total, active_only=active_only)

    # Build F6-aligned response with streaming status for each device
    items = []
    for d in devices:
        # Get stream status for this device
        stream_status = await stream_service.get_stream_status(d.id)

        items.append(
            Device(
                id=d.id,
                name=d.name,
                is_active=d.is_active,
                streaming=DeviceStreaming(
                    active=stream_status["active"],
                    # Use vas_stream_id for frontend video playback (HLS/WebRTC)
                    stream_id=stream_status.get("vas_stream_id"),
                    state=stream_status.get("state"),
                    ai_enabled=stream_status["active"] and stream_status.get("model_id") is not None,
                    model_id=stream_status.get("model_id"),
                ),
            )
        )

    return DeviceListResponse(items=items, total=total)


@router.get(
    "/devices/{device_id}",
    response_model=DeviceDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get device details",
    description="Returns a single device with stream status.",
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_device(
    device_id: UUID,
    device_service: DeviceServiceDep,
    stream_service: StreamServiceDep,
) -> DeviceDetailResponse:
    """Get device by ID with stream status.

    Args:
        device_id: Device UUID
        device_service: Injected DeviceService
        stream_service: Injected StreamService

    Returns:
        Device details with stream status

    Raises:
        HTTPException: 404 if device not found
    """
    try:
        device = await device_service.get_device_by_id(device_id)
    except DeviceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "device_not_found",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    # Get stream status
    stream_status_dict = await stream_service.get_stream_status(device_id)

    logger.info("Retrieved device", device_id=str(device_id))

    return DeviceDetailResponse(
        id=device.id,
        name=device.name,
        description=device.description,
        location=device.location,
        is_active=device.is_active,
        streaming=DeviceStreaming(
            active=stream_status_dict["active"],
            # Use vas_stream_id for frontend video playback (HLS/WebRTC)
            stream_id=stream_status_dict.get("vas_stream_id"),
            state=stream_status_dict.get("state"),
            ai_enabled=stream_status_dict["active"] and stream_status_dict.get("model_id") is not None,
            model_id=stream_status_dict.get("model_id"),
        ),
        last_synced_at=device.last_synced_at,
        created_at=device.created_at,
        updated_at=device.updated_at,
    )


@router.post(
    "/devices/{device_id}/start-inference",
    response_model=InferenceStartResponse,
    status_code=status.HTTP_200_OK,
    summary="Start inference",
    description="Start AI inference on a device stream. Idempotent - returns existing session if already active.",
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
        409: {"model": ErrorResponse, "description": "Stream already active"},
        500: {"model": ErrorResponse, "description": "Failed to start stream"},
        502: {"model": ErrorResponse, "description": "VAS error"},
    },
)
async def start_inference(
    device_id: UUID,
    stream_service: StreamServiceDep,
    request: InferenceStartRequest | None = None,
) -> InferenceStartResponse:
    """Start AI inference on a device.

    This endpoint is idempotent. If a stream is already active for the device,
    it returns the existing session information.

    Args:
        device_id: Device UUID
        stream_service: Injected StreamService
        request: Optional inference configuration

    Returns:
        Stream session information

    Raises:
        HTTPException: 404 if device not found, 500 on VAS failure
    """
    # Use defaults if no request body
    if request is None:
        request = InferenceStartRequest()

    # Check for existing active session (idempotency)
    existing_session = await stream_service.get_active_session_for_device(device_id)
    if existing_session:
        logger.info(
            "Returning existing session (idempotent)",
            device_id=str(device_id),
            session_id=str(existing_session.id),
        )
        return InferenceStartResponse(
            session_id=existing_session.id,
            device_id=existing_session.device_id,
            state=existing_session.state.value,
            model_id=existing_session.model_id,
            started_at=existing_session.started_at,
        )

    try:
        session = await stream_service.start_stream(
            device_id,
            model_id=request.model_id,
            model_version=request.model_version,
            inference_fps=request.inference_fps,
            confidence_threshold=request.confidence_threshold,
        )
    except DeviceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "device_not_found",
                "message": str(e),
                "details": e.details,
            },
        ) from e
    except StreamAlreadyActiveError as e:
        # Should not happen due to idempotency check above, but handle it
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "stream_already_active",
                "message": str(e),
                "details": e.details,
            },
        ) from e
    except StreamStartError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "stream_start_failed",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    logger.info(
        "Started inference",
        device_id=str(device_id),
        session_id=str(session.id),
    )

    return InferenceStartResponse(
        session_id=session.id,
        device_id=session.device_id,
        state=session.state.value,
        model_id=session.model_id,
        started_at=session.started_at,
    )


@router.post(
    "/devices/{device_id}/stop-inference",
    response_model=InferenceStopResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop inference",
    description="Stop AI inference on a device stream. Idempotent - succeeds even if not active.",
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
        500: {"model": ErrorResponse, "description": "Failed to stop stream"},
        502: {"model": ErrorResponse, "description": "VAS error"},
    },
)
async def stop_inference(
    device_id: UUID,
    stream_service: StreamServiceDep,
) -> InferenceStopResponse:
    """Stop AI inference on a device.

    This endpoint is idempotent. If no stream is active for the device,
    it returns success with null session information.

    Args:
        device_id: Device UUID
        stream_service: Injected StreamService

    Returns:
        Stopped session information

    Raises:
        HTTPException: 500 on VAS failure
    """
    # Check for existing active session (idempotency)
    existing_session = await stream_service.get_active_session_for_device(device_id)
    if not existing_session:
        logger.info(
            "No active session to stop (idempotent)",
            device_id=str(device_id),
        )
        # Return idempotent response
        return InferenceStopResponse(
            session_id=None,  # type: ignore
            device_id=device_id,
            state="stopped",
            stopped_at=None,
        )

    try:
        session = await stream_service.stop_stream(device_id)
    except StreamNotActiveError:
        # Idempotent - already stopped
        logger.info(
            "Stream already stopped (idempotent)",
            device_id=str(device_id),
        )
        return InferenceStopResponse(
            session_id=existing_session.id,
            device_id=device_id,
            state="stopped",
            stopped_at=existing_session.stopped_at,
        )
    except StreamStopError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "stream_stop_failed",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    logger.info(
        "Stopped inference",
        device_id=str(device_id),
        session_id=str(session.id),
    )

    return InferenceStopResponse(
        session_id=session.id,
        device_id=session.device_id,
        state=session.state.value,
        stopped_at=session.stopped_at,
    )


# -----------------------------------------------------------------------------
# Stream Endpoints (for WebRTC video playback, separate from AI inference)
# -----------------------------------------------------------------------------


class StreamStartResponseSchema(BaseModel):
    """Response schema for POST /devices/{id}/start-stream.

    Returns VAS stream info needed for WebRTC connection.
    """

    status: str = Field(..., description="Stream status")
    device_id: str = Field(..., description="Ruth AI device UUID")
    room_id: str | None = Field(None, description="MediaSoup room ID")
    transport_id: str | None = Field(None, description="WebRTC transport ID")
    producers: dict | None = Field(None, description="Producer IDs (video, audio)")
    v2_stream_id: str | None = Field(None, description="VAS v2 stream ID")
    reconnect: bool = Field(False, description="Whether this is a reconnection")


class StreamStopResponseSchema(BaseModel):
    """Response schema for POST /devices/{id}/stop-stream."""

    status: str = Field(..., description="Stream status")
    message: str | None = Field(None, description="Status message")


@router.post(
    "/devices/{device_id}/start-stream",
    response_model=StreamStartResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Start video stream",
    description="Start video streaming from a device. Returns VAS stream info for WebRTC.",
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
        502: {"model": ErrorResponse, "description": "VAS error"},
    },
)
async def start_stream(
    device_id: UUID,
    device_service: DeviceServiceDep,
    vas_client: VASClientDep,
) -> StreamStartResponseSchema:
    """Start video streaming from a device.

    This endpoint calls VAS to start the stream and returns the VAS stream info
    needed for WebRTC connection (room_id, transport_id, producers, v2_stream_id).

    Args:
        device_id: Ruth AI device UUID
        device_service: Injected DeviceService
        vas_client: Injected VASClient

    Returns:
        VAS stream info for WebRTC connection

    Raises:
        HTTPException: 404 if device not found, 502 on VAS error
    """
    # Get device to get VAS device ID
    try:
        device = await device_service.get_device_by_id(device_id)
    except DeviceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "device_not_found",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    # Start stream via VAS
    try:
        vas_response = await vas_client.start_stream(device.vas_device_id)
    except VASNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "vas_device_not_found",
                "message": f"VAS device not found: {device.vas_device_id}",
            },
        ) from e
    except VASError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "vas_error",
                "message": str(e),
            },
        ) from e

    logger.info(
        "Started video stream",
        device_id=str(device_id),
        vas_device_id=device.vas_device_id,
        v2_stream_id=vas_response.v2_stream_id,
    )

    return StreamStartResponseSchema(
        status=vas_response.status,
        device_id=str(device_id),
        room_id=vas_response.room_id,
        transport_id=vas_response.transport_id,
        producers=vas_response.producers,
        v2_stream_id=vas_response.v2_stream_id,
        reconnect=vas_response.reconnect,
    )


@router.post(
    "/devices/{device_id}/stop-stream",
    response_model=StreamStopResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Stop video stream",
    description="Stop video streaming from a device.",
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
        502: {"model": ErrorResponse, "description": "VAS error"},
    },
)
async def stop_stream(
    device_id: UUID,
    device_service: DeviceServiceDep,
    vas_client: VASClientDep,
) -> StreamStopResponseSchema:
    """Stop video streaming from a device.

    Args:
        device_id: Ruth AI device UUID
        device_service: Injected DeviceService
        vas_client: Injected VASClient

    Returns:
        Stop status

    Raises:
        HTTPException: 404 if device not found, 502 on VAS error
    """
    # Get device to get VAS device ID
    try:
        device = await device_service.get_device_by_id(device_id)
    except DeviceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "device_not_found",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    # Stop stream via VAS
    try:
        vas_response = await vas_client.stop_stream(device.vas_device_id)
    except VASNotFoundError:
        # Stream already stopped or not started - that's fine
        logger.info(
            "Stream not found in VAS (already stopped)",
            device_id=str(device_id),
        )
        return StreamStopResponseSchema(
            status="stopped",
            message="Stream already stopped",
        )
    except VASError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "vas_error",
                "message": str(e),
            },
        ) from e

    logger.info(
        "Stopped video stream",
        device_id=str(device_id),
        vas_device_id=device.vas_device_id,
    )

    return StreamStopResponseSchema(
        status=vas_response.status,
        message=vas_response.message,
    )
