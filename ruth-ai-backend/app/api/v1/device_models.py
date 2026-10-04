"""Several models per camera.

    GET    /devices/{device_id}/models               models running on the camera
    POST   /devices/{device_id}/models               add one (starts inference if none)
    PATCH  /devices/{device_id}/models/{model_id}    change its config / fps_override
    DELETE /devices/{device_id}/models/{model_id}    remove it (last one = stop inference)
    GET    /devices/{device_id}/detections           newest result per model

The existing single-model endpoints (start-inference, stop-inference,
model-config, detections/latest) are unchanged. Like them, these routes carry
no authentication.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.core.cache import DEVICES_LIST_CACHE_KEY, cache_delete
from app.deps import DBSession, StreamServiceDep
from app.services.exceptions import (
    DeviceNotFoundError,
    StreamAlreadyActiveError,
    StreamStartError,
)
from app.services.model_rates import MAX_OVERRIDE_FPS, MIN_OVERRIDE_FPS, desired_fps
from app.services.session_models import (
    SessionModelError,
    SessionModelsService,
    session_entries,
)

router = APIRouter(tags=["Device Models"])


class ModelEntryIn(BaseModel):
    model_id: str = Field(min_length=1, max_length=100)
    model_version: str | None = Field(default=None, max_length=50)
    config: dict[str, Any] | None = None
    fps_override: float | None = Field(default=None, ge=MIN_OVERRIDE_FPS, le=MAX_OVERRIDE_FPS)


class ModelEntryUpdate(BaseModel):
    """Only the fields present in the request are changed; send
    "fps_override": null to clear an override."""

    config: dict[str, Any] | None = None
    fps_override: float | None = Field(default=None, ge=MIN_OVERRIDE_FPS, le=MAX_OVERRIDE_FPS)


class ModelEntryOut(BaseModel):
    model_id: str
    model_version: str | None = None
    config: dict[str, Any] | None = None
    fps_override: float | None = None
    target_fps: float = Field(description="Rate asked for before the GPU budget applies")


class DeviceModelsOut(BaseModel):
    device_id: UUID
    session_id: UUID | None
    models_revision: int
    models: list[ModelEntryOut]


class DetectionOut(BaseModel):
    model_id: str
    model_version: str | None = None
    result: dict[str, Any]
    frame_width: int | None = None
    frame_height: int | None = None
    age_ms: int


class DeviceDetectionsOut(BaseModel):
    device_id: UUID
    detections: list[DetectionOut]


def _out(device_id: UUID, session) -> DeviceModelsOut:
    from app.services.inference_loop import TARGET_FPS

    return DeviceModelsOut(
        device_id=device_id,
        session_id=session.id if session else None,
        models_revision=session.models_revision if session else 0,
        models=[
            ModelEntryOut(**{k: e.get(k) for k in ("model_id", "model_version", "config", "fps_override")},
                          target_fps=desired_fps(e, TARGET_FPS))
            for e in session_entries(session)
        ],
    )


def _http(exc: SessionModelError) -> HTTPException:
    return HTTPException(exc.status, detail={"error": exc.code, "message": exc.message})


@router.get("/devices/{device_id}/models", response_model=DeviceModelsOut, summary="Models on a camera")
async def list_models(device_id: UUID, streams: StreamServiceDep, db: DBSession) -> DeviceModelsOut:
    session = await SessionModelsService(streams, db).get(device_id)
    return _out(device_id, session)


@router.post(
    "/devices/{device_id}/models",
    response_model=DeviceModelsOut,
    summary="Add a model to a camera",
    responses={200: {"description": "Already running"}, 201: {"description": "Added"}},
)
async def add_model(
    device_id: UUID,
    body: ModelEntryIn,
    response: Response,
    streams: StreamServiceDep,
    db: DBSession,
) -> DeviceModelsOut:
    service = SessionModelsService(streams, db)
    try:
        outcome = await service.add(device_id, body.model_dump())
    except SessionModelError as exc:
        raise _http(exc)
    except DeviceNotFoundError as exc:
        raise HTTPException(404, detail={"error": "device_not_found", "message": str(exc)})
    except StreamAlreadyActiveError as exc:
        raise HTTPException(409, detail={"error": "stream_already_active", "message": str(exc)})
    except StreamStartError as exc:
        raise HTTPException(502, detail={"error": "stream_start_failed", "message": str(exc)})
    await db.commit()
    await cache_delete(DEVICES_LIST_CACHE_KEY)
    response.status_code = status.HTTP_201_CREATED if outcome.changed else status.HTTP_200_OK
    return _out(device_id, outcome.session)


@router.patch(
    "/devices/{device_id}/models/{model_id}",
    response_model=DeviceModelsOut,
    summary="Change one model's config or fps_override (takes effect immediately)",
)
async def update_model(
    device_id: UUID,
    model_id: str,
    body: ModelEntryUpdate,
    streams: StreamServiceDep,
    db: DBSession,
) -> DeviceModelsOut:
    changes = body.model_dump(include=body.model_fields_set)
    if not changes:
        raise HTTPException(422, detail={"error": "nothing_to_change", "message": "send config and/or fps_override"})
    try:
        session = await SessionModelsService(streams, db).update(device_id, model_id, changes)
    except SessionModelError as exc:
        raise _http(exc)
    await db.commit()
    await cache_delete(DEVICES_LIST_CACHE_KEY)
    return _out(device_id, session)


@router.delete(
    "/devices/{device_id}/models/{model_id}",
    response_model=DeviceModelsOut,
    summary="Remove one model from a camera (the last one stops inference)",
)
async def remove_model(
    device_id: UUID,
    model_id: str,
    streams: StreamServiceDep,
    db: DBSession,
) -> DeviceModelsOut:
    try:
        session = await SessionModelsService(streams, db).remove(device_id, model_id)
    except SessionModelError as exc:
        raise _http(exc)
    await db.commit()
    await cache_delete(DEVICES_LIST_CACHE_KEY)
    return _out(device_id, session)


@router.get(
    "/devices/{device_id}/detections",
    response_model=DeviceDetectionsOut,
    summary="Newest detection result per model on a camera",
)
async def list_detections(device_id: UUID) -> DeviceDetectionsOut:
    from app.services.inference_loop import get_inference_loop

    loop = get_inference_loop()
    detections = loop.get_latest_detections(device_id) if loop is not None else []
    return DeviceDetectionsOut(device_id=device_id, detections=[DetectionOut(**d) for d in detections])
