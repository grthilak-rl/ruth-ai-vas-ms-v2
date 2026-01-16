"""Event model for Ruth AI.

Represents a single AI detection output (raw inference result).
Events are high-volume, raw outputs from AI models.
Multiple events may be aggregated into a single Violation.

From API Contract Section 3.1 - Event Schema:
- Events are created for every AI inference that produces a detection
- Events are retained indefinitely (per confirmed design decision)
- Events link to violations for traceability
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid
from app.models.enums import EventType

if TYPE_CHECKING:
    from app.models.device import Device
    from app.models.stream_session import StreamSession
    from app.models.violation import Violation


class Event(Base, TimestampMixin):
    """AI detection event entity.

    An Event represents a single frame inference result from the AI Runtime.
    Events are high-volume (potentially 10 per second per camera) and are
    retained indefinitely for audit and analytics purposes.

    Key fields from API Contract:
    - event_type: fall_detected, no_fall, person_detected, unknown
    - confidence: 0.0 to 1.0
    - bounding_boxes: JSON array of detected objects
    - frame_id: Reference to the analyzed frame

    Relationships:
    - Event → Device (N:1): Events belong to a device
    - Event → StreamSession (N:1): Events occur during a session
    - Event → Violation (N:1): Events may trigger a violation

    Indexes:
    - Primary key on id
    - Index on device_id for filtering by camera
    - Index on stream_session_id for session analysis
    - Index on violation_id for linking events to violations
    - Index on event_type for filtering by detection type
    - Index on timestamp for time-range queries
    - Composite index on (device_id, timestamp) for dashboard queries
    - Composite index on (device_id, event_type, timestamp) for analytics
    """

    __tablename__ = "events"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=generate_uuid,
    )

    # Foreign keys
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    stream_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stream_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    violation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("violations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Event classification
    event_type: Mapped[EventType] = mapped_column(
        ENUM(
            EventType,
            name="event_type",
            create_type=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        index=True,
    )

    # Model confidence score (0.0 to 1.0)
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    # Timestamp when the event occurred (frame capture time)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # AI model information
    model_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    model_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    # Bounding boxes for detected objects (JSON array)
    # Structure: [{"x": int, "y": int, "width": int, "height": int, "label": str, "confidence": float}]
    bounding_boxes: Mapped[list[dict] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=list,
    )

    # Frame reference (internal identifier for debugging)
    frame_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # Processing metrics
    inference_time_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # Relationships
    device: Mapped["Device"] = relationship(
        "Device",
        back_populates="events",
    )

    stream_session: Mapped["StreamSession | None"] = relationship(
        "StreamSession",
        back_populates="events",
    )

    violation: Mapped["Violation | None"] = relationship(
        "Violation",
        back_populates="events",
        foreign_keys=[violation_id],
    )

    def __repr__(self) -> str:
        return f"<Event(id={self.id}, type={self.event_type}, confidence={self.confidence})>"
