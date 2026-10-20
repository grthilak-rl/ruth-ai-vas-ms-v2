"""A bulk download of violation evidence, built in the background.

The AI engineer wants the exact images a model was given, in bulk, with the
metadata needed to turn them into a dataset. A request can cover thousands
of violations and hundreds of megabytes, which is too long for a request to
hold open, so the work becomes a job: the row below is what the UI polls and
what the sweeper later cleans up.

State lives in a table rather than in memory because the backend restarts —
during a deploy, or after the kind of crash loop BL-12 produced — and a job
the operator is watching must not vanish silently. A row left in
``building`` by a restart is reaped by the sweeper and reported as failed,
which is information; a lost in-memory task is just a spinner that never
finishes.

``total`` and ``done`` are the progress indicator. They are counts of
violations, not bytes, because that is what the operator chose in the
filters and so the only number they can sanity-check.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_uuid

#: Job is queued or actively writing the archive.
EXPORT_BUILDING = "building"
#: Archive is on disk and downloadable until ``expires_at``.
EXPORT_READY = "ready"
#: Build failed; ``error`` says why. Terminal.
EXPORT_FAILED = "failed"
#: Past its TTL and the file has been removed. Terminal, kept for the audit
#: trail: who exported what, when, is worth more than the disk the row uses.
EXPORT_EXPIRED = "expired"

TERMINAL_STATES = (EXPORT_READY, EXPORT_FAILED, EXPORT_EXPIRED)


class ViolationExport(Base):
    """One requested bulk export of violation evidence."""

    __tablename__ = "violation_exports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EXPORT_BUILDING
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: The filters and options the export was built from, exactly as
    #: requested. Stored so the ZIP's manifest and any later question about
    #: "what was in that export?" can be answered without guessing.
    request: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    #: Progress, in violations.
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Outcome counts, mirroring the labelling export's result shape.
    images: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_frame: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Admin principal that asked for it. Bulk worker imagery leaving the
    #: system is worth being able to attribute.
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    #: When the file becomes collectable. NULL until the build succeeds.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # The sweeper's query: ready rows past expiry, and building rows
        # abandoned by a restart.
        Index("ix_violation_exports_status_expires", "status", "expires_at"),
        Index("ix_violation_exports_created_at", "created_at"),
    )
