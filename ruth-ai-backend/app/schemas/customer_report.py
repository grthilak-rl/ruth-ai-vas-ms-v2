"""Customer report (PDF) and report branding API schemas."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

GALLERY_SIZES = (6, 12, 18, 24)


class CustomerReportRequest(BaseModel):
    """POST /admin/customer-reports."""

    format: Literal["pdf"] = "pdf"
    preset: Literal["daily", "weekly", "custom"]
    #: Daily: the shift day. Weekly: the last of its 7 shift days.
    day: date | None = None
    #: Custom: local dates, both included.
    start: date | None = None
    end: date | None = None
    mode: Literal["all", "verified"] = "all"
    gallery: bool = True
    gallery_size: int = Field(default=12, ge=1, le=max(GALLERY_SIZES))
    #: Incident keys an admin removed from the gallery; the next fill in.
    gallery_exclude: list[str] = Field(default_factory=list, max_length=500)


class GalleryCandidate(BaseModel):
    key: str
    #: The violation whose saved frame represents the incident, if any;
    #: its thumbnail is /api/v1/violations/{id}/frame/thumb.
    violation_id: uuid.UUID | None
    area: str
    camera: str
    type_label: str
    severity: str
    #: In the site's time zone, e.g. "Wed 28 Oct, 07:05".
    started: str
    minutes: int
    detections: int


class GalleryPreview(BaseModel):
    items: list[GalleryCandidate]
    #: Incidents in the period, before any were removed.
    incidents: int


class CustomerReportJob(BaseModel):
    id: uuid.UUID
    status: str
    error: str | None = None
    stage: str | None = None
    done: int
    total: int
    format: str
    preset: str
    mode: str
    period_start: datetime
    period_end: datetime
    period_label: str
    options: dict
    filename: str | None = None
    size_bytes: int | None = None
    incidents: int | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None

    model_config = {"from_attributes": True}


class CustomerReportList(BaseModel):
    items: list[CustomerReportJob]
    total: int


class CustomerReportDefaults(BaseModel):
    """What the Export page needs to offer sensible periods."""

    timezone: str
    #: "07:00" when report days follow the first shift, else "00:00".
    day_start: str
    #: The most recent shift day that has ended.
    last_complete_day: date
    project_started_on: date | None
    max_custom_days: int
    retention_days: int
    gallery_sizes: list[int]
    default_gallery_size: int


class ReportBrandingOut(BaseModel):
    customer_name: str | None
    has_logo: bool
    updated_by: str | None = None
    updated_at: datetime | None = None


class ReportBrandingIn(BaseModel):
    customer_name: str | None = Field(default=None, max_length=120)
