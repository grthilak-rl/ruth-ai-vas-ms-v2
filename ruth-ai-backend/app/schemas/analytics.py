"""Pydantic schemas for analytics API endpoints.

From API Contract - Analytics APIs.
Aligned with F6 §6 Analytics Domain and analytics-design.md Section 8.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AnalyticsNotImplementedResponse(BaseModel):
    """Response for unimplemented analytics endpoints."""

    message: str = Field(
        default="Analytics endpoints not yet implemented",
        description="Status message",
    )
    endpoint: str = Field(..., description="Requested endpoint")
    phase: str = Field(default="Phase 4", description="Implementation phase")


class TimeRange(BaseModel):
    """Time range for analytics queries."""

    from_: datetime = Field(..., alias="from", description="Start of time range")
    to: datetime = Field(..., description="End of time range")

    class Config:
        populate_by_name = True


class AnalyticsTotals(BaseModel):
    """Analytics totals breakdown.

    Aligned with F6 §6.1 AnalyticsTotals interface and analytics-design.md §8.1.
    """

    violations_total: int = Field(default=0, description="Total violation count")
    violations_open: int = Field(default=0, description="Open violations count")
    violations_reviewed: int = Field(default=0, description="Reviewed violations count")
    violations_dismissed: int = Field(
        default=0, description="Dismissed violations count"
    )
    violations_resolved: int = Field(default=0, description="Resolved violations count")
    cameras_active: int = Field(default=0, description="Active cameras count")
    cameras_total: int = Field(default=0, description="Total cameras count")


class AnalyticsComparison(BaseModel):
    """Comparison to previous period."""

    violations_total_change: int = Field(
        default=0, description="Change in total violations vs previous period"
    )
    violations_total_change_percent: float = Field(
        default=0.0, description="Percentage change vs previous period"
    )


class CameraBreakdown(BaseModel):
    """Per-camera violation breakdown."""

    camera_id: str = Field(..., description="Camera UUID")
    camera_name: str = Field(..., description="Camera name")
    violations_total: int = Field(default=0, description="Total violations")
    violations_open: int = Field(default=0, description="Open violations")
    violations_reviewed: int = Field(default=0, description="Reviewed violations")
    violations_dismissed: int = Field(default=0, description="Dismissed violations")
    violations_resolved: int = Field(default=0, description="Resolved violations")


class TypeBreakdown(BaseModel):
    """Violation type breakdown."""

    type: str = Field(..., description="Violation type identifier")
    type_display: str = Field(..., description="Human-readable type name")
    count: int = Field(..., description="Number of violations")
    percentage: float = Field(..., description="Percentage of total (0-100)")


class StatusBreakdown(BaseModel):
    """Violation status breakdown."""

    status: str = Field(..., description="Violation status")
    count: int = Field(..., description="Number of violations")
    percentage: float = Field(..., description="Percentage of total (0-100)")


class TimeSeriesBucket(BaseModel):
    """Time series data bucket."""

    bucket: datetime = Field(..., description="Time bucket timestamp")
    total: int = Field(default=0, description="Total violations in this bucket")
    by_type: dict[str, int] = Field(
        default_factory=dict, description="Breakdown by type"
    )


class AnalyticsSummaryResponse(BaseModel):
    """Response schema for GET /api/v1/analytics/summary.

    Aligned with F6 §6.1 AnalyticsSummaryResponse interface and analytics-design.md §8.1.
    """

    time_range: TimeRange = Field(..., description="Query time range")
    totals: AnalyticsTotals = Field(..., description="Aggregated counts")
    comparison: AnalyticsComparison | None = Field(
        None, description="Comparison to previous period"
    )
    by_camera: list[CameraBreakdown] = Field(
        default_factory=list, description="Per-camera breakdown"
    )
    by_type: list[TypeBreakdown] = Field(
        default_factory=list, description="By violation type"
    )
    by_status: list[StatusBreakdown] = Field(
        default_factory=list, description="By status"
    )
    time_series: list[TimeSeriesBucket] = Field(
        default_factory=list, description="Time series data"
    )
    generated_at: datetime = Field(..., description="When summary was computed")


# Violations Trends API (§8.2)


class ViolationTrendBucket(BaseModel):
    """Trend data bucket with status breakdown."""

    bucket: datetime = Field(..., description="Time bucket timestamp")
    total: int = Field(default=0, description="Total violations in this bucket")
    by_type: dict[str, int] = Field(
        default_factory=dict, description="Breakdown by type"
    )
    by_status: dict[str, int] = Field(
        default_factory=dict, description="Breakdown by status"
    )


class ViolationTrendsResponse(BaseModel):
    """Response for GET /api/v1/analytics/violations/trends."""

    time_range: TimeRange = Field(..., description="Query time range")
    granularity: Literal["minute", "hour", "day"] = Field(
        ..., description="Time bucket granularity"
    )
    data: list[ViolationTrendBucket] = Field(..., description="Trend data")
    generated_at: datetime = Field(..., description="When data was computed")


# Device Status API (§8.2)


class DeviceAnalytics(BaseModel):
    """Analytics for a single device."""

    camera_id: str = Field(..., description="Camera UUID")
    camera_name: str = Field(..., description="Camera name")
    violations_total: int = Field(default=0, description="Total violations")
    violations_by_status: dict[str, int] = Field(
        default_factory=dict, description="Violations by status"
    )
    violations_by_type: dict[str, int] = Field(
        default_factory=dict, description="Violations by type"
    )
    avg_confidence: float = Field(default=0.0, description="Average confidence score")
    last_violation_at: datetime | None = Field(
        None, description="Timestamp of last violation"
    )


class DeviceStatusSummary(BaseModel):
    """Overall device status summary."""

    total_violations: int = Field(default=0, description="Total violations")
    total_cameras: int = Field(default=0, description="Total cameras")
    active_cameras: int = Field(default=0, description="Active cameras")


class DeviceStatusResponse(BaseModel):
    """Response for GET /api/v1/analytics/devices/status."""

    time_range: TimeRange = Field(..., description="Query time range")
    devices: list[DeviceAnalytics] = Field(..., description="Per-device analytics")
    summary: DeviceStatusSummary = Field(..., description="Overall summary")
    generated_at: datetime = Field(..., description="When data was computed")


# Export API (§8.2)


class ExportScope(BaseModel):
    """Scope definition for exports."""

    all: bool = Field(default=True, description="Export all violations")
    camera_ids: list[str] = Field(default_factory=list, description="Filter by cameras")
    violation_types: list[str] = Field(
        default_factory=list, description="Filter by types"
    )
    statuses: list[str] = Field(default_factory=list, description="Filter by statuses")


class ExportOptions(BaseModel):
    """Export format-specific options."""

    include_headers: bool = Field(default=True, description="Include column headers")
    include_timestamps: bool = Field(
        default=True, description="Include ISO 8601 timestamps"
    )
    include_raw_confidence: bool = Field(
        default=False, description="Include raw confidence scores"
    )
    include_evidence_urls: bool = Field(
        default=False, description="Include evidence URLs"
    )
    include_bounding_boxes: bool = Field(
        default=False, description="Include bounding box coordinates"
    )


class ExportRequest(BaseModel):
    """Request for POST /api/v1/analytics/export."""

    format: Literal["csv", "xlsx", "pdf"] = Field(..., description="Export format")
    time_range: TimeRange = Field(..., description="Time range to export")
    scope: ExportScope = Field(
        default_factory=ExportScope, description="Data scope filters"
    )
    options: ExportOptions = Field(
        default_factory=ExportOptions, description="Format-specific options"
    )
