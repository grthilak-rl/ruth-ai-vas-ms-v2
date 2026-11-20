"""Schemas for /api/v1/admin/model-store."""

from datetime import date, datetime
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
    #: Its model ID is in the store's enabled/ tree: the runtime serves it,
    #: so the draft and its files cannot be deleted.
    installed: bool = False
    #: Violation types its installed manifest raises ([] when not installed).
    violation_types: list[str] = []
    #: Violation types it is the active recommended model for.
    recommended_for: list[str] = []
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


# =============================================================================
# Notes and recommendations
# =============================================================================


class ModelNoteOut(BaseModel):
    id: UUID
    model_pk: UUID
    observed_on: date
    body: str
    project_id: UUID | None
    project_name: str | None
    source: str | None
    #: Shown on the model page only, never in the camera picker.
    internal: bool
    created_by: str
    created_at: datetime
    edited_by: str | None
    updated_at: datetime
    #: Violation types this note is the active recommendation reason for.
    reason_for: list[str] = []


class ModelNoteList(BaseModel):
    notes: list[ModelNoteOut]


class ModelNoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    observed_on: date
    project_id: UUID | None = None
    source: str | None = Field(default=None, max_length=500)
    internal: bool = False


class ModelNoteUpdate(BaseModel):
    """Only the fields sent change; send project_id/source null to clear them."""

    body: str | None = Field(default=None, min_length=1, max_length=2000)
    observed_on: date | None = None
    project_id: UUID | None = None
    source: str | None = Field(default=None, max_length=500)
    internal: bool | None = None


class RecommendationOut(BaseModel):
    violation_type: str
    label: str
    model_pk: UUID
    model_id: str
    display_name: str
    #: False when the model is no longer installed: kept, not shown as recommended.
    active: bool
    note: ModelNoteOut
    set_by: str
    set_at: datetime


class RecommendationList(BaseModel):
    recommendations: list[RecommendationOut]


class RecommendationSet(BaseModel):
    model_pk: UUID
    note_id: UUID
