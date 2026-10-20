"""SQLAlchemy models for Ruth AI Backend.

This module exports all database models for use throughout the application.
Models are designed to match the Ruth AI API Contract Specification exactly.
"""

from app.models.app_setting import SHIFT_SCHEDULE_KEY, AppSetting
from app.models.archive import (
    BookmarkAnalysisArchive,
    EventArchive,
    EvidenceArchive,
    StreamSessionArchive,
    ViolationArchive,
)
from app.models.base import Base, TimestampMixin
from app.models.bookmark_analysis import BookmarkAnalysis
from app.models.device import Device
from app.models.enums import (
    BookmarkAnalysisState,
    EvidenceStatus,
    EvidenceType,
    EventType,
    StreamState,
    ViolationStatus,
    ViolationType,
)
from app.models.event import Event
from app.models.evidence import Evidence
from app.models.inference_intent import (
    INTENT_ACTIVE,
    INTENT_OFF,
    INTENT_SUSPENDED,
    DeviceInferenceIntent,
)
from app.models.model_store import ModelStoreFile, ModelStoreModel, ModelStoreUpload
from app.models.project import (
    PROJECT_START_LOCK_KEY,
    PROJECT_STATE_ACTIVE,
    PROJECT_STATE_ARCHIVED,
    PROJECT_STATES,
    Project,
)
from app.models.stream_session import StreamSession
from app.models.violation import Violation

__all__ = [
    # Base
    "Base",
    "TimestampMixin",
    # Enums
    "BookmarkAnalysisState",
    "StreamState",
    "EventType",
    "ViolationType",
    "ViolationStatus",
    "EvidenceType",
    "EvidenceStatus",
    # Models
    "AppSetting",
    "SHIFT_SCHEDULE_KEY",
    "BookmarkAnalysis",
    "Device",
    "StreamSession",
    "Event",
    "Violation",
    "Evidence",
    "DeviceInferenceIntent",
    "INTENT_ACTIVE",
    "INTENT_OFF",
    "INTENT_SUSPENDED",
    "ModelStoreModel",
    "ModelStoreFile",
    "ModelStoreUpload",
    # Projects
    "Project",
    "PROJECT_STATE_ACTIVE",
    "PROJECT_STATE_ARCHIVED",
    "PROJECT_STATES",
    "PROJECT_START_LOCK_KEY",
    # Archive tables
    "ViolationArchive",
    "EventArchive",
    "EvidenceArchive",
    "StreamSessionArchive",
    "BookmarkAnalysisArchive",
]
