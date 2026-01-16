"""Evidence model for Ruth AI.

Represents evidence (snapshots and bookmarks) captured via VAS when a violation is detected.
Evidence is created asynchronously and linked to violations.

From API Contract Section 3.3 - Evidence Schema:
- One Violation → Many Evidence records (1:N)
- Evidence types: snapshot (image), bookmark (video clip)
- Evidence status: pending → processing → ready/failed
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid
from app.models.enums import EvidenceStatus, EvidenceType

if TYPE_CHECKING:
    from app.models.violation import Violation


class Evidence(Base, TimestampMixin):
    """Evidence entity for violations.

    Evidence contains references to snapshots and video bookmarks
    created via VAS when a violation is detected. Evidence is created
    asynchronously and may take time to become ready.

    One Violation can have multiple Evidence records:
    - Typically one snapshot and one bookmark per violation
    - Multiple evidence records possible for re-captures or retries

    Evidence workflow:
    1. Violation detected → Evidence record created with status=pending
    2. VAS API called → status=processing
    3. VAS completes → status=ready (with VAS IDs)
    4. If VAS fails → status=failed (manual intervention required)

    Indexes:
    - Primary key on id
    - Index on violation_id for querying evidence by violation
    - Index on status for finding pending/failed evidence
    - Index on evidence_type for filtering by type
    - Composite index on (violation_id, evidence_type) for unique evidence per type
    """

    __tablename__ = "evidence"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=generate_uuid,
    )

    # Foreign key to violation
    violation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("violations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Evidence classification
    evidence_type: Mapped[EvidenceType] = mapped_column(
        ENUM(
            EvidenceType,
            name="evidence_type",
            create_type=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        index=True,
    )

    status: Mapped[EvidenceStatus] = mapped_column(
        ENUM(
            EvidenceStatus,
            name="evidence_status",
            create_type=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        default=EvidenceStatus.PENDING,
        nullable=False,
        index=True,
    )

    # VAS identifiers (set when VAS responds)
    vas_snapshot_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    vas_bookmark_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # For bookmarks: duration in seconds (default: 15 = 5 before + 10 after)
    bookmark_duration_seconds: Mapped[int | None] = mapped_column(
        Integer,
        default=15,
        nullable=True,
    )

    # Timestamps for evidence lifecycle
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Error information if status is FAILED
    error_message: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    # Retry tracking
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    last_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    violation: Mapped["Violation"] = relationship(
        "Violation",
        back_populates="evidence",
    )

    def __repr__(self) -> str:
        return f"<Evidence(id={self.id}, type={self.evidence_type}, status={self.status})>"

    @property
    def snapshot_url(self) -> str | None:
        """Generate the Ruth AI proxy URL for snapshot retrieval."""
        if self.evidence_type != EvidenceType.SNAPSHOT or not self.vas_snapshot_id:
            return None
        return f"/api/v1/violations/{self.violation_id}/snapshot/image"

    @property
    def bookmark_url(self) -> str | None:
        """Generate the Ruth AI proxy URL for bookmark retrieval."""
        if self.evidence_type != EvidenceType.BOOKMARK or not self.vas_bookmark_id:
            return None
        return f"/api/v1/violations/{self.violation_id}/video"
