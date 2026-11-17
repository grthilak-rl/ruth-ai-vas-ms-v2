"""Schemas for projects: the admin lifecycle API and the read-only project list."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


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
    stopped_at: datetime | None = None
    stopped_by: str | None = None
    resumed_at: datetime | None = None
    resumed_by: str | None = None
    lifecycle_error: str | None = None
    #: Rows tagged with this project, per table (list endpoint only).
    counts: dict[str, int] | None = None

    model_config = {"from_attributes": True}


class ProjectBrief(BaseModel):
    """What any portal user needs to show and pick a project (no audit fields)."""

    id: uuid.UUID
    name: str
    slug: str
    state: str
    started_at: datetime
    ended_at: datetime | None = None
    #: The project is current (active/stopping/stopped/resuming). False for
    #: every project between End and the next Start.
    is_current: bool = False

    model_config = {"from_attributes": True}


class ProjectBriefList(BaseModel):
    items: list[ProjectBrief]
    current: ProjectBrief | None = None


class ProjectCameraInfo(BaseModel):
    """A camera of a project, for past-project camera filters."""

    id: uuid.UUID
    name: str
    display_name: str | None = None
    enabled: bool


class LifecycleCamera(BaseModel):
    """One camera in a Stop/Resume/End plan: what it is now, what will change."""

    name: str
    vas_device_id: str
    device_id: str | None
    vas_enabled_now: bool
    intent: str | None
    intent_models: int
    live_session: bool
    actions: list[str]
    vas_change: bool


class LifecyclePreflightResponse(BaseModel):
    action: str
    project: ProjectSummary | None
    allowed: bool
    blocked_reason: str | None = None
    cameras: list[LifecycleCamera]
    #: Site-wide effects, in plain words.
    effects: list[str]


class LifecycleResultResponse(BaseModel):
    action: str
    project: ProjectSummary
    complete: bool
    errors: list[str]
    cameras: list[LifecycleCamera]
    retention_paused: bool | None


class EndProjectRequest(BaseModel):
    confirm_name: str = Field(..., description="The project name, typed exactly")


class ProjectListResponse(BaseModel):
    items: list[ProjectSummary]
    active: ProjectSummary | None = Field(
        None, description="The current project (active, stopping, stopped or resuming), if any"
    )


class StartPreflightResponse(BaseModel):
    """What starting the next project would do, per camera.

    `cameras` is planned with the cameras enabled in VAS right now as the
    default pick; the dialog re-plans as the operator ticks.
    """

    can_proceed: bool
    blocked_reason: str | None = None
    blockers: list[str] = Field(
        default_factory=list,
        description="project_current (end it first), backup_unavailable",
    )
    current_project: ProjectSummary | None = None
    last_project: ProjectSummary | None = None
    cameras: list[LifecycleCamera]
    backup_dir: str
    effects: list[str]


class StartProjectRequest(BaseModel):
    """Start the next project. `confirm_name` must equal `name` exactly."""

    name: str = Field(min_length=3, max_length=200, description="Name of the NEW project")
    confirm_name: str = Field(min_length=3, max_length=200, description="Retype the name exactly")
    camera_ids: list[str] = Field(
        default_factory=list,
        description="VAS device ids of the cameras the new project runs; the rest are disabled",
    )
    allow_no_cameras: bool = Field(
        False,
        description="Start with no cameras at all. Without it an empty camera_ids is refused (422).",
    )


class ProjectJobStage(BaseModel):
    key: str
    label: str
    #: pending / running / done / failed / interrupted
    status: str


class ProjectJobResponse(BaseModel):
    """A Start/Stop/End/Resume running (or run) in the background."""

    id: uuid.UUID
    action: str
    #: queued / running / succeeded / failed / interrupted
    state: str
    stage: str | None
    stage_detail: str | None
    stages: list[ProjectJobStage]
    error_code: str | None
    error_message: str | None
    #: Cameras VAS would not switch, one line each.
    errors: list[str] = Field(default_factory=list)
    cameras: list[LifecycleCamera] = Field(default_factory=list)
    retention_paused: bool | None = None
    project_id: uuid.UUID | None
    project_name: str | None = None
    backup_path: str | None
    attempts: int
    can_retry: bool
    created_by: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ProjectJobsState(BaseModel):
    """What the Project tab needs on load: the running job, and the last one."""

    active: ProjectJobResponse | None
    latest: ProjectJobResponse | None


class ProjectMember(BaseModel):
    """A camera in the current project (an open membership)."""

    device_id: uuid.UUID
    vas_device_id: str | None
    name: str
    joined_at: datetime
    inferred: bool
    source: str


class ChangeCamerasPreflight(BaseModel):
    """What "Change cameras" would do, per camera; members as they are now."""

    project: ProjectSummary | None
    allowed: bool
    blocked_reason: str | None = None
    members: list[ProjectMember]
    cameras: list[LifecycleCamera]
    effects: list[str]


class ChangeCamerasRequest(BaseModel):
    """Add and/or remove cameras (VAS ids) of the active project."""

    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)
