"""Request and response shapes for the bulk evidence export."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ViolationStatus, ViolationType


class ExportFilters(BaseModel):
    """The Violations page's filters, named as the page's query params are.

    Sent as a body rather than a query string because an export also carries
    a selection, and a list of incident keys does not belong in a URL.
    """

    statuses: list[ViolationStatus] | None = Field(
        default=None, description="Review states to include, dismissed included"
    )
    camera_id: uuid.UUID | None = None
    since: datetime | None = None
    until: datetime | None = None
    violation_type: ViolationType | None = None
    type_detail: str | None = Field(default=None, max_length=64)
    severities: list[str] | None = None
    area: str | None = Field(default=None, max_length=64)


class ExportRequest(BaseModel):
    filters: ExportFilters = Field(default_factory=ExportFilters)
    scope: str = Field(
        default="all",
        pattern="^(all|one_per_incident)$",
        description=(
            "all: every matching violation. one_per_incident: the "
            "highest-confidence member of each incident that has an inferred "
            "frame, which is usually what a dataset wants."
        ),
    )
    annotated: bool = Field(
        default=False, description="Also include copies with the boxes drawn on"
    )
    include_snapshots: bool = Field(
        default=False,
        description=(
            "For violations with no inferred frame, fall back to the scene "
            "snapshot. Off by default: it is a later capture whose boxes do "
            "not line up, it is ~3x the size, and each one is a separate "
            "request to VAS."
        ),
    )
    incident_ids: list[str] | None = Field(
        default=None,
        description=(
            "Export only these incidents, all their members included. The "
            "filters must be the same ones the list was showing, because "
            "incident keys are derived from the grouping."
        ),
    )


class ExportPreview(BaseModel):
    """What an export would contain, before committing to building it."""

    violations_matching_filters: int
    violations_in_export: int
    without_inferred_frame: int
    estimated_bytes: int
    max_violations: int
    within_cap: bool


class ExportJob(BaseModel):
    id: uuid.UUID
    status: str
    error: str | None = None
    total: int
    done: int
    images: int
    without_inferred_frame: int = Field(validation_alias="no_frame")
    skipped: int
    size_bytes: int | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class ExportJobList(BaseModel):
    items: list[ExportJob]
    total: int
