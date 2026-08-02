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
from fastapi.responses import Response

from pydantic import BaseModel, Field

from app.core.cache import (
    DEVICES_LIST_CACHE_KEY,
    DEVICES_LIST_CACHE_TTL_SECONDS,
    cache_delete,
    cache_get_json,
    cache_set_json,
)
from app.core.logging import get_logger
from app.deps import DeviceServiceDep, StreamServiceDep, VASClientDep
from app.integrations.vas import VASError, VASNotFoundError
from app.integrations.vas.models import SnapshotCreateRequest, SnapshotSource
from app.schemas import (
    Device,
    DeviceDetailResponse,
    DeviceListResponse,
    DeviceStreaming,
    ErrorResponse,
    InferenceStartRequest,
    InferenceStartResponse,
    InferenceStopResponse,
    ModelConfigUpdateRequest,
    ModelConfigUpdateResponse,
    DeviceNamingUpdateRequest,
    DeviceNamingUpdateResponse,
    ManwayListResponse,
)
from app.services import (
    DeviceInactiveError,
    DeviceNotFoundError,
    StreamAlreadyActiveError,
    StreamNotActiveError,
    StreamStartError,
    StreamSessionNotFoundError,
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
    # Short-TTL Redis cache absorbs the burst of identical concurrent
    # requests this endpoint gets (multiple frontend components mount
    # useDevicesQuery on the same page render). We cache only the
    # default shape — that's what the frontend always sends — so a
    # single cache key suffices; mutations that change the response
    # (start/stop inference, model-config update, device sync) call
    # cache_delete on that key.
    is_cacheable_shape = active_only is True and skip == 0 and limit == 100
    if is_cacheable_shape:
        cached = await cache_get_json(DEVICES_LIST_CACHE_KEY)
        if cached is not None:
            logger.debug("devices list cache hit")
            return DeviceListResponse.model_validate(cached)

    devices = await device_service.list_devices(
        active_only=active_only,
        skip=skip,
        limit=limit,
    )
    total = await device_service.count_devices(active_only=active_only)

    logger.info("Listing devices", total=total, active_only=active_only)

    # Bulk-fetch streaming status: 1 VAS call + 1 DB query for all devices,
    # instead of N VAS calls + N DB queries.
    status_by_device = await stream_service.get_combined_status_bulk(devices)

    items = []
    for d in devices:
        stream_status = status_by_device.get(d.id, {})
        items.append(
            Device(
                id=d.id,
                name=d.name,
                # Mirrored from VAS. May be NULL until the next device sync;
                # clients render `display_name or name`.
                display_name=d.display_name,
                manway=d.manway,
                in_out=d.in_out,
                is_active=d.is_active,
                streaming=DeviceStreaming(
                    # VAS video status
                    video_live=stream_status.get("video_live", False),
                    stream_id=stream_status.get("stream_id"),
                    # AI inference status
                    active=stream_status.get("active", False),
                    state=stream_status.get("state"),
                    ai_enabled=stream_status.get("active", False)
                    and stream_status.get("model_id") is not None,
                    model_id=stream_status.get("model_id"),
                    ai_model_config=stream_status.get("model_config"),
                ),
            )
        )

    response = DeviceListResponse(items=items, total=total)
    if is_cacheable_shape:
        await cache_set_json(
            DEVICES_LIST_CACHE_KEY,
            response.model_dump(mode="json"),
            DEVICES_LIST_CACHE_TTL_SECONDS,
        )
    return response


@router.get(
    "/devices/manways",
    response_model=ManwayListResponse,
    status_code=status.HTTP_200_OK,
    summary="List manway values in use",
    description="Proxies VAS's manway vocabulary for autocomplete.",
    responses={
        502: {"model": ErrorResponse, "description": "VAS unavailable"},
    },
)
async def list_manways(vas_client: VASClientDep) -> ManwayListResponse:
    """List the distinct manway values currently assigned in VAS.

    Read straight from VAS rather than from Ruth's mirrored devices table so
    the vocabulary is current even for cameras named since the last sync.

    A failure here returns an empty list instead of an error: autocomplete is
    a convenience, and losing it must not block an operator from naming a
    camera.

    MUST stay declared above ``GET /devices/{device_id}`` — FastAPI matches in
    declaration order and the path-param route would otherwise capture
    "manways" and fail UUID parsing.
    """
    try:
        return ManwayListResponse(manways=await vas_client.get_manways())
    except VASError as e:
        logger.warning("Failed to fetch manways from VAS", error=str(e))
        return ManwayListResponse(manways=[])


@router.patch(
    "/devices/{device_id}/naming",
    response_model=DeviceNamingUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update device structured naming",
    description=(
        "Write manway / in_out through to VAS, which owns these fields and "
        "derives display_name from them."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
        502: {"model": ErrorResponse, "description": "VAS rejected the update"},
    },
)
async def update_device_naming(
    device_id: UUID,
    request: DeviceNamingUpdateRequest,
    device_service: DeviceServiceDep,
    vas_client: VASClientDep,
) -> DeviceNamingUpdateResponse:
    """Update a device's structured naming, writing through to VAS.

    VAS is the source of truth. The order here matters: VAS is written FIRST
    and Ruth's mirrored row is only updated once VAS confirms. If the VAS call
    fails, Ruth's copy is left untouched, so Ruth can never display a name VAS
    does not have.

    Ruth's row is updated at all (rather than waiting for the next device
    sync) so a browser refresh right after saving shows the new name instead
    of appearing to have lost the edit.

    Args:
        device_id: Ruth AI internal device UUID
        request: Fields to change; omitted fields are left alone in VAS
        device_service: Injected DeviceService
        vas_client: Injected VAS client

    Returns:
        The naming as VAS stored it, including the derived display_name

    Raises:
        HTTPException: 404 if the device is unknown, 502 if VAS rejects it
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

    # Only forward what the caller actually set. Sending the full model would
    # turn "edit manway alone" into "clear in_out", because unset optional
    # fields default to None.
    fields = request.model_dump(include=request.model_fields_set)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "no_fields",
                "message": "Provide at least one of: manway, in_out",
            },
        )

    logger.info(
        "Updating device naming via VAS",
        device_id=str(device_id),
        vas_device_id=device.vas_device_id,
        fields=fields,
    )

    try:
        updated = await vas_client.update_device(device.vas_device_id, fields)
    except VASNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "device_not_found_in_vas",
                "message": f"VAS does not know device {device.vas_device_id}",
            },
        ) from e
    except VASError as e:
        # Ruth's mirrored row is deliberately NOT touched on this path.
        logger.warning(
            "VAS rejected device naming update",
            device_id=str(device_id),
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "vas_update_failed",
                "message": f"VAS rejected the update: {e}",
            },
        ) from e

    # VAS accepted it — mirror the values it actually stored (manway
    # normalized, display_name derived) rather than what was requested.
    display_name = updated.display_name or updated.name
    await device_service.apply_naming_from_vas(
        device_id,
        manway=updated.manway,
        in_out=updated.in_out,
        display_name=display_name,
    )

    # The devices list is Redis-cached; without this the grid would keep
    # serving the old display_name for the whole TTL and the save would look
    # like it silently failed.
    await cache_delete(DEVICES_LIST_CACHE_KEY)

    logger.info(
        "Device naming updated",
        device_id=str(device_id),
        display_name=display_name,
    )

    return DeviceNamingUpdateResponse(
        device_id=device_id,
        name=updated.name,
        manway=updated.manway,
        in_out=updated.in_out,
        display_name=display_name,
    )


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

    # Get combined VAS video + AI inference status
    stream_status_dict = await stream_service.get_combined_status(device_id, device.vas_device_id)

    logger.info("Retrieved device", device_id=str(device_id))

    return DeviceDetailResponse(
        id=device.id,
        name=device.name,
        description=device.description,
        location=device.location,
        is_active=device.is_active,
        streaming=DeviceStreaming(
            # VAS video status
            video_live=stream_status_dict.get("video_live", False),
            stream_id=stream_status_dict.get("stream_id"),
            # AI inference status
            active=stream_status_dict["active"],
            state=stream_status_dict.get("state"),
            ai_enabled=stream_status_dict["active"] and stream_status_dict.get("model_id") is not None,
            model_id=stream_status_dict.get("model_id"),
            ai_model_config=stream_status_dict.get("model_config"),
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
            model_config=request.config,
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

    # Invalidate devices-list cache so the next /devices request reflects
    # the new session immediately instead of waiting on TTL expiry.
    await cache_delete(DEVICES_LIST_CACHE_KEY)

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
    description=(
        "Stop AI inference on a device. Idempotent - succeeds even if not "
        "active. The VAS video stream is left running."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
    },
)
async def stop_inference(
    device_id: UUID,
    stream_service: StreamServiceDep,
) -> InferenceStopResponse:
    """Stop AI inference on a device.

    Inference only: the VAS stream keeps running for other consumers and for
    this operator's own WebRTC video, per the contract spec. No VAS call is
    made and no device state is touched, so nothing here can flip
    ``Device.is_active`` or close a producer.

    This endpoint is idempotent. If no session is active for the device,
    it returns success with null session information.

    Args:
        device_id: Device UUID
        stream_service: Injected StreamService

    Returns:
        Stopped session information
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
        session = await stream_service.stop_inference(device_id)
    except StreamNotActiveError:
        # Idempotent - already stopped
        logger.info(
            "Inference already stopped (idempotent)",
            device_id=str(device_id),
        )
        return InferenceStopResponse(
            session_id=existing_session.id,
            device_id=device_id,
            state="stopped",
            stopped_at=existing_session.stopped_at,
        )

    logger.info(
        "Stopped inference",
        device_id=str(device_id),
        session_id=str(session.id),
    )

    await cache_delete(DEVICES_LIST_CACHE_KEY)

    return InferenceStopResponse(
        session_id=session.id,
        device_id=session.device_id,
        state=session.state.value,
        stopped_at=session.stopped_at,
    )


@router.patch(
    "/devices/{device_id}/model-config",
    response_model=ModelConfigUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update model config",
    description="Update model_config for an active inference session. Use this to update zone definitions for geo-fencing.",
    responses={
        404: {"model": ErrorResponse, "description": "Device or active session not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def update_model_config(
    device_id: UUID,
    stream_service: StreamServiceDep,
    request: ModelConfigUpdateRequest,
) -> ModelConfigUpdateResponse:
    """Update model_config for an active inference session.

    This endpoint updates the model_config for an already-running inference session.
    Use this when the user configures zones for geo-fencing after the model is already active.

    Args:
        device_id: Device UUID
        stream_service: Injected StreamService
        request: Model configuration update request

    Returns:
        Update confirmation

    Raises:
        HTTPException: 404 if device not found or no active session
    """
    try:
        session = await stream_service.update_model_config(
            device_id,
            model_config=request.config,
        )
    except StreamNotActiveError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "no_active_session",
                "message": "No active inference session for this device",
            },
        )

    logger.info(
        "Updated model config",
        device_id=str(device_id),
        session_id=str(session.id),
        model_id=session.model_id,
    )

    await cache_delete(DEVICES_LIST_CACHE_KEY)

    return ModelConfigUpdateResponse(
        session_id=session.id,
        device_id=session.device_id,
        model_id=session.model_id,
        config_updated=True,
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


@router.get(
    "/devices/{device_id}/snapshot",
    status_code=status.HTTP_200_OK,
    summary="Get device snapshot",
    description="Get a live snapshot image from the device for geo-fencing/ROI selection. Automatically starts a VAS stream if needed.",
    responses={
        404: {"model": ErrorResponse, "description": "Device not found"},
        500: {"model": ErrorResponse, "description": "Failed to capture snapshot"},
        502: {"model": ErrorResponse, "description": "VAS error"},
    },
)
async def get_device_snapshot(
    device_id: UUID,
    device_service: DeviceServiceDep,
    stream_service: StreamServiceDep,
    vas_client: VASClientDep,
) -> Response:
    """Get a live snapshot from the device.

    This endpoint creates a snapshot via VAS and returns the image directly.
    Used for ROI/geo-fence selection in the frontend.

    If no stream is active for the device, this endpoint will automatically
    start a temporary VAS stream to capture the snapshot.

    Args:
        device_id: Device UUID
        device_service: Injected DeviceService
        stream_service: Injected StreamService
        vas_client: Injected VAS client

    Returns:
        Binary JPEG image

    Raises:
        HTTPException: 404 if device not found, 502 on VAS error
    """
    # Get device
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

    # Get stream status to get VAS stream_id
    stream_status = await stream_service.get_stream_status(device_id)
    vas_stream_id = stream_status.get("vas_stream_id")

    # Track whether we started a temporary stream
    started_temp_stream = False

    # If no active stream, start a temporary VAS stream for snapshot capture
    if not vas_stream_id:
        logger.info(
            "No active stream, starting temporary VAS stream for snapshot",
            device_id=str(device_id),
            vas_device_id=device.vas_device_id,
        )
        try:
            vas_response = await vas_client.start_stream(device.vas_device_id)
            vas_stream_id = vas_response.v2_stream_id
            started_temp_stream = True
            logger.info(
                "Started temporary VAS stream",
                device_id=str(device_id),
                vas_stream_id=vas_stream_id,
            )
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
                    "error": "vas_stream_start_failed",
                    "message": f"Failed to start VAS stream: {e}",
                },
            ) from e

    # Create snapshot via VAS
    try:
        snapshot_request = SnapshotCreateRequest(
            source=SnapshotSource.LIVE,
            created_by="ruth-ai-frontend",
        )
        snapshot_response = await vas_client.create_snapshot(
            stream_id=vas_stream_id,
            request=snapshot_request,
        )
        snapshot_id = snapshot_response.id

        # Wait for snapshot to be ready (processing can take a few seconds)
        await vas_client.wait_for_snapshot_ready(snapshot_id, timeout=10.0)

        # Get snapshot image
        image_data = await vas_client.get_snapshot_image(snapshot_id)

        logger.info(
            "Fetched snapshot for device",
            device_id=str(device_id),
            snapshot_id=snapshot_id,
        )

        return Response(content=image_data, media_type="image/jpeg")

    except VASNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "stream_not_found",
                "message": str(e),
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
    finally:
        # Clean up temporary stream if we started one
        # Note: We intentionally leave the stream running for subsequent snapshot requests
        # The stream will be stopped when the frontend explicitly stops it or starts inference
        if started_temp_stream:
            logger.info(
                "Temporary VAS stream started for snapshots, leaving active for subsequent requests",
                device_id=str(device_id),
                vas_stream_id=vas_stream_id,
            )


@router.get(
    "/devices/{device_id}/detections/latest",
    status_code=status.HTTP_200_OK,
    summary="Latest AI detections for a device",
    description=(
        "Returns the most recent inference result produced by the backend "
        "inference loop for this device, so browser overlays can render "
        "detections instead of running their own inference."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No detections available"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_latest_detections(device_id: UUID) -> dict:
    """
    Read the newest detection result for a device.

    The backend inference loop is the single source of detections; this is a
    passive read of its in-memory latest-result cache, so polling it costs one
    dict lookup and runs no inference of its own.

    Bounding boxes are only meaningful against the frame they were computed
    on, so ``frame_width`` / ``frame_height`` travel with every result. Model
    coordinate spaces are unchanged from what clients already handle:
    fall_detection reports in 640x640 model space, ppe_detection in frame
    pixels.
    """
    from app.services.inference_loop import get_inference_loop

    loop = get_inference_loop()
    if loop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inference loop is not running",
        )

    detection = loop.get_latest_detection(device_id)
    if detection is None:
        # No active session for this device, or it hasn't produced a first
        # result yet. Not an error — the common case for a camera with no
        # model enabled — so clients treat this as "nothing to draw".
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No detections available for device {device_id}",
        )

    return detection
