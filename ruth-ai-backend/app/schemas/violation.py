"""Pydantic schemas for violations API.

From API Contract - Violation APIs.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.evidence import EvidenceResponse


class ViolationEvidenceSummary(BaseModel):
    """Summarized evidence for list views.

    Contains only the fields needed to display thumbnail/status in list views.
    Per F6 §3.4, evidence URLs are only valid when status = 'ready'.
    """

    snapshot_id: str | None = Field(None, description="VAS snapshot ID")
    snapshot_url: str | None = Field(None, description="Snapshot URL (if ready)")
    snapshot_status: str = Field(default="pending", description="Snapshot status")
    bookmark_id: str | None = Field(None, description="VAS bookmark ID")
    bookmark_url: str | None = Field(None, description="Bookmark URL (if ready)")
    bookmark_status: str = Field(default="pending", description="Bookmark status")
    bookmark_duration_seconds: int | None = Field(None, description="Bookmark duration")


class ViolationResponse(BaseModel):
    """Response schema for a single violation."""

    id: uuid.UUID = Field(..., description="Violation UUID")
    type: str = Field(..., description="Violation type (e.g., fall_detected)")
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


class ViolationQueryParams(BaseModel):
    """Query parameters for GET /api/v1/violations."""

    status: str | None = Field(None, description="Filter by status")
    device_id: uuid.UUID | None = Field(None, description="Filter by device")
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
