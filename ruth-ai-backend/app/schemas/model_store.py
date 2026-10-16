"""Schemas for /api/v1/admin/model-store."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class StoreModelCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=128)
    model_id: str | None = Field(
        default=None,
        description="Optional; generated from display_name when omitted",
    )


class StoreModelUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    model_id: str | None = Field(
        default=None, description="Editable until the model's first Apply"
    )


class StoreModelRuntime(BaseModel):
    """Whether the store runtime is actually serving this model.

    Distinct from ``StoreModelSummary.status``, which is about the *upload*
    (are the weight files here?). A model can be fully uploaded and still
    not be running — installed but not loaded, or not installed into
    ``enabled/`` at all — and until this field existed there was no way to
    see that from the admin page.
    """

    state: Literal["running", "not_loaded", "not_installed", "unreachable"] = Field(
        ...,
        description=(
            "running: loaded and ready. not_loaded: installed in enabled/ "
            "but the runtime isn't serving it. not_installed: uploaded but "
            "not in enabled/. unreachable: the store runtime did not answer."
        ),
    )
    version: str | None = Field(None, description="Version the runtime reports")
    detail: str | None = Field(
        None, description="Runtime state/health, or the reason it isn't running"
    )


class StoreModelSummary(BaseModel):
    id: UUID
    model_id: str
    display_name: str
    state: str
    model_id_editable: bool
    file_count: int
    total_bytes: int
    # Step 2: every file is simply "uploaded"; introspection arrives in Step 3.
    status: Literal["no_files", "uploaded"]
    created_at: datetime
    created_by: str | None
    #: None when no store runtime is configured — the column then shows "—"
    #: rather than claiming the model isn't running.
    runtime: StoreModelRuntime | None = None


class StoreFile(BaseModel):
    id: UUID
    filename: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime
    uploaded_by: str | None
    status: Literal["uploaded"] = "uploaded"


class StoreUpload(BaseModel):
    id: UUID
    model_pk: UUID
    filename: str
    size_bytes: int
    chunk_size: int
    total_chunks: int
    received_chunks: list[int]
    status: str
    error: str | None
    client_last_modified: int | None
    created_at: datetime
    updated_at: datetime


class StoreModelDetail(StoreModelSummary):
    files: list[StoreFile]
    active_uploads: list[StoreUpload]


class StoreModelList(BaseModel):
    models: list[StoreModelSummary]


class StoreFileList(BaseModel):
    files: list[StoreFile]


class StoreUploadList(BaseModel):
    uploads: list[StoreUpload]


class UploadInit(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
        description="Optional lowercase hex sha256; checked on complete",
    )
    last_modified: int | None = Field(
        default=None, description="Client file lastModified (ms), used to match resumes"
    )


class ChunkAck(BaseModel):
    upload_id: UUID
    index: int
    received: int
    total_chunks: int


class UploadComplete(BaseModel):
    upload_id: UUID
    file: StoreFile
