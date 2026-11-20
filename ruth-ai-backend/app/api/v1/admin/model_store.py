"""/api/v1/admin/model-store: drafts and chunked weight uploads.

Mounted on the admin protected_router, so every route requires an admin
token. The router's lifespan runs the 24h stale-staging cleanup.

Upload protocol:
    POST /models/{model_pk}/uploads            init (or resume: same filename+size)
    PUT  /uploads/{upload_id}/chunks/{index}   raw bytes, exactly chunk_size
                                               (last chunk: the remainder)
    GET  /uploads/{upload_id}                  received_chunks, for resume
    POST /uploads/{upload_id}/complete         server-side sha256, promote
    DELETE /uploads/{upload_id}                discard
Only the chunk PUT path gets nginx's larger body limit.
"""

import asyncio
import contextlib
from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.core.admin_auth import AdminUser
from app.deps import DBSession
from app.models.model_store import ModelStoreFile, ModelStoreModel, ModelStoreUpload
from app.schemas.model_store import (
    ChunkAck,
    ModelNoteCreate,
    ModelNoteList,
    ModelNoteOut,
    ModelNoteUpdate,
    RecommendationList,
    RecommendationOut,
    RecommendationSet,
    StoreFile,
    StoreFileList,
    StoreModelCreate,
    StoreModelDetail,
    StoreModelList,
    StoreModelRuntime,
    StoreModelSummary,
    StoreModelUpdate,
    StoreUpload,
    StoreUploadList,
    UploadComplete,
    UploadInit,
)
from app.services.model_store.enabled import enabled_store_models
from app.services.model_store.runtime_probe import (
    READY_STATE,
    StoreRuntimeProbe,
    probe_store_runtime,
)
from app.services.model_store import (
    ModelStore,
    get_model_store,
    model_store_lifespan,
    service,
)
from app.services.model_store import notes as notes_service
from app.services.model_store.service import ModelStoreError

router = APIRouter(prefix="/model-store", tags=["Admin: Model Store"], lifespan=model_store_lifespan)

Store = Annotated[ModelStore, Depends(get_model_store)]


@contextlib.contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except ModelStoreError as exc:
        raise HTTPException(
            status_code=exc.status,
            detail={"error": exc.code, "message": exc.message, **exc.extra},
        )


# =============================================================================
# Serialisers
# =============================================================================


def _file_out(record: ModelStoreFile) -> StoreFile:
    return StoreFile(
        id=record.id,
        filename=record.filename,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        uploaded_at=record.uploaded_at,
        uploaded_by=record.uploaded_by,
    )


async def _upload_out(store: ModelStore, upload: ModelStoreUpload) -> StoreUpload:
    received = (
        await asyncio.to_thread(store.received_chunks, upload.id)
        if upload.status == "uploading"
        else list(range(upload.total_chunks)) if upload.status == "completed" else []
    )
    return StoreUpload(
        id=upload.id,
        model_pk=upload.model_pk,
        filename=upload.filename,
        size_bytes=upload.size_bytes,
        chunk_size=upload.chunk_size,
        total_chunks=upload.total_chunks,
        received_chunks=received,
        status=upload.status,
        error=upload.error,
        client_last_modified=upload.client_last_modified,
        created_at=upload.created_at,
        updated_at=upload.updated_at,
    )


def _runtime_out(
    model: ModelStoreModel,
    probe: StoreRuntimeProbe | None,
    installed: dict[str, object],
) -> StoreModelRuntime | None:
    """Whether the store runtime is serving this model.

    Answers the question the upload status cannot: a model can be fully
    uploaded and still not be running. ``None`` when no store runtime is
    configured, so the UI shows "—" instead of inventing a state.
    """
    if probe is None or not probe.configured:
        return None

    if not probe.reachable:
        # Applies to every row: we genuinely do not know what is loaded.
        return StoreModelRuntime(
            state="unreachable",
            detail=probe.error or "Store runtime did not answer",
        )

    if model.model_id not in installed:
        # Uploaded, but never installed into enabled/ — the runtime only
        # loads what is there, so it was never going to run.
        return StoreModelRuntime(
            state="not_installed", detail="Not installed in enabled/"
        )

    entry = probe.model(model.model_id)
    if entry is None:
        return StoreModelRuntime(
            state="not_loaded", detail="Installed but not loaded by the runtime"
        )

    state = str(entry.get("state", "unknown"))
    health = str(entry.get("health", "unknown"))
    version = entry.get("version")
    if state == READY_STATE:
        return StoreModelRuntime(
            state="running",
            version=str(version) if version else None,
            detail=f"{state}, {health}",
        )
    return StoreModelRuntime(
        state="not_loaded",
        version=str(version) if version else None,
        detail=f"{state}, {health}",
    )


def _summary_out(
    model: ModelStoreModel,
    file_count: int,
    total_bytes: int,
    runtime: StoreModelRuntime | None = None,
    installed: bool = False,
    violation_types: list[str] | None = None,
    recommended_for: list[str] | None = None,
) -> StoreModelSummary:
    return StoreModelSummary(
        id=model.id,
        model_id=model.model_id,
        display_name=model.display_name,
        state=model.state,
        model_id_editable=(
            model.state == "draft" and model.first_applied_at is None and not installed
        ),
        installed=installed,
        violation_types=violation_types or [],
        recommended_for=recommended_for or [],
        file_count=file_count,
        total_bytes=total_bytes,
        status="uploaded" if file_count else "no_files",
        created_at=model.created_at,
        created_by=model.created_by,
        runtime=runtime,
    )


async def _detail_out(db, store: ModelStore, model: ModelStoreModel) -> StoreModelDetail:
    files = await service.list_files(db, model.id)
    uploads = await service.list_active_uploads(db, model.id)
    probe = await probe_store_runtime()
    installed = enabled_store_models()
    info = installed.get(model.model_id)
    recommended = await notes_service.active_recommendations(db)
    summary = _summary_out(
        model,
        len(files),
        sum(f.size_bytes for f in files),
        runtime=_runtime_out(model, probe, installed),
        installed=info is not None,
        violation_types=list(info.violation_types) if info else [],
        recommended_for=recommended.get(model.model_id, []),
    )
    return StoreModelDetail(
        **summary.model_dump(),
        files=[_file_out(f) for f in files],
        active_uploads=[await _upload_out(store, u) for u in uploads],
    )


# =============================================================================
# Models
# =============================================================================


@router.get("/models", response_model=StoreModelList, summary="List uploaded models")
async def list_models(db: DBSession, _store: Store) -> StoreModelList:
    summaries = await service.list_models(db)
    # Probed and read once for the whole page, not per row.
    probe = await probe_store_runtime()
    installed = enabled_store_models()
    recommended = await notes_service.active_recommendations(db)
    return StoreModelList(
        models=[
            _summary_out(
                s.model,
                s.file_count,
                s.total_bytes,
                runtime=_runtime_out(s.model, probe, installed),
                installed=s.model.model_id in installed,
                violation_types=(
                    list(installed[s.model.model_id].violation_types)
                    if s.model.model_id in installed
                    else []
                ),
                recommended_for=recommended.get(s.model.model_id, []),
            )
            for s in summaries
        ]
    )


@router.post(
    "/models",
    response_model=StoreModelDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft model",
)
async def create_model(
    body: StoreModelCreate, db: DBSession, store: Store, admin: AdminUser
) -> StoreModelDetail:
    with _http_errors():
        model = await service.create_model(db, body.display_name, body.model_id, admin.username)
    await db.commit()
    return await _detail_out(db, store, model)


@router.get("/models/{model_pk}", response_model=StoreModelDetail, summary="Model detail")
async def get_model(model_pk: UUID, db: DBSession, store: Store) -> StoreModelDetail:
    with _http_errors():
        model = await service.get_model(db, model_pk)
        return await _detail_out(db, store, model)


@router.patch(
    "/models/{model_pk}",
    response_model=StoreModelDetail,
    summary="Rename a draft",
    responses={
        409: {"description": "model_id_locked / model_id_taken"},
        503: {"description": "installed_state_unknown: enabled/ unreadable, so an ID change is refused"},
    },
)
async def update_model(
    model_pk: UUID, body: StoreModelUpdate, db: DBSession, store: Store, admin: AdminUser
) -> StoreModelDetail:
    with _http_errors():
        model = await service.update_model(
            db, store, model_pk, body.display_name, body.model_id, admin.username
        )
    await db.commit()
    return await _detail_out(db, store, model)


@router.delete(
    "/models/{model_pk}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a draft (moves it to trash; the model_id is never reused)",
    responses={
        409: {"description": "model_installed: the model is installed; uninstall it first"},
        503: {"description": "installed_state_unknown: enabled/ unreadable, so the delete is refused"},
    },
)
async def delete_model(model_pk: UUID, db: DBSession, store: Store, admin: AdminUser) -> Response:
    with _http_errors():
        await service.delete_model(db, store, model_pk, admin.username)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# Notes
# =============================================================================


async def _reason_map(db) -> dict:
    """note_id -> violation types it is the active recommendation reason for."""
    out: dict = {}
    for rec in await notes_service.list_recommendations(db):
        out.setdefault(rec.note.id, []).append(rec.violation_type)
    return out


def _note_out(note, project_names: dict, reasons: dict) -> ModelNoteOut:
    return ModelNoteOut(
        id=note.id,
        model_pk=note.model_pk,
        observed_on=note.observed_on,
        body=note.body,
        project_id=note.project_id,
        project_name=project_names.get(note.project_id),
        source=note.source,
        internal=note.internal,
        created_by=note.created_by,
        created_at=note.created_at,
        edited_by=note.edited_by,
        updated_at=note.updated_at,
        reason_for=reasons.get(note.id, []),
    )


async def _one_note_out(db, note) -> ModelNoteOut:
    names = await notes_service.project_names(db, [note.project_id])
    return _note_out(note, names, await _reason_map(db))


@router.get("/models/{model_pk}/notes", response_model=ModelNoteList, summary="A model's notes")
async def list_notes(model_pk: UUID, db: DBSession, _store: Store) -> ModelNoteList:
    with _http_errors():
        notes = await notes_service.list_notes(db, model_pk)
    names = await notes_service.project_names(db, (n.project_id for n in notes))
    reasons = await _reason_map(db)
    return ModelNoteList(notes=[_note_out(n, names, reasons) for n in notes])


@router.post(
    "/models/{model_pk}/notes",
    response_model=ModelNoteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a note to a model",
)
async def create_note(
    model_pk: UUID, body: ModelNoteCreate, db: DBSession, _store: Store, admin: AdminUser
) -> ModelNoteOut:
    with _http_errors():
        note = await notes_service.create_note(
            db,
            model_pk,
            body=body.body,
            observed_on=body.observed_on,
            project_id=body.project_id,
            source=body.source,
            internal=body.internal,
            actor=admin.username,
        )
    await db.commit()
    return await _one_note_out(db, note)


@router.patch("/notes/{note_id}", response_model=ModelNoteOut, summary="Edit a note")
async def update_note(
    note_id: UUID, body: ModelNoteUpdate, db: DBSession, _store: Store, admin: AdminUser
) -> ModelNoteOut:
    sent = body.model_fields_set
    extra = {}
    if "project_id" in sent:
        extra["project_id"] = body.project_id
    if "source" in sent:
        extra["source"] = body.source
    with _http_errors():
        note = await notes_service.update_note(
            db,
            note_id,
            actor=admin.username,
            body=body.body,
            observed_on=body.observed_on,
            internal=body.internal,
            **extra,
        )
    await db.commit()
    return await _one_note_out(db, note)


@router.delete(
    "/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a note",
    responses={409: {"description": "note_in_use: the reason for an active recommendation"}},
)
async def delete_note(note_id: UUID, db: DBSession, _store: Store, admin: AdminUser) -> Response:
    with _http_errors():
        await notes_service.delete_note(db, note_id, admin.username)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# Recommendations
# =============================================================================


async def _recommendations_out(db) -> RecommendationList:
    recs = await notes_service.list_recommendations(db)
    names = await notes_service.project_names(db, (r.note.project_id for r in recs))
    reasons: dict = {}
    for r in recs:
        reasons.setdefault(r.note.id, []).append(r.violation_type)
    return RecommendationList(
        recommendations=[
            RecommendationOut(
                violation_type=r.violation_type,
                label=r.label,
                model_pk=r.model_pk,
                model_id=r.model_id,
                display_name=r.display_name,
                active=r.active,
                note=_note_out(r.note, names, reasons),
                set_by=r.set_by,
                set_at=r.set_at,
            )
            for r in recs
        ]
    )


@router.get(
    "/recommendations",
    response_model=RecommendationList,
    summary="The recommended model per violation type (inactive = model uninstalled)",
)
async def list_recommendations(db: DBSession, _store: Store) -> RecommendationList:
    return await _recommendations_out(db)


@router.put(
    "/recommendations/{violation_type}",
    response_model=RecommendationList,
    summary="Recommend a model for a violation type, with a note as the reason",
    responses={
        409: {"description": "model_not_installed"},
        422: {"description": "violation_type_not_raised / note_not_for_model"},
    },
)
async def set_recommendation(
    violation_type: str, body: RecommendationSet, db: DBSession, _store: Store, admin: AdminUser
) -> RecommendationList:
    with _http_errors():
        await notes_service.set_recommendation(
            db, violation_type, model_pk=body.model_pk, note_id=body.note_id, actor=admin.username
        )
    await db.commit()
    return await _recommendations_out(db)


@router.delete(
    "/recommendations/{violation_type}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop recommending a model for a violation type",
)
async def clear_recommendation(
    violation_type: str, db: DBSession, _store: Store, admin: AdminUser
) -> Response:
    with _http_errors():
        await notes_service.clear_recommendation(db, violation_type, admin.username)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# Files
# =============================================================================


@router.get("/models/{model_pk}/files", response_model=StoreFileList, summary="List files")
async def list_files(model_pk: UUID, db: DBSession, _store: Store) -> StoreFileList:
    with _http_errors():
        files = await service.list_files(db, model_pk)
    return StoreFileList(files=[_file_out(f) for f in files])


@router.delete(
    "/models/{model_pk}/files/{file_pk}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one file from a draft",
    responses={
        409: {"description": "model_installed: the model is installed; uninstall it first"},
        503: {"description": "installed_state_unknown: enabled/ unreadable, so the delete is refused"},
    },
)
async def delete_file(
    model_pk: UUID, file_pk: UUID, db: DBSession, store: Store, admin: AdminUser
) -> Response:
    with _http_errors():
        await service.delete_file(db, store, model_pk, file_pk, admin.username)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# Uploads
# =============================================================================


@router.get(
    "/models/{model_pk}/uploads",
    response_model=StoreUploadList,
    summary="In-progress uploads (for resume after a reload)",
)
async def list_uploads(model_pk: UUID, db: DBSession, store: Store) -> StoreUploadList:
    with _http_errors():
        uploads = await service.list_active_uploads(db, model_pk)
    return StoreUploadList(uploads=[await _upload_out(store, u) for u in uploads])


@router.post(
    "/models/{model_pk}/uploads",
    response_model=StoreUpload,
    summary="Start or resume a chunked upload",
    responses={200: {"description": "Resumed an in-progress upload"}, 201: {"description": "Started"}},
)
async def init_upload(
    model_pk: UUID,
    body: UploadInit,
    response: Response,
    db: DBSession,
    store: Store,
    admin: AdminUser,
) -> StoreUpload:
    with _http_errors():
        upload, created = await service.init_upload(
            db,
            store,
            model_pk,
            body.filename,
            body.size_bytes,
            body.sha256,
            body.last_modified,
            admin.username,
        )
    await db.commit()
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return await _upload_out(store, upload)


@router.get("/uploads/{upload_id}", response_model=StoreUpload, summary="Upload status")
async def get_upload(upload_id: UUID, db: DBSession, store: Store) -> StoreUpload:
    with _http_errors():
        upload = await service.get_upload(db, upload_id)
    return await _upload_out(store, upload)


@router.put(
    "/uploads/{upload_id}/chunks/{index}",
    response_model=ChunkAck,
    summary="Upload one chunk (raw body)",
)
async def put_chunk(
    upload_id: UUID, index: int, request: Request, db: DBSession, store: Store
) -> ChunkAck:
    length_header = request.headers.get("content-length")
    content_length = int(length_header) if length_header and length_header.isdigit() else None
    with _http_errors():
        upload, received = await service.write_chunk(
            db, store, upload_id, index, request.stream(), content_length
        )
    await db.commit()
    return ChunkAck(
        upload_id=upload.id, index=index, received=received, total_chunks=upload.total_chunks
    )


@router.post(
    "/uploads/{upload_id}/complete",
    response_model=UploadComplete,
    summary="Finish an upload: verify chunks and sha256, add the file to the draft",
)
async def complete_upload(
    upload_id: UUID, db: DBSession, store: Store, admin: AdminUser
) -> UploadComplete:
    with _http_errors():
        record = await service.complete_upload(db, store, upload_id, admin.username)
    await db.commit()
    await asyncio.to_thread(store.remove_staging, upload_id)
    return UploadComplete(upload_id=upload_id, file=_file_out(record))


@router.delete(
    "/uploads/{upload_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Discard an in-progress upload",
)
async def abort_upload(upload_id: UUID, db: DBSession, store: Store) -> Response:
    with _http_errors():
        await service.abort_upload(db, store, upload_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
