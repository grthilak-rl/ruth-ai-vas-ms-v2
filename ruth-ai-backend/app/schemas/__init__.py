"""Pydantic schemas for Ruth AI Backend API."""

from app.schemas.analytics import (
    AnalyticsComparison,
    AnalyticsNotImplementedResponse,
    AnalyticsSummaryResponse,
    AnalyticsTotals,
    CameraBreakdown,
    DeviceAnalytics,
    DeviceStatusResponse,
    DeviceStatusSummary,
    ExportOptions,
    ExportRequest,
    ExportScope,
    StatusBreakdown,
    TimeRange,
    TimeSeriesBucket,
    TypeBreakdown,
    ViolationTrendBucket,
    ViolationTrendsResponse,
)
from app.schemas.models import ModelStatusInfo, ModelsStatusResponse
from app.schemas.device import (
    Device,
    DeviceDetailResponse,
    DeviceListResponse,
    DeviceStreaming,
    InferenceStartRequest,
    InferenceStartResponse,
    InferenceStopResponse,
)
from app.schemas.error import (
    ErrorResponse,
    ValidationErrorDetail,
    ValidationErrorResponse,
)
from app.schemas.event import (
    BoundingBoxInput,
    BoundingBoxResponse,
    EventIngestRequest,
    EventListResponse,
    EventQueryParams,
    EventResponse,
)
from app.schemas.evidence import (
    EvidenceResponse,
    SnapshotCreateRequest,
    SnapshotResponse,
    VideoEvidenceResponse,
)
from app.schemas.violation import (
    ViolationDetailResponse,
    ViolationEvidenceSummary,
    ViolationListResponse,
    ViolationQueryParams,
    ViolationResponse,
    ViolationStatusUpdateRequest,
)

__all__ = [
    # Device schemas
    "Device",
    "DeviceStreaming",
    "DeviceListResponse",
    "DeviceDetailResponse",
    "InferenceStartRequest",
    "InferenceStartResponse",
    "InferenceStopResponse",
    # Event schemas
    "BoundingBoxInput",
    "BoundingBoxResponse",
    "EventIngestRequest",
    "EventResponse",
    "EventListResponse",
    "EventQueryParams",
    # Violation schemas
    "ViolationResponse",
    "ViolationDetailResponse",
    "ViolationEvidenceSummary",
    "ViolationListResponse",
    "ViolationQueryParams",
    "ViolationStatusUpdateRequest",
    # Evidence schemas
    "EvidenceResponse",
    "SnapshotCreateRequest",
    "SnapshotResponse",
    "VideoEvidenceResponse",
    # Analytics schemas
    "AnalyticsComparison",
    "AnalyticsNotImplementedResponse",
    "AnalyticsSummaryResponse",
    "AnalyticsTotals",
    "CameraBreakdown",
    "DeviceAnalytics",
    "DeviceStatusResponse",
    "DeviceStatusSummary",
    "ExportOptions",
    "ExportRequest",
    "ExportScope",
    "StatusBreakdown",
    "TimeRange",
    "TimeSeriesBucket",
    "TypeBreakdown",
    "ViolationTrendBucket",
    "ViolationTrendsResponse",
    # Models schemas
    "ModelStatusInfo",
    "ModelsStatusResponse",
    # Error schemas
    "ErrorResponse",
    "ValidationErrorDetail",
    "ValidationErrorResponse",
]
