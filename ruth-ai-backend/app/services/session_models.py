"""Several models on one camera: add / update / remove entries of a session.

The camera's active stream session holds a list in stream_sessions.models.
Every change locks the session row (SELECT ... FOR UPDATE), so concurrent
edits serialise and none is lost, and bumps models_revision, which makes the
inference loop restart the session's task with the new list.

model_id / model_version / model_config always mirror models[0], so every
existing reader of a session (devices list, /detections/latest, analytics,
/models/status camera counts) stays correct.

Legacy sessions (models IS NULL, started via POST /start-inference) are
converted on their first edit here: their single model becomes models[0].
"""

import contextlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import StreamSession, StreamState
from app.services.exceptions import StreamAlreadyActiveError, StreamNotActiveError
from app.services.stream_service import StreamService

logger = get_logger(__name__)

ACTIVE_STATES = (StreamState.STARTING, StreamState.LIVE, StreamState.STOPPING)
MAX_MODELS_PER_CAMERA = 8


class SessionModelError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass
class ModelsResult:
    session: StreamSession | None
    changed: bool


def legacy_entry(session: StreamSession) -> dict[str, Any]:
    return {
        "model_id": session.model_id,
        "model_version": session.model_version,
        "config": session.model_config,
        "fps_override": None,
    }


def session_entries(session: StreamSession | None) -> list[dict[str, Any]]:
    """The models a session runs, whether legacy or multi-model."""
    if session is None:
        return []
    if session.models is None:
        return [legacy_entry(session)]
    return [dict(e) for e in session.models]


class SessionModelsService:
    def __init__(self, stream_service: StreamService, db: AsyncSession):
        self._streams = stream_service
        self._db = db

    async def _locked_active_session(self, device_id: UUID) -> StreamSession | None:
        stmt = (
            select(StreamSession)
            .where(StreamSession.device_id == device_id, StreamSession.state.in_(ACTIVE_STATES))
            .with_for_update()
        )
        return (await self._db.execute(stmt)).scalars().first()

    def _write(self, session: StreamSession, entries: list[dict[str, Any]]) -> None:
        """Store the list, mirror models[0] into the legacy columns, bump revision."""
        session.models = entries
        primary = entries[0]
        session.model_id = primary["model_id"]
        session.model_version = primary.get("model_version")
        session.model_config = primary.get("config")
        session.models_revision = (session.models_revision or 0) + 1

    async def get(self, device_id: UUID) -> StreamSession | None:
        return await self._streams.get_active_session_for_device(device_id)

    async def add(
        self,
        device_id: UUID,
        entry: dict[str, Any],
        *,
        inference_fps: int = 10,
        confidence_threshold: float = 0.7,
    ) -> ModelsResult:
        """Add a model to the camera; start a session if it has none."""
        session = await self._locked_active_session(device_id)
        if session is None:
            try:
                session = await self._streams.start_stream(
                    device_id,
                    model_id=entry["model_id"],
                    model_version=entry.get("model_version"),
                    inference_fps=inference_fps,
                    confidence_threshold=confidence_threshold,
                    model_config=entry.get("config"),
                )
            except StreamAlreadyActiveError:
                # Another request started this camera's session first (the
                # unique index decided). Add to that session instead.
                session = await self._locked_active_session(device_id)
                if session is None:
                    raise
            else:
                self._write(session, [entry])
                await self._db.flush()
                logger.info("Started session with model", device_id=str(device_id), model_id=entry["model_id"])
                return ModelsResult(session, True)

        entries = session_entries(session)
        if any(e["model_id"] == entry["model_id"] for e in entries):
            return ModelsResult(session, False)
        if len(entries) >= MAX_MODELS_PER_CAMERA:
            raise SessionModelError(
                409, "too_many_models", f"a camera can run at most {MAX_MODELS_PER_CAMERA} models"
            )
        self._write(session, entries + [entry])
        await self._db.flush()
        logger.info(
            "Added model to session",
            device_id=str(device_id),
            session_id=str(session.id),
            model_id=entry["model_id"],
            models=[e["model_id"] for e in session.models],
        )
        return ModelsResult(session, True)

    async def update(self, device_id: UUID, model_id: str, changes: dict[str, Any]) -> StreamSession:
        """Change one model's config and/or fps_override. Takes effect at once
        (the revision bump restarts the session's task) for 1 or N models."""
        session = await self._locked_active_session(device_id)
        entries = session_entries(session)
        target = next((e for e in entries if e["model_id"] == model_id), None)
        if session is None or target is None:
            raise SessionModelError(404, "model_not_active", f"{model_id} is not running on this camera")
        target.update(changes)
        self._write(session, entries)
        await self._db.flush()
        logger.info(
            "Updated session model",
            device_id=str(device_id),
            model_id=model_id,
            changed=sorted(changes),
        )
        return session

    async def remove(self, device_id: UUID, model_id: str) -> StreamSession | None:
        """Remove one model; removing the last one stops inference (as today)."""
        session = await self._locked_active_session(device_id)
        entries = session_entries(session)
        if session is None or not any(e["model_id"] == model_id for e in entries):
            raise SessionModelError(404, "model_not_active", f"{model_id} is not running on this camera")
        remaining = [e for e in entries if e["model_id"] != model_id]
        if not remaining:
            with contextlib.suppress(StreamNotActiveError):
                await self._streams.stop_inference(device_id)
            logger.info("Removed last model; inference stopped", device_id=str(device_id), model_id=model_id)
            return None
        self._write(session, remaining)
        await self._db.flush()
        logger.info(
            "Removed model from session",
            device_id=str(device_id),
            model_id=model_id,
            models=[e["model_id"] for e in remaining],
        )
        return session
