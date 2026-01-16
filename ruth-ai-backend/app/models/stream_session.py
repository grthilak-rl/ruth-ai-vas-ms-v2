"""StreamSession model for Ruth AI.

Represents an active or historical streaming session for a device.
A StreamSession tracks the lifecycle of AI inference on a camera stream.

From API Contract Section 1.7 - Streaming Control Endpoints:
- POST /api/v1/devices/{id}/start-inference creates a new session
- POST /api/v1/devices/{id}/stop-inference ends the session
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid
from app.models.enums import StreamState

if TYPE_CHECKING:
    from app.models.device import Device
    from app.models.event import Event
    from app.models.violation import Violation


class StreamSession(Base, TimestampMixin):
    """Streaming session entity.

    A StreamSession represents a period during which AI inference is
    active on a device's video stream. Sessions track:
    - Which model is being used
    - Inference parameters (FPS, confidence threshold)
    - Stream state lifecycle
    - Start/end timestamps

    Relationships:
    - StreamSession → Device (N:1): Many sessions belong to one device
    - StreamSession → Event (1:N): Events are detected during this session
    - StreamSession → Violation (1:N): Violations are created during this session

    Indexes:
    - Primary key on id
    - Foreign key index on device_id
    - Index on state for filtering active sessions
    - Index on started_at for time-range queries
    - Composite index on (device_id, state) for finding active sessions per device
    """

    __tablename__ = "stream_sessions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=generate_uuid,
    )

    # Foreign key to device
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # VAS stream identifier (from VAS when stream is started)
    vas_stream_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    # AI model configuration
    model_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    # Inference parameters
    inference_fps: Mapped[int] = mapped_column(
        Integer,
        default=10,
        nullable=False,
    )

    confidence_threshold: Mapped[float] = mapped_column(
        Float,
        default=0.7,
        nullable=False,
    )

    # Stream state
    state: Mapped[StreamState] = mapped_column(
        ENUM(
            StreamState,
            name="stream_state",
            create_type=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        default=StreamState.STARTING,
        nullable=False,
        index=True,
    )

    # Timestamps for session lifecycle
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Error information if state is ERROR
    error_message: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    # Session statistics (updated periodically)
    frames_processed: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    events_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    violations_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # Relationships
    device: Mapped["Device"] = relationship(
        "Device",
        back_populates="stream_sessions",
    )

    events: Mapped[list["Event"]] = relationship(
        "Event",
        back_populates="stream_session",
        lazy="noload",
    )

    violations: Mapped[list["Violation"]] = relationship(
        "Violation",
        back_populates="stream_session",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<StreamSession(id={self.id}, device_id={self.device_id}, state={self.state})>"
