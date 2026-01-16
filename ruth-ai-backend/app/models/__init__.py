"""SQLAlchemy models for Ruth AI Backend.

This module exports all database models for use throughout the application.
Models are designed to match the Ruth AI API Contract Specification exactly.
"""

from app.models.base import Base, TimestampMixin
from app.models.device import Device
from app.models.enums import (
    EvidenceStatus,
    EvidenceType,
    EventType,
    StreamState,
    ViolationStatus,
    ViolationType,
)
from app.models.event import Event
from app.models.evidence import Evidence
from app.models.stream_session import StreamSession
from app.models.violation import Violation

__all__ = [
    # Base
    "Base",
    "TimestampMixin",
    # Enums
    "StreamState",
    "EventType",
    "ViolationType",
    "ViolationStatus",
    "EvidenceType",
    "EvidenceStatus",
    # Models
    "Device",
    "StreamSession",
    "Event",
    "Violation",
    "Evidence",
]
