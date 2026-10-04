"""Model store service: drafts, chunked uploads, deletion, staging cleanup.

DB access is async (SQLAlchemy); filesystem work is delegated to ModelStore
and run in a thread. Errors are raised as ModelStoreError with an HTTP status
and a stable error code; the router turns them into responses.
"""

import asyncio
import math
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.model_store import (
    MODEL_STATE_DELETED,
    MODEL_STATE_DRAFT,
    UPLOAD_STATUS_ABORTED,
    UPLOAD_STATUS_COMPLETED,
    UPLOAD_STATUS_EXPIRED,
    UPLOAD_STATUS_FAILED,
    UPLOAD_STATUS_UPLOADING,
    ModelStoreFile,
    ModelStoreModel,
    ModelStoreUpload,
)
from app.services.model_store.ids import model_id_candidates, model_id_problem
from app.services.model_store.storage import ModelStore, file_age_seconds

logger = get_logger(__name__)

MIB = 1024 * 1024
GIB = 1024 * MIB

CHUNK_SIZE = 16 * MIB
MAX_FILE_BYTES = 2 * GIB
MAX_FILES_PER_MODEL = 16
STAGING_QUOTA_BYTES = 20 * GIB
STALE_AFTER = timedelta(hours=24)
# Keep this much disk free beyond the upload itself.
DISK_HEADROOM_BYTES = 1 * GIB

ALLOWED_EXTENSIONS = (".pt",)
FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,250}$")

# Serialises upload inits so two concurrent inits cannot both pass the quota.
_INIT_LOCK_KEY = 0x6D73_7570  # "msup"


class ModelStoreError(Exception):
    def __init__(self, status: int, code: str, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra or {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# Models
# =============================================================================


@dataclass(frozen=True)
class ModelSummary:
    model: ModelStoreModel
    file_count: int
    total_bytes: int


async def list_models(db: AsyncSession) -> list[ModelSummary]:
    stmt = (
        select(
            ModelStoreModel,
            func.count(ModelStoreFile.id),
            func.coalesce(func.sum(ModelStoreFile.size_bytes), 0),
        )
        .outerjoin(ModelStoreFile, ModelStoreFile.model_pk == ModelStoreModel.id)
        .where(ModelStoreModel.state != MODEL_STATE_DELETED)
        .group_by(ModelStoreModel.id)
        .order_by(ModelStoreModel.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return [ModelSummary(model=m, file_count=c, total_bytes=int(s)) for m, c, s in rows]


async def get_model(db: AsyncSession, model_pk: uuid.UUID) -> ModelStoreModel:
    model = await db.get(ModelStoreModel, model_pk)
    if model is None or model.state == MODEL_STATE_DELETED:
        raise ModelStoreError(404, "model_not_found", "model not found")
    return model


def _require_draft(model: ModelStoreModel) -> None:
    if model.state != MODEL_STATE_DRAFT:
        raise ModelStoreError(409, "model_not_draft", f"model is {model.state}, not a draft")


async def _model_id_taken(db: AsyncSession, model_id: str) -> bool:
    # Tombstones (deleted rows) count: an id is never reused.
    stmt = select(func.count()).select_from(ModelStoreModel).where(
        ModelStoreModel.model_id == model_id
    )
    return (await db.execute(stmt)).scalar_one() > 0


async def _validate_new_model_id(db: AsyncSession, model_id: str) -> None:
    problem = model_id_problem(model_id)
    if problem:
        raise ModelStoreError(422, "invalid_model_id", problem)
    if await _model_id_taken(db, model_id):
        raise ModelStoreError(
            409, "model_id_taken", f"model_id '{model_id}' is already used (or was used)"
        )


async def _generate_model_id(db: AsyncSession, display_name: str) -> str:
    for candidate in model_id_candidates(display_name):
        if model_id_problem(candidate) is None and not await _model_id_taken(db, candidate):
            return candidate
    raise ModelStoreError(409, "model_id_taken", "could not generate a free model_id; set one")


async def create_model(
    db: AsyncSession, display_name: str, model_id: str | None, actor: str
) -> ModelStoreModel:
    display_name = display_name.strip()
    if not display_name:
        raise ModelStoreError(422, "invalid_display_name", "display_name is required")
    if model_id is not None:
        await _validate_new_model_id(db, model_id)
    else:
        model_id = await _generate_model_id(db, display_name)

    model = ModelStoreModel(
        model_id=model_id,
        display_name=display_name,
        state=MODEL_STATE_DRAFT,
        created_by=actor,
    )
    db.add(model)
    try:
        await db.flush()
    except IntegrityError:
        raise ModelStoreError(409, "model_id_taken", f"model_id '{model_id}' is already used")
    logger.info("Model store draft created", model_id=model_id, actor=actor)
    return model


async def update_model(
    db: AsyncSession,
    model_pk: uuid.UUID,
    display_name: str | None,
    model_id: str | None,
    actor: str,
) -> ModelStoreModel:
    model = await get_model(db, model_pk)
    _require_draft(model)
    if display_name is not None:
        if not display_name.strip():
            raise ModelStoreError(422, "invalid_display_name", "display_name is required")
        model.display_name = display_name.strip()
    if model_id is not None and model_id != model.model_id:
        if model.first_applied_at is not None:
            raise ModelStoreError(
                409, "model_id_locked", "model_id cannot change after the first Apply"
            )
        await _validate_new_model_id(db, model_id)
        model.model_id = model_id
    try:
        await db.flush()
    except IntegrityError:
        raise ModelStoreError(409, "model_id_taken", f"model_id '{model_id}' is already used")
    logger.info("Model store draft updated", model_id=model.model_id, actor=actor)
    return model


async def delete_model(
    db: AsyncSession, store: ModelStore, model_pk: uuid.UUID, actor: str
) -> ModelStoreModel:
    """Trash a draft: abort its uploads, move its directory, tombstone the row."""
    model = await get_model(db, model_pk)
    _require_draft(model)

    active = (
        await db.execute(
            select(ModelStoreUpload).where(
                ModelStoreUpload.model_pk == model.id,
                ModelStoreUpload.status == UPLOAD_STATUS_UPLOADING,
            )
        )
    ).scalars().all()
    for upload in active:
        upload.status = UPLOAD_STATUS_ABORTED
        upload.error = "model deleted"
        await asyncio.to_thread(store.remove_staging, upload.id)

    model.trash_path = await asyncio.to_thread(store.trash_draft, model.id, model.model_id)
    model.state = MODEL_STATE_DELETED
    model.deleted_at = _now()
    model.deleted_by = actor
    await db.flush()
    logger.info(
        "Model store draft deleted",
        model_id=model.model_id,
        trash_path=model.trash_path,
        actor=actor,
    )
    return model


# =============================================================================
# Files
# =============================================================================


async def list_files(db: AsyncSession, model_pk: uuid.UUID) -> list[ModelStoreFile]:
    await get_model(db, model_pk)
    stmt = (
        select(ModelStoreFile)
        .where(ModelStoreFile.model_pk == model_pk)
        .order_by(ModelStoreFile.filename)
    )
    return list((await db.execute(stmt)).scalars().all())


async def delete_file(
    db: AsyncSession, store: ModelStore, model_pk: uuid.UUID, file_pk: uuid.UUID, actor: str
) -> None:
    model = await get_model(db, model_pk)
    _require_draft(model)
    record = await db.get(ModelStoreFile, file_pk)
    if record is None or record.model_pk != model.id:
        raise ModelStoreError(404, "file_not_found", "file not found")
    await db.delete(record)
    await db.flush()
    await asyncio.to_thread(store.delete_weights, record.storage_path)
    logger.info(
        "Model store file deleted", model_id=model.model_id, filename=record.filename, actor=actor
    )


# =============================================================================
# Uploads
# =============================================================================


def validate_filename(filename: str) -> str:
    if (
        filename != filename.strip()
        or "/" in filename
        or "\\" in filename
        or not FILENAME_PATTERN.match(filename)
    ):
        raise ModelStoreError(
            422,
            "invalid_filename",
            "filename may contain letters, digits, '.', '_' and '-' only",
        )
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise ModelStoreError(
            415, "unsupported_file_type", "only .pt files are accepted for now"
        )
    return filename


def expected_chunk_length(upload: ModelStoreUpload, index: int) -> int:
    if index < upload.total_chunks - 1:
        return upload.chunk_size
    return upload.size_bytes - upload.chunk_size * (upload.total_chunks - 1)


async def get_upload(db: AsyncSession, upload_id: uuid.UUID, *, lock: bool = False) -> ModelStoreUpload:
    stmt = select(ModelStoreUpload).where(ModelStoreUpload.id == upload_id)
    if lock:
        stmt = stmt.with_for_update()
    upload = (await db.execute(stmt)).scalar_one_or_none()
    if upload is None:
        raise ModelStoreError(404, "upload_not_found", "upload not found")
    return upload


async def list_active_uploads(db: AsyncSession, model_pk: uuid.UUID) -> list[ModelStoreUpload]:
    await get_model(db, model_pk)
    stmt = (
        select(ModelStoreUpload)
        .where(
            ModelStoreUpload.model_pk == model_pk,
            ModelStoreUpload.status == UPLOAD_STATUS_UPLOADING,
        )
        .order_by(ModelStoreUpload.created_at)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _abort(db: AsyncSession, store: ModelStore, upload: ModelStoreUpload, reason: str) -> None:
    upload.status = UPLOAD_STATUS_ABORTED
    upload.error = reason
    await db.flush()
    await asyncio.to_thread(store.remove_staging, upload.id)


async def init_upload(
    db: AsyncSession,
    store: ModelStore,
    model_pk: uuid.UUID,
    filename: str,
    size_bytes: int,
    expected_sha256: str | None,
    client_last_modified: int | None,
    actor: str,
) -> tuple[ModelStoreUpload, bool]:
    """Start (or resume) an upload of one file into a draft. Returns (upload, created).

    Idempotent for resume: an in-flight upload of the same filename and size
    is returned as-is, with the chunks already received.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _INIT_LOCK_KEY})

    model = await get_model(db, model_pk)
    _require_draft(model)
    validate_filename(filename)
    if size_bytes <= 0:
        raise ModelStoreError(422, "empty_file", "file is empty")
    if size_bytes > MAX_FILE_BYTES:
        raise ModelStoreError(
            413, "file_too_large", f"files are limited to {MAX_FILE_BYTES // GIB} GiB"
        )

    existing_file = (
        await db.execute(
            select(ModelStoreFile).where(
                ModelStoreFile.model_pk == model.id, ModelStoreFile.filename == filename
            )
        )
    ).scalar_one_or_none()
    if existing_file is not None:
        raise ModelStoreError(
            409,
            "file_exists",
            f"'{filename}' is already in this model; delete it first to replace it",
        )

    in_flight = (
        await db.execute(
            select(ModelStoreUpload).where(
                ModelStoreUpload.model_pk == model.id,
                ModelStoreUpload.filename == filename,
                ModelStoreUpload.status == UPLOAD_STATUS_UPLOADING,
            )
        )
    ).scalar_one_or_none()
    if in_flight is not None:
        same_file = in_flight.size_bytes == size_bytes and (
            expected_sha256 is None or in_flight.expected_sha256 in (None, expected_sha256)
        )
        if same_file:
            return in_flight, False
        # A different file under the same name replaces the abandoned upload.
        await _abort(db, store, in_flight, "replaced by a new upload of the same filename")

    file_count = (
        await db.execute(
            select(func.count()).select_from(ModelStoreFile).where(ModelStoreFile.model_pk == model.id)
        )
    ).scalar_one()
    active_for_model = (
        await db.execute(
            select(func.count())
            .select_from(ModelStoreUpload)
            .where(
                ModelStoreUpload.model_pk == model.id,
                ModelStoreUpload.status == UPLOAD_STATUS_UPLOADING,
            )
        )
    ).scalar_one()
    if file_count + active_for_model >= MAX_FILES_PER_MODEL:
        raise ModelStoreError(
            409, "too_many_files", f"a model may have at most {MAX_FILES_PER_MODEL} files"
        )

    staged = (
        await db.execute(
            select(func.coalesce(func.sum(ModelStoreUpload.size_bytes), 0)).where(
                ModelStoreUpload.status == UPLOAD_STATUS_UPLOADING
            )
        )
    ).scalar_one()
    if int(staged) + size_bytes > STAGING_QUOTA_BYTES:
        raise ModelStoreError(
            507,
            "staging_quota_exceeded",
            f"staging is limited to {STAGING_QUOTA_BYTES // GIB} GiB of in-progress uploads; "
            "finish or discard some first",
            {"staged_bytes": int(staged), "quota_bytes": STAGING_QUOTA_BYTES},
        )
    free = await asyncio.to_thread(store.free_bytes)
    if free < size_bytes + DISK_HEADROOM_BYTES:
        raise ModelStoreError(507, "disk_full", "not enough free disk space for this file")

    upload = ModelStoreUpload(
        model_pk=model.id,
        filename=filename,
        size_bytes=size_bytes,
        chunk_size=CHUNK_SIZE,
        total_chunks=math.ceil(size_bytes / CHUNK_SIZE),
        expected_sha256=expected_sha256,
        client_last_modified=client_last_modified,
        status=UPLOAD_STATUS_UPLOADING,
        created_by=actor,
    )
    db.add(upload)
    await db.flush()
    await asyncio.to_thread(store.create_staging, upload.id, size_bytes)
    logger.info(
        "Model store upload started",
        model_id=model.model_id,
        filename=filename,
        size_bytes=size_bytes,
        total_chunks=upload.total_chunks,
        actor=actor,
    )
    return upload, True


async def write_chunk(
    db: AsyncSession,
    store: ModelStore,
    upload_id: uuid.UUID,
    index: int,
    body: AsyncIterator[bytes],
    content_length: int | None,
) -> tuple[ModelStoreUpload, int]:
    """Receive one chunk. Returns (upload, chunks received so far)."""
    upload = await get_upload(db, upload_id)
    if upload.status != UPLOAD_STATUS_UPLOADING:
        raise ModelStoreError(409, "upload_not_active", f"upload is {upload.status}")
    if not 0 <= index < upload.total_chunks:
        raise ModelStoreError(
            422, "invalid_chunk_index", f"chunk index must be 0..{upload.total_chunks - 1}"
        )
    expected = expected_chunk_length(upload, index)
    if content_length is not None and content_length != expected:
        raise ModelStoreError(
            413 if content_length > expected else 400,
            "invalid_chunk_length",
            f"chunk {index} must be exactly {expected} bytes",
        )

    buffer = bytearray()
    async for piece in body:
        buffer += piece
        if len(buffer) > expected:
            raise ModelStoreError(
                413, "invalid_chunk_length", f"chunk {index} must be exactly {expected} bytes"
            )
    if len(buffer) != expected:
        raise ModelStoreError(
            400, "invalid_chunk_length", f"chunk {index} must be exactly {expected} bytes"
        )

    try:
        await asyncio.to_thread(
            store.write_chunk, upload.id, index, index * upload.chunk_size, bytes(buffer)
        )
    except FileNotFoundError:
        # Completed or aborted while this chunk was in flight.
        raise ModelStoreError(409, "upload_not_active", "upload is no longer active")
    # Touch last-activity so the stale cleanup leaves an active upload alone.
    await db.execute(
        update(ModelStoreUpload).where(ModelStoreUpload.id == upload.id).values(updated_at=_now())
    )
    received = len(await asyncio.to_thread(store.received_chunks, upload.id))
    return upload, received


async def complete_upload(
    db: AsyncSession, store: ModelStore, upload_id: uuid.UUID, actor: str
) -> ModelStoreFile:
    """Verify all chunks, hash server-side, promote into the draft."""
    upload = await get_upload(db, upload_id, lock=True)

    if upload.status == UPLOAD_STATUS_COMPLETED and upload.file_id is not None:
        record = await db.get(ModelStoreFile, upload.file_id)
        if record is not None:
            return record  # idempotent: a retried complete returns the same file
    if upload.status != UPLOAD_STATUS_UPLOADING:
        raise ModelStoreError(409, "upload_not_active", f"upload is {upload.status}")

    model = await get_model(db, upload.model_pk)
    _require_draft(model)

    received = set(await asyncio.to_thread(store.received_chunks, upload.id))
    missing = [i for i in range(upload.total_chunks) if i not in received]
    if missing:
        raise ModelStoreError(
            409,
            "missing_chunks",
            f"{len(missing)} chunk(s) not received yet",
            {"missing_chunks": missing[:100]},
        )

    sha256, size = await asyncio.to_thread(store.sha256_of_data, upload.id)
    if size != upload.size_bytes:
        upload.status = UPLOAD_STATUS_FAILED
        upload.error = f"assembled size {size} != declared {upload.size_bytes}"
        await db.commit()  # the request rolls back on error; keep the failure
        await asyncio.to_thread(store.remove_staging, upload.id)
        raise ModelStoreError(422, "size_mismatch", upload.error)
    if upload.expected_sha256 and sha256 != upload.expected_sha256:
        upload.status = UPLOAD_STATUS_FAILED
        upload.error = "sha256 mismatch"
        await db.commit()  # the request rolls back on error; keep the failure
        await asyncio.to_thread(store.remove_staging, upload.id)
        logger.warning(
            "Model store upload sha256 mismatch",
            model_id=model.model_id,
            filename=upload.filename,
            expected=upload.expected_sha256,
            actual=sha256,
        )
        raise ModelStoreError(
            422,
            "sha256_mismatch",
            "uploaded data does not match the expected sha256; upload the file again",
            {"expected_sha256": upload.expected_sha256, "actual_sha256": sha256},
        )

    record = ModelStoreFile(
        model_pk=model.id,
        filename=upload.filename,
        size_bytes=size,
        sha256=sha256,
        storage_path=store.relative(store.weights_path(model.id, upload.filename)),
        uploaded_at=_now(),
        uploaded_by=actor,
    )
    db.add(record)
    try:
        await db.flush()
    except IntegrityError:
        raise ModelStoreError(
            409, "file_exists", f"'{upload.filename}' is already in this model"
        )
    await asyncio.to_thread(store.promote, upload.id, model.id, upload.filename)
    upload.status = UPLOAD_STATUS_COMPLETED
    upload.file_id = record.id
    await db.flush()
    # Staging is removed by the caller after commit, so a failed commit never
    # leaves a "completed" upload without its data.
    logger.info(
        "Model store upload completed",
        model_id=model.model_id,
        filename=upload.filename,
        size_bytes=size,
        sha256=sha256,
        actor=actor,
    )
    return record


async def abort_upload(db: AsyncSession, store: ModelStore, upload_id: uuid.UUID) -> None:
    upload = await get_upload(db, upload_id, lock=True)
    if upload.status != UPLOAD_STATUS_UPLOADING:
        return
    await _abort(db, store, upload, "discarded by admin")


# =============================================================================
# Stale staging cleanup
# =============================================================================


async def cleanup_stale_staging(
    db: AsyncSession, store: ModelStore, now: datetime | None = None
) -> dict[str, int]:
    """Expire uploads idle for 24h and remove orphaned staging entries."""
    now = now or _now()
    cutoff = now - STALE_AFTER

    stale = (
        await db.execute(
            select(ModelStoreUpload).where(
                ModelStoreUpload.status == UPLOAD_STATUS_UPLOADING,
                ModelStoreUpload.updated_at < cutoff,
            )
        )
    ).scalars().all()
    for upload in stale:
        upload.status = UPLOAD_STATUS_EXPIRED
        upload.error = "no activity for 24h"
        await asyncio.to_thread(store.remove_staging, upload.id)
    await db.flush()

    active_ids = {
        str(i)
        for i in (
            await db.execute(
                select(ModelStoreUpload.id).where(ModelStoreUpload.status == UPLOAD_STATUS_UPLOADING)
            )
        ).scalars()
    }
    orphans = 0
    for name, mtime in await asyncio.to_thread(store.staging_entries):
        if name not in active_ids and file_age_seconds(mtime) > STALE_AFTER.total_seconds():
            await asyncio.to_thread(store.remove_staging_entry, name)
            orphans += 1

    if stale or orphans:
        logger.info("Model store staging cleaned", expired_uploads=len(stale), orphans=orphans)
    return {"expired_uploads": len(stale), "orphans_removed": orphans}
