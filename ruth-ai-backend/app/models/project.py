"""Project model — the site's current and past monitoring projects.

A "project" is a bounded period of operation at a site. Starting a new one
archives the previous project's violations, events, evidence, sessions and
bookmark analyses out of the live tables, so every dashboard counter — all
of which are computed live, none of which are stored — reads zero.

The row is also the audit record for the action: who started it, when, how
many rows moved, and where the pre-flight pg_dump landed. There is
deliberately no general audit table; this is the only thing being audited.

Invariant: at most one project row is current (active, stopping, stopped,
resuming or ended), enforced by the partial unique index
`uq_projects_one_current`. Archiving runs inside a single
transaction guarded by a Postgres advisory lock, so a crash rolls back to
exactly the previous state rather than leaving a half-archived project.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid

#: The project currently collecting data. Exactly one row, or none before
#: the feature is first used.
PROJECT_STATE_ACTIVE = "active"

#: A closed project. Its rows live in the *_archive tables, keyed by
#: archive_batch_id.
PROJECT_STATE_ARCHIVED = "archived"

#: Stop in progress (or interrupted: retrying is safe). Cameras may be
#: partly disabled; everything that would start them again is already idle.
PROJECT_STATE_STOPPING = "stopping"
#: Temporarily off: cameras disabled in VAS, no inference, footage deletion
#: paused. Configuration is untouched; Resume restores the snapshot.
PROJECT_STATE_STOPPED = "stopped"
#: Resume in progress (or interrupted: retrying is safe).
PROJECT_STATE_RESUMING = "resuming"
#: Permanently off. Like stopped, but cannot be resumed. Data stays live
#: and readable; nothing is archived or deleted.
PROJECT_STATE_ENDED = "ended"

PROJECT_STATES = (
    PROJECT_STATE_ACTIVE,
    PROJECT_STATE_STOPPING,
    PROJECT_STATE_STOPPED,
    PROJECT_STATE_RESUMING,
    PROJECT_STATE_ENDED,
    PROJECT_STATE_ARCHIVED,
)

#: The current project is in one of these (at most one row). Everything but
#: "active" means the site must stay idle.
CURRENT_PROJECT_STATES = (
    PROJECT_STATE_ACTIVE,
    PROJECT_STATE_STOPPING,
    PROJECT_STATE_STOPPED,
    PROJECT_STATE_RESUMING,
    PROJECT_STATE_ENDED,
)

#: Advisory lock key for "start new project". Two concurrent starts must not
#: interleave: the second waits, then fails its own preflight because the
#: first already moved the rows. Arbitrary but fixed — never reuse it.
PROJECT_START_LOCK_KEY = 0x52555448_50524A31  # "RUTH" "PRJ1"


class Project(Base, TimestampMixin):
    """One monitoring project at this site.

    Attributes:
        name: Operator-supplied label, e.g. "Coke Drum Campaign 2026-Q4".
            Also what the admin must retype to confirm the action.
        slug: Filesystem-safe derivation of `name`, used in the backup
            filename. Unique so two projects cannot claim one dump.
        state: `active` or `archived`.
        started_at: When this project began collecting.
        started_by: Admin username that started it.
        ended_at: When the next project replaced it. NULL while active.
        ended_by: Admin username that ended it.
        archive_batch_id: Set when the project is archived; the key every
            archived row carries. NULL while active.
        archived_counts: Per-table row counts that were moved, recorded so a
            later restore can verify it got everything back.
        backup_path: Path to the pg_dump taken immediately before this
            project's data was archived.
    """

    __tablename__ = "projects"
    __table_args__ = (
        Index(
            "uq_projects_one_current",
            text("(true)"),
            unique=True,
            postgresql_where=text(
                "state IN ('active', 'stopping', 'stopped', 'resuming', 'ended')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=generate_uuid,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)

    state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=PROJECT_STATE_ACTIVE,
        index=True,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    started_by: Mapped[str] = mapped_column(String(255), nullable=False)

    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ended_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    archive_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        unique=True,
    )

    archived_counts: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    backup_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stop / Resume / End (see project_lifecycle.py).
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resumed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Per camera, VAS enabled/desired_state when Stop began; Resume restores it.
    lifecycle_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: Last Stop/Resume failure, cleared when an attempt succeeds.
    lifecycle_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Project(name={self.name!r}, state={self.state})>"
