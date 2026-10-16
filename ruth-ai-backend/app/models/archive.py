"""Archive tables — a closed project's rows, moved out of the live tables.

Why physical tables rather than a `project_id` column on the live rows:
every counter in this product is a live aggregate (there is not one stored
total anywhere), and one of the readers is a text-to-SQL chatbot that writes
its own `SELECT count(*) FROM violations`. A filter-based scheme would have
to be applied correctly in ~40 query sites *and* inside LLM-generated SQL.
Moving the rows makes "the new project starts at zero" true of the data, so
no reader — present, future, or generated — has to be taught about it.

Three deliberate differences from the live tables:

1. **No foreign keys.** Not to each other, and not to `devices`. The archive
   must survive a device being retired, an enum being edited, and the live
   tables being dropped and rebuilt. The UUIDs are kept as plain columns.
2. **Enums stored as text.** `violation_type` and friends gain and lose
   values as models ship. An archive that referenced the live enum type
   would break retroactively the first time a value was removed.
3. **Minimal indexing.** These tables are append-only and read rarely (the
   "view archived project" screens). One index per table on
   `archive_batch_id` serves restore and verification; violations get a
   second for the paged viewer. Fewer indexes also makes the archiving
   INSERT cheap.

`archive_batch_id` is the unit of reversal: one project's archiving writes
exactly one batch id across all five tables, and it is recorded on the
`projects` row.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class _ArchiveMixin:
    """Columns every archived row carries.

    `archived_at` is server-side so every row in one batch shares an
    instant, independent of how long the copy took.
    """

    archive_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ViolationArchive(_ArchiveMixin, Base):
    """Archived `violations` row. Columns mirror the live table."""

    __tablename__ = "violations_archive"
    __table_args__ = (
        Index("ix_violations_archive_batch", "archive_batch_id"),
        # The archived-project viewer pages by newest first, per project.
        Index("ix_violations_archive_project_timestamp", "project_id", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    stream_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    type_detail: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    camera_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    bounding_boxes: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EventArchive(_ArchiveMixin, Base):
    """Archived `events` row."""

    __tablename__ = "events_archive"
    __table_args__ = (Index("ix_events_archive_batch", "archive_batch_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    stream_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    violation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    bounding_boxes: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    frame_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    inference_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceArchive(_ArchiveMixin, Base):
    """Archived `evidence` row, plus the VAS media paths as they were.

    Ruth stores no media paths of its own: `Evidence` holds only VAS ids and
    serves media by proxying to VAS. Those ids go dangling once VAS retention
    reaps the row, after which nothing records where the file was. The three
    `vas_*_path` columns capture VAS's own paths at archive time so an
    archived violation stays traceable to a file — recoverable from a cold
    backup even if the VAS row is gone.

    All three are nullable: VAS may already have deleted the row (then
    `vas_paths_resolved` is False), or VAS may be unreachable during
    archiving, which must never block the archive.
    """

    __tablename__ = "evidence_archive"
    __table_args__ = (Index("ix_evidence_archive_batch", "archive_batch_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    violation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    vas_snapshot_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vas_bookmark_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bookmark_duration_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Captured from VAS at archive time (see class docstring).
    vas_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    vas_video_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    vas_thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    vas_file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: True when VAS answered for this id. False means the media was already
    #: gone (or VAS was unreachable) — the distinction matters when someone
    #: later asks why an archived violation has no viewable evidence.
    vas_paths_resolved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )


class StreamSessionArchive(_ArchiveMixin, Base):
    """Archived `stream_sessions` row, including its per-session counters.

    `frames_processed` / `events_count` / `violations_count` are the only
    stored counters in the product. They are not reset — they leave with the
    row, which is why the new project's session list starts genuinely empty
    rather than carrying zeroed rows.
    """

    __tablename__ = "stream_sessions_archive"
    __table_args__ = (Index("ix_stream_sessions_archive_batch", "archive_batch_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    vas_stream_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    inference_fps: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    model_config_json: Mapped[dict | None] = mapped_column(
        "model_config", JSONB, nullable=True
    )
    models: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    models_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    frames_processed: Mapped[int] = mapped_column(Integer, nullable=False)
    events_count: Mapped[int] = mapped_column(Integer, nullable=False)
    violations_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BookmarkAnalysisArchive(_ArchiveMixin, Base):
    """Archived `bookmark_analyses` row."""

    __tablename__ = "bookmark_analyses_archive"
    __table_args__ = (
        Index("ix_bookmark_analyses_archive_batch", "archive_batch_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    vas_bookmark_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
