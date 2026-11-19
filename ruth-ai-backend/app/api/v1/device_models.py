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

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.v1.model_guard import MODEL_GUARD_RESPONSES, require_installed_model
from app.core.cache import DEVICES_LIST_CACHE_KEYS, cache_delete
from app.deps import DBSession, StreamServiceDep
from app.services.exceptions import (
    DeviceNotFoundError,
    StreamAlreadyActiveError,
    StreamStartError,
)
from app.services.model_rates import MAX_OVERRIDE_FPS, MIN_OVERRIDE_FPS, desired_fps
from app.services.model_store.enabled import enabled_store_models
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
    status: str = Field(
        default="running",
        description="running; failing (no result for 60 s); unavailable (not installed: retired or never installed)",
    )
    reason: str | None = Field(default=None, description="model_retired / model_not_installed / inference_failing")
    message: str | None = None
    replacement: str | None = Field(default=None, description="What replaced a retired model")
    failing_since: datetime | None = None


class DeviceModelsOut(BaseModel):
    device_id: UUID
    session_id: UUID | None
    models_revision: int
    models: list[ModelEntryOut]
    not_started: list[ModelEntryOut] = Field(
        default_factory=list,
        description="Saved models a resume left out because they are not installed (status unavailable); "
        "DELETE removes them from the saved list",
    )


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


_ENTRY_KEYS = ("model_id", "model_version", "config", "fps_override")


async def _out(device_id: UUID, session, db) -> DeviceModelsOut:
    from app.services.camera_model_status import camera_model_statuses
    from app.services.inference_intent import InferenceIntentService
    from app.services.inference_loop import TARGET_FPS

    statuses = {
        (s.model_id, s.in_session): s for s in await camera_model_statuses(db, device_id=device_id)
    }

    def entry(e: dict, in_session: bool) -> ModelEntryOut:
        s = statuses.get((e["model_id"], in_session))
        extra = {}
        if s is not None:
            extra = dict(status=s.status, reason=s.reason, message=s.message,
                         replacement=s.replacement, failing_since=s.failing_since)
        return ModelEntryOut(**{k: e.get(k) for k in _ENTRY_KEYS}, target_fps=desired_fps(e, TARGET_FPS), **extra)

    running = session_entries(session)
    running_ids = {e["model_id"] for e in running}
    intent = await InferenceIntentService(db).get(device_id)
    saved = [dict(e) for e in (intent.models or [])] if intent is not None else []
    not_started = [
        entry(e, False) for e in saved
        if e.get("model_id") not in running_ids and (e.get("model_id"), False) in statuses
    ]
    return DeviceModelsOut(
        device_id=device_id,
        session_id=session.id if session else None,
        models_revision=session.models_revision if session else 0,
        models=[entry(e, True) for e in running],
        not_started=not_started,
    )


def _http(exc: SessionModelError) -> HTTPException:
    return HTTPException(exc.status, detail={"error": exc.code, "message": exc.message})


@router.get("/devices/{device_id}/models", response_model=DeviceModelsOut, summary="Models on a camera")
async def list_models(device_id: UUID, streams: StreamServiceDep, db: DBSession) -> DeviceModelsOut:
    session = await SessionModelsService(streams, db).get(device_id)
    return await _out(device_id, session, db)


@router.post(
    "/devices/{device_id}/models",
    response_model=DeviceModelsOut,
    summary="Add a model to a camera",
    responses={200: {"description": "Already running"}, 201: {"description": "Added"}, **MODEL_GUARD_RESPONSES},
)
async def add_model(
    device_id: UUID,
    body: ModelEntryIn,
    response: Response,
    streams: StreamServiceDep,
    db: DBSession,
) -> DeviceModelsOut:
    # A retired or uninstalled model is refused (422), whatever the caller
    # believes is installed: a tab opened before a deploy keeps its old list.
    await require_installed_model(body.model_id)
    # Uploaded models whose every rule needs a zone can raise nothing without
    # one: refuse them until zones are drawn (fails closed for API callers
    # too, not just the picker). Built-in models are never affected.
    store_info = enabled_store_models().get(body.model_id)
    if store_info and store_info.all_rules_need_zone and not (body.config or {}).get("zones"):
        raise HTTPException(
            422,
            detail={
                "error": "zone_required",
                "message": f"{store_info.display_name} needs a zone for every rule "
                f"({', '.join(store_info.zone_required_rules)}); draw one first",
            },
        )
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
    await cache_delete(*DEVICES_LIST_CACHE_KEYS)
    response.status_code = status.HTTP_201_CREATED if outcome.changed else status.HTTP_200_OK
    return await _out(device_id, outcome.session, db)


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
    await cache_delete(*DEVICES_LIST_CACHE_KEYS)
    return await _out(device_id, session, db)


@router.delete(
    "/devices/{device_id}/models/{model_id}",
    response_model=DeviceModelsOut,
    summary="Remove one model from a camera (the last one stops inference); also removes a saved model that was not started",
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
    await cache_delete(*DEVICES_LIST_CACHE_KEYS)
    return await _out(device_id, session, db)


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
