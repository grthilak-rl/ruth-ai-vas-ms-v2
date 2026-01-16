"""Violation model for Ruth AI.

Represents a confirmed or potential safety incident.
Violations are created when AI detects significant events.
Each Violation has a lifecycle: open → reviewed → resolved/dismissed.

From API Contract Section 3.2 - Violation Schema:
- Violations are derived from one or more events
- Status transitions are constrained (resolved is terminal)
- Evidence is linked asynchronously via VAS
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid
from app.models.enums import ViolationStatus, ViolationType

if TYPE_CHECKING:
    from app.models.device import Device
    from app.models.event import Event
    from app.models.evidence import Evidence
    from app.models.stream_session import StreamSession


class Violation(Base, TimestampMixin):
    """Safety violation entity.

    A Violation represents a detected safety incident that requires
    operator review. Violations are created when AI confidence exceeds
    the configured threshold for actionable event types (e.g., fall_detected).

    Status lifecycle:
    - open: New violation, not yet seen by operator
    - reviewed: Operator has viewed the violation
    - dismissed: Marked as false positive or not actionable
    - resolved: Incident has been handled (terminal state)

    Relationships:
    - Violation → Device (N:1): Violations belong to a device
    - Violation → StreamSession (N:1): Violations occur during a session
    - Violation → Event (1:N): One or more events trigger this violation
    - Violation → Evidence (1:N): Evidence records for this violation

    Indexes:
    - Primary key on id
    - Index on device_id for filtering by camera
    - Index on stream_session_id for session analysis
    - Index on status for filtering by lifecycle state
    - Index on type for filtering by violation type
    - Index on timestamp for time-range queries
    - Composite index on (status, timestamp) for dashboard (open violations)
    - Composite index on (device_id, status, timestamp) for per-camera dashboards
    """

    __tablename__ = "violations"

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

    stream_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stream_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Violation classification
    type: Mapped[ViolationType] = mapped_column(
        ENUM(
            ViolationType,
            name="violation_type",
            create_type=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        index=True,
    )

    status: Mapped[ViolationStatus] = mapped_column(
        ENUM(
            ViolationStatus,
            name="violation_status",
            create_type=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ViolationStatus.OPEN,
        nullable=False,
        index=True,
    )

    # Highest confidence score among triggering events (0.0 to 1.0)
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    # Timestamp when the violation was detected
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # Denormalized camera name for display (from device at creation time)
    camera_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
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

    # Bounding boxes from the primary detection (JSON array)
    bounding_boxes: Mapped[list[dict] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=list,
    )

    # Operator review information
    reviewed_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Operator notes (max 2000 chars per API contract)
    resolution_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Relationships
    device: Mapped["Device"] = relationship(
        "Device",
        back_populates="violations",
    )

    stream_session: Mapped["StreamSession | None"] = relationship(
        "StreamSession",
        back_populates="violations",
    )

    events: Mapped[list["Event"]] = relationship(
        "Event",
        back_populates="violation",
        lazy="selectin",
        foreign_keys="Event.violation_id",
    )

    evidence: Mapped[list["Evidence"]] = relationship(
        "Evidence",
        back_populates="violation",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Violation(id={self.id}, type={self.type}, status={self.status})>"
