"""Pydantic schemas for violations API.

From API Contract - Violation APIs.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.dismiss_reasons import NOTE_REQUIRED_REASONS, DismissReason

from app.schemas.evidence import EvidenceResponse


class ViolationEvidenceSummary(BaseModel):
    """Summarized evidence for list views.

    Contains only the fields needed to display thumbnail/status in list views.
    Per F6 §3.4, evidence URLs are only valid when status = 'ready'.
    """

    #: The frame the model actually inferred, saved by Ruth. Prefer this over
    #: the snapshot wherever the bounding boxes are drawn: the snapshot is a
    #: later capture, so the boxes do not line up with it.
    frame_url: str | None = Field(None, description="Inferred-frame URL (if ready)")
    frame_status: str | None = Field(
        None,
        description="Inferred-frame status, or null when no frame was saved",
    )
    #: The inferred frame cropped around the detection, for cards.
    frame_thumb_url: str | None = Field(
        None, description="Cropped, annotated card thumbnail of the inferred frame (if ready)"
    )
    snapshot_id: str | None = Field(None, description="VAS snapshot ID")
    snapshot_url: str | None = Field(None, description="Snapshot URL (if ready)")
    snapshot_status: str = Field(default="pending", description="Snapshot status")
    bookmark_id: str | None = Field(None, description="VAS bookmark ID")
    bookmark_url: str | None = Field(None, description="Bookmark URL (if ready)")
    #: null when no clip was ever requested — distinct from "pending", which
    #: means one is genuinely being prepared. The UI must not show a spinner
    #: for null, which it did for every violation before clips existed.
    bookmark_status: str | None = Field(None, description="Bookmark status, or null if none requested")
    bookmark_duration_seconds: int | None = Field(None, description="Bookmark duration")


class ViolationResponse(BaseModel):
    """Response schema for a single violation."""

    id: uuid.UUID = Field(..., description="Violation UUID")
    type: str = Field(..., description="Violation type (e.g., fall_detected)")
    type_detail: str | None = Field(
        None,
        description="Specific type the model reported (e.g. missing_gloves); null when it reported nothing more specific",
    )
    type_label: str = Field(..., description="Human label for the family (e.g. PPE Violation)")
    detail_label: str | None = Field(
        None, description="Human label for the specific type (e.g. Missing gloves), or null"
    )
    severity: str = Field(
        "medium",
        description="Firing rule's severity from its manifest: critical, high, medium or low",
    )
    camera_display_name: str | None = Field(
        None, description="Camera display name (e.g. REFORMER1_OUT_75081), when known"
    )
    camera_area: str | None = Field(None, description="Camera's area / manway (e.g. REFORMER1)")
    camera_in_out: str | None = Field(None, description="IN or OUT side of the area")
    dismiss_reason: str | None = Field(
        None, description="Why it was dismissed (object, wrong_person, ppe_worn, other_false_alarm, duplicate)"
    )
    status: str = Field(..., description="Violation status")
    camera_id: uuid.UUID = Field(..., description="Device/camera UUID")
    camera_name: str = Field(..., description="Camera display name")
    confidence: float = Field(..., description="Detection confidence (0.0-1.0)")
    timestamp: datetime = Field(..., description="Violation detection timestamp")
    model_id: str = Field(..., description="AI model identifier")
    model_version: str = Field(..., description="AI model version")
    bounding_boxes: list[dict] | None = Field(
        None, description="Detection bounding boxes"
    )
    reviewed_by: str | None = Field(None, description="Reviewer identifier")
    reviewed_at: datetime | None = Field(None, description="Review timestamp")
    resolution_notes: str | None = Field(None, description="Resolution notes")
    evidence: ViolationEvidenceSummary | None = Field(
        None, description="Evidence summary for list display"
    )
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record update timestamp")

    model_config = {"from_attributes": True}


class ViolationDetailResponse(BaseModel):
    """Response schema for GET /api/v1/violations/{id} with evidence.

    Note: Uses ViolationEvidenceSummary (same as list) for frontend compatibility.
    """

    id: uuid.UUID = Field(..., description="Violation UUID")
    type: str = Field(..., description="Violation type")
    type_detail: str | None = Field(
        None,
        description="Specific type the model reported (e.g. missing_gloves); null when it reported nothing more specific",
    )
    type_label: str = Field(..., description="Human label for the family (e.g. PPE Violation)")
    detail_label: str | None = Field(
        None, description="Human label for the specific type (e.g. Missing gloves), or null"
    )
    severity: str = Field(
        "medium",
        description="Firing rule's severity from its manifest: critical, high, medium or low",
    )
    camera_display_name: str | None = Field(
        None, description="Camera display name (e.g. REFORMER1_OUT_75081), when known"
    )
    camera_area: str | None = Field(None, description="Camera's area / manway (e.g. REFORMER1)")
    camera_in_out: str | None = Field(None, description="IN or OUT side of the area")
    dismiss_reason: str | None = Field(
        None, description="Why it was dismissed (object, wrong_person, ppe_worn, other_false_alarm, duplicate)"
    )
    status: str = Field(..., description="Violation status")
    camera_id: uuid.UUID = Field(..., description="Device/camera UUID")
    camera_name: str = Field(..., description="Camera display name")
    confidence: float = Field(..., description="Detection confidence")
    timestamp: datetime = Field(..., description="Violation timestamp")
    model_id: str = Field(..., description="AI model identifier")
    model_version: str = Field(..., description="AI model version")
    bounding_boxes: list[dict] | None = Field(None, description="Bounding boxes")
    reviewed_by: str | None = Field(None, description="Reviewer identifier")
    reviewed_at: datetime | None = Field(None, description="Review timestamp")
    resolution_notes: str | None = Field(None, description="Resolution notes")
    evidence: ViolationEvidenceSummary | None = Field(
        None, description="Evidence summary for display"
    )
    event_count: int = Field(default=0, description="Number of triggering events")
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record update timestamp")


class ViolationListResponse(BaseModel):
    """Response schema for GET /api/v1/violations.

    Aligned with F6 ViolationsListResponse interface.
    """

    items: list[ViolationResponse] = Field(..., description="List of violations")
    total: int = Field(..., description="Total count of violations")


class ViolationTypeDetailOption(BaseModel):
    """One specific type within a family, for the type filter."""

    type_detail: str | None = Field(
        ..., description="Specific type, or null for violations with none"
    )
    label: str = Field(..., description="Label for the option")
    count: int = Field(..., description="Violations with this type")


class ViolationTypeOption(BaseModel):
    """A violation family and the specific types seen under it."""

    type: str = Field(..., description="Family (violation type enum value)")
    label: str = Field(..., description="Family label")
    count: int = Field(..., description="Violations in the family")
    details: list[ViolationTypeDetailOption] = Field(
        default_factory=list,
        description="Specific types seen in this family; empty when it has none",
    )


class ViolationTypesResponse(BaseModel):
    """Response schema for GET /api/v1/violations/types."""

    items: list[ViolationTypeOption] = Field(..., description="Families, largest first")


class IncidentResponse(BaseModel):
    """Repeated violations of one type on one camera, shown as one card."""

    incident_id: str = Field(..., description="Stable while the incident grows")
    camera_id: uuid.UUID = Field(..., description="Device/camera UUID")
    camera_name: str = Field(..., description="Camera name (its number)")
    camera_display_name: str | None = Field(None, description="Camera display name")
    camera_area: str | None = Field(None, description="Camera's area / manway")
    camera_in_out: str | None = Field(None, description="IN or OUT")
    type: str = Field(..., description="Family")
    type_detail: str | None = Field(None, description="Specific type, or null")
    type_label: str = Field(..., description="Family label")
    detail_label: str | None = Field(None, description="Specific label, or null")
    severity: str = Field(..., description="Worst member severity")
    count: int = Field(..., description="Violations in the incident (after filters)")
    open_count: int = Field(..., description="Of those, still open")
    first_at: datetime = Field(..., description="First violation")
    last_at: datetime = Field(..., description="Latest violation")
    has_clip: bool = Field(..., description="At least one member has a ready clip")
    violation_ids: list[uuid.UUID] = Field(..., description="Members, newest first")
    open_violation_ids: list[uuid.UUID] = Field(
        ..., description="Members still open, newest first: what group actions apply to"
    )
    representative: ViolationResponse = Field(..., description="The latest member")


class SeverityCounts(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


class IncidentSummary(BaseModel):
    """The summary strip: totals for the current filters."""

    open_violations: int = Field(..., description="Matching violations still open")
    violations_by_severity: SeverityCounts
    incidents_by_severity: SeverityCounts
    cameras: int = Field(..., description="Distinct cameras with matching violations")
    top_area: str | None = Field(None, description="Area with the most matching violations")
    top_area_violations: int = Field(0, description="Violations in that area")


class IncidentListResponse(BaseModel):
    """Response schema for GET /api/v1/violations/incidents."""

    items: list[IncidentResponse] = Field(..., description="Incidents, most recently active first")
    total: int = Field(..., description="Total incidents matching the filters")
    violations_total: int = Field(..., description="Violations those incidents contain")
    gap_minutes: int = Field(..., description="Grouping window in force")
    max_span_minutes: int = Field(..., description="Longest incident span in force")
    summary: IncidentSummary = Field(..., description="Totals for the current filters (all pages)")


class ViolationBulkRequest(BaseModel):
    """Request schema for POST /api/v1/violations/bulk."""

    ids: list[uuid.UUID] = Field(..., min_length=1, max_length=1000, description="Violations to change")
    action: Literal["review", "dismiss"] = Field(..., description="Mark reviewed, or dismiss")
    dismiss_reason: DismissReason | None = Field(None, description="Required to dismiss")
    note: str | None = Field(None, max_length=2000, description="Required for 'other_false_alarm'")
    reviewed_by: str | None = Field(None, max_length=255, description="Operator identifier")

    @model_validator(mode="after")
    def _reason_rules(self) -> "ViolationBulkRequest":
        if self.action == "dismiss" and self.dismiss_reason is None:
            raise ValueError("dismiss_reason is required to dismiss")
        if self.dismiss_reason in NOTE_REQUIRED_REASONS and not (self.note or "").strip():
            raise ValueError(f"a note is required for '{self.dismiss_reason.value}'")
        return self


class BulkSkipped(BaseModel):
    id: uuid.UUID
    reason: str = Field(..., description="not_found, terminal_state or invalid_transition")
    status: str | None = Field(None, description="Its current status, when found")


class LabellingExport(BaseModel):
    exported: int = Field(0, description="Frames copied to the labelling set")
    no_frame: int = Field(0, description="False alarms without a saved inferred frame")
    failed: int = Field(0, description="Copies that failed (logged)")
    capped: int = Field(0, description="Skipped over the per-incident cap")


class ViolationBulkResponse(BaseModel):
    """Response schema for POST /api/v1/violations/bulk."""

    updated: list[uuid.UUID] = Field(..., description="Violations changed")
    skipped: list[BulkSkipped] = Field(..., description="Violations left as they were, and why")
    labelling: LabellingExport | None = Field(
        None, description="Labelling export, for false-alarm dismissals"
    )


class ViolationQueryParams(BaseModel):
    """Query parameters for GET /api/v1/violations."""

    status: str | None = Field(None, description="Filter by status")
    camera_id: uuid.UUID | None = Field(None, description="Filter by camera ID")
    since: datetime | None = Field(None, description="Filter by timestamp (after)")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")


class ViolationStatusUpdateRequest(BaseModel):
    """Request schema for PATCH /api/v1/violations/{id}.

    Updates violation status (mark reviewed, dismiss, resolve).
    """

    status: str = Field(..., description="New status: 'reviewed', 'dismissed', or 'resolved'")
    reviewed_by: str | None = Field(None, description="Operator/reviewer identifier")
    resolution_notes: str | None = Field(None, description="Notes about resolution or dismissal")
    dismiss_reason: DismissReason | None = Field(
        None, description="Why it is dismissed; false-alarm reasons export the frame for labelling"
    )
