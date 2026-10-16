"""Schemas for /api/v1/admin/projects (Start New Project)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LiveCameraInfo(BaseModel):
    """A camera whose inference session is blocking the archive."""

    device_id: uuid.UUID
    camera_name: str
    session_id: uuid.UUID
    state: str


class ProjectSummary(BaseModel):
    """One project row."""

    id: uuid.UUID
    name: str
    slug: str
    state: str
    started_at: datetime
    started_by: str
    ended_at: datetime | None = None
    ended_by: str | None = None
    archive_batch_id: uuid.UUID | None = None
    archived_counts: dict[str, int] | None = None
    backup_path: str | None = None

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    items: list[ProjectSummary]
    active: ProjectSummary | None = Field(
        None, description="The project currently collecting data, if any"
    )


class PreflightResponse(BaseModel):
    """What starting a new project would do, measured now.

    The confirmation screen renders these numbers verbatim; the archive
    re-measures under a lock and refuses if anything changed in a way that
    matters, so the figures shown are never merely indicative.
    """

    can_proceed: bool
    blockers: list[str] = Field(
        default_factory=list,
        description=(
            "Machine-readable reasons the action is refused: "
            "inference_active, too_much_data, backup_unavailable"
        ),
    )
    current_project: ProjectSummary | None = None
    row_counts: dict[str, int] = Field(
        description="Rows that would be archived, per live table"
    )
    total_rows: int
    live_cameras: list[LiveCameraInfo] = Field(default_factory=list)
    backup_dir: str
    evidence_with_vas_media: int = Field(
        description=(
            "Evidence rows holding a VAS snapshot/bookmark id. Their VAS "
            "paths are captured into the archive; ids VAS has already reaped "
            "resolve to nothing and are recorded as unresolved."
        )
    )


class StartProjectRequest(BaseModel):
    """Start a new project.

    `confirm_name` must equal `name` byte for byte — it is the typed
    confirmation, not a checkbox.
    """

    name: str = Field(
        min_length=3,
        max_length=200,
        description="Name of the NEW project",
    )
    confirm_name: str = Field(
        min_length=3,
        max_length=200,
        description="Retype the new project name exactly",
    )
    stop_inference: bool = Field(
        default=False,
        description=(
            "Stop every live inference session first and wait for it to wind "
            "down. Without this, live inference refuses the request: "
            "archiving while the InferenceLoop is writing would race it."
        ),
    )
    confirm_large: bool = Field(
        default=False,
        description=(
            "Acknowledge an unusually large archive. Only consulted when the "
            "row count exceeds the advisory threshold."
        ),
    )


class StartProjectResponse(BaseModel):
    """The outcome, with enough detail to reassure that nothing was deleted."""

    new_project: ProjectSummary
    archived_project: ProjectSummary | None
    archive_batch_id: uuid.UUID | None
    archived_counts: dict[str, int]
    backup_path: str | None
    stopped_cameras: list[str] = Field(default_factory=list)
    vas_paths_resolved: int = 0
    vas_paths_missing: int = 0
    message: str


class ArchivedViolation(BaseModel):
    """One archived violation, for the read-only archived-project viewer."""

    id: uuid.UUID
    device_id: uuid.UUID
    camera_name: str
    type: str
    type_detail: str | None = None
    status: str
    confidence: float
    timestamp: datetime
    model_id: str
    model_version: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    resolution_notes: str | None = None
    #: Paths as VAS held them at archive time. Present only when VAS still
    #: had the media then; null means the file had already been reaped.
    snapshot_path: str | None = None
    video_path: str | None = None


class ArchivedViolationListResponse(BaseModel):
    project: ProjectSummary
    items: list[ArchivedViolation]
    total: int
