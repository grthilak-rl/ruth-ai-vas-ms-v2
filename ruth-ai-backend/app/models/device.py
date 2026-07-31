"""Device model for Ruth AI.

Represents a camera/device registered in the system.
Device IDs are VAS-owned identifiers (opaque UUIDs from VAS).

From API Contract Section 1.6 - Device Proxy Endpoints:
- Ruth AI proxies device information from VAS
- Device IDs are VAS-owned and treated as opaque by Ruth AI
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.stream_session import StreamSession
    from app.models.violation import Violation


class Device(Base, TimestampMixin):
    """Camera/device entity.

    A Device represents a camera registered in VAS and tracked by Ruth AI.
    The device_id is the VAS-assigned identifier (opaque to Ruth AI).

    Relationships:
    - Device → StreamSession (1:N): A device can have multiple stream sessions over time
    - Device → Event (1:N): Events are detected from this device's streams
    - Device → Violation (1:N): Violations are created from events on this device

    Indexes:
    - Primary key on id
    - Unique constraint on vas_device_id
    - Index on is_active for filtering active devices
    - Index on name for search/sorting
    """

    __tablename__ = "devices"

    # Primary key (Ruth AI internal ID)
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=generate_uuid,
    )

    # VAS device identifier (opaque, from VAS API)
    vas_device_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    # Human-readable name (from VAS, cached locally)
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    # Optional description
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Physical location of the camera
    location: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # Structured naming, mirrored from VAS on each sync (VAS phase 1).
    #
    # `name` above stays the stable identifier (CUG3PTZ10072). display_name is
    # DERIVED in VAS and stored here verbatim rather than recomputed, so there
    # is exactly one implementation of the naming rule. It is NULL for devices
    # last synced before this field existed — always read it as
    # `display_name or name`.
    #
    # These are read-only from Ruth's side in phase 1; editing lands later.
    manway: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    in_out: Mapped[str | None] = mapped_column(
        String(8),
        nullable=True,
    )
    display_name: Mapped[str | None] = mapped_column(
        String(400),
        nullable=True,
    )

    # Whether the device is active and available for streaming
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
    )

    # Last time we synced device info from VAS
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    stream_sessions: Mapped[list["StreamSession"]] = relationship(
        "StreamSession",
        back_populates="device",
        lazy="selectin",
        order_by="desc(StreamSession.started_at)",
    )

    events: Mapped[list["Event"]] = relationship(
        "Event",
        back_populates="device",
        lazy="noload",  # Events are high-volume; load explicitly
    )

    violations: Mapped[list["Violation"]] = relationship(
        "Violation",
        back_populates="device",
        lazy="noload",  # Load explicitly when needed
    )

    def __repr__(self) -> str:
        return f"<Device(id={self.id}, name={self.name}, is_active={self.is_active})>"
