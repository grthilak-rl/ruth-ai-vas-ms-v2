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
    StoreFile,
    StoreFileList,
    StoreModelCreate,
    StoreModelDetail,
    StoreModelList,
    StoreModelSummary,
    StoreModelUpdate,
    StoreUpload,
    StoreUploadList,
    UploadComplete,
    UploadInit,
)
from app.services.model_store import (
    ModelStore,
    get_model_store,
    model_store_lifespan,
    service,
)
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


def _summary_out(model: ModelStoreModel, file_count: int, total_bytes: int) -> StoreModelSummary:
    return StoreModelSummary(
        id=model.id,
        model_id=model.model_id,
        display_name=model.display_name,
        state=model.state,
        model_id_editable=model.state == "draft" and model.first_applied_at is None,
        file_count=file_count,
        total_bytes=total_bytes,
        status="uploaded" if file_count else "no_files",
        created_at=model.created_at,
        created_by=model.created_by,
    )


async def _detail_out(db, store: ModelStore, model: ModelStoreModel) -> StoreModelDetail:
    files = await service.list_files(db, model.id)
    uploads = await service.list_active_uploads(db, model.id)
    summary = _summary_out(model, len(files), sum(f.size_bytes for f in files))
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
    return StoreModelList(
        models=[_summary_out(s.model, s.file_count, s.total_bytes) for s in summaries]
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


@router.patch("/models/{model_pk}", response_model=StoreModelDetail, summary="Rename a draft")
async def update_model(
    model_pk: UUID, body: StoreModelUpdate, db: DBSession, store: Store, admin: AdminUser
) -> StoreModelDetail:
    with _http_errors():
        model = await service.update_model(
            db, model_pk, body.display_name, body.model_id, admin.username
        )
    await db.commit()
    return await _detail_out(db, store, model)


@router.delete(
    "/models/{model_pk}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a draft (moves it to trash; the model_id is never reused)",
)
async def delete_model(model_pk: UUID, db: DBSession, store: Store, admin: AdminUser) -> Response:
    with _http_errors():
        await service.delete_model(db, store, model_pk, admin.username)
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
