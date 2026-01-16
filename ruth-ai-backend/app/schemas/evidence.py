"""Pydantic schemas for evidence API endpoints.

From API Contract - Violation Evidence APIs.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class EvidenceResponse(BaseModel):
    """Response schema for evidence item."""

    id: uuid.UUID = Field(..., description="Evidence UUID")
    violation_id: uuid.UUID = Field(..., description="Associated violation UUID")
    evidence_type: str = Field(..., description="Evidence type (snapshot, bookmark)")
    status: str = Field(..., description="Evidence status")
    vas_snapshot_id: str | None = Field(None, description="VAS snapshot ID")
    vas_bookmark_id: str | None = Field(None, description="VAS bookmark ID")
    bookmark_duration_seconds: int | None = Field(
        None, description="Bookmark duration in seconds"
    )
    requested_at: datetime = Field(..., description="Evidence request timestamp")
    ready_at: datetime | None = Field(None, description="Evidence ready timestamp")
    error_message: str | None = Field(None, description="Error message if failed")
    created_at: datetime = Field(..., description="Record creation timestamp")

    model_config = {"from_attributes": True}


class SnapshotCreateRequest(BaseModel):
    """Request schema for POST /api/v1/violations/{id}/snapshot."""

    # Currently no additional parameters needed
    # VAS snapshot is triggered automatically for the violation
    pass


class SnapshotResponse(BaseModel):
    """Response schema for snapshot creation."""

    evidence_id: uuid.UUID = Field(..., description="Evidence UUID")
    violation_id: uuid.UUID = Field(..., description="Violation UUID")
    status: str = Field(..., description="Evidence status")
    vas_snapshot_id: str | None = Field(None, description="VAS snapshot ID")
    requested_at: datetime = Field(..., description="Request timestamp")


class VideoEvidenceResponse(BaseModel):
    """Response schema for GET /api/v1/violations/{id}/video."""

    evidence_id: uuid.UUID = Field(..., description="Evidence UUID")
    violation_id: uuid.UUID = Field(..., description="Violation UUID")
    status: str = Field(..., description="Evidence status (ready, processing, etc.)")
    vas_bookmark_id: str | None = Field(None, description="VAS bookmark ID")
    duration_seconds: int | None = Field(None, description="Video duration")
    video_url: str | None = Field(
        None, description="Video URL (available when ready)"
    )
    requested_at: datetime = Field(..., description="Request timestamp")
    ready_at: datetime | None = Field(None, description="Ready timestamp")
