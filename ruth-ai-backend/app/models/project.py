"""Project model — the site's current and past monitoring projects.

A "project" is a bounded period of operation at a site. Its data is tagged,
not moved: every violation, event, evidence row, session, report and export
carries ``project_id`` (app/models/project_tag.py), and the portal can be
put into any project's context to read it (app/core/project_scope.py).
Starting a new project after ending one opens a new row and changes which
cameras run; it archives, moves and deletes nothing.

History: until 2026-11 starting a project moved the previous project's rows
into ``*_archive`` tables. The one project archived that way ("Initial data
(before projects)") was copied back and tagged by the projects_as_tags
migration; the archive tables are kept untouched until a later release.

Invariant: at most one project row is current (active, stopping, stopped or
resuming), enforced by the partial unique index `uq_projects_one_current`.
An ended project is past: it no longer holds the current slot, so the next
project can start. Between End and the next Start there is no current
project and the site stays idle (see project_lifecycle.site_project).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid

#: The project currently collecting data. Exactly one row, or none before
#: the feature is first used.
PROJECT_STATE_ACTIVE = "active"

#: Legacy: a project whose rows were moved to the *_archive tables. No row is
#: in this state after the projects_as_tags migration (it became "ended");
#: the value stays allowed so old backups still restore.
PROJECT_STATE_ARCHIVED = "archived"

#: Stop in progress (or interrupted: retrying is safe). Cameras may be
#: partly disabled; everything that would start them again is already idle.
PROJECT_STATE_STOPPING = "stopping"
#: Temporarily off: cameras disabled in VAS, no inference, footage deletion
#: paused. Configuration is untouched; Resume restores the snapshot.
PROJECT_STATE_STOPPED = "stopped"
#: Resume in progress (or interrupted: retrying is safe).
PROJECT_STATE_RESUMING = "resuming"
#: Permanently off and past. Cannot be resumed; its data stays tagged and
#: readable from Settings -> Project. Not a current state: once a project
#: is ended the next one can be started.
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
)

#: Past projects: viewable, never current again.
PAST_PROJECT_STATES = (PROJECT_STATE_ENDED, PROJECT_STATE_ARCHIVED)

#: Advisory lock key for "start new project". Two concurrent starts must not
#: interleave: the second waits, then fails because a current project now
#: exists. Arbitrary but fixed — never reuse it.
PROJECT_START_LOCK_KEY = 0x52555448_50524A31  # "RUTH" "PRJ1"


class Project(Base, TimestampMixin):
    """One monitoring project at this site.

    Attributes:
        name: Operator-supplied label, e.g. "Coke Drum Campaign 2026-Q4".
            Also what the admin must retype to confirm the action.
        slug: Filesystem-safe derivation of `name`, used in the backup
            filename. Unique so two projects cannot claim one dump.
        state: one of PROJECT_STATES.
        started_at: When this project began collecting.
        started_by: Admin username that started it.
        ended_at: When it was ended. NULL while current.
        ended_by: Admin username that ended it.
        archive_batch_id: Legacy. Set only on the project whose rows the old
            Start flow moved to the *_archive tables.
        archived_counts: Legacy, as archive_batch_id.
        backup_path: Path to the pg_dump taken immediately before the
            project that followed this one was started.
    """

    __tablename__ = "projects"
    __table_args__ = (
        Index(
            "uq_projects_one_current",
            text("(true)"),
            unique=True,
            postgresql_where=text(
                "state IN ('active', 'stopping', 'stopped', 'resuming')"
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


class ProjectCamera(Base):
    """A camera's membership of a project, for one interval.

    ``joined_at`` .. ``left_at`` (NULL while it is still in the project). A
    camera removed and added again has two rows; at most one is open
    (``uq_project_cameras_open``). Start opens rows for the picked cameras,
    "Change cameras" opens and closes them mid-project, End closes every open
    row. Stop closes nothing: a stopped project's cameras are still its
    cameras; monitored time comes from stream sessions, not from here.

    Analytics counts the cameras that were members at any point of the
    period. ``inferred`` rows were reconstructed from data (first/last
    activity) for projects that predate this table.

    Membership is Ruth's: it never touches a camera's VAS placement (location
    history), which stays independent. Devices and inference intents stay
    global, as before.
    """

    __tablename__ = "project_cameras"
    __table_args__ = (
        Index(
            "uq_project_cameras_open",
            "project_id",
            "device_id",
            unique=True,
            postgresql_where=text("left_at IS NULL"),
        ),
        Index("ix_project_cameras_project_joined", "project_id", "joined_at"),
        CheckConstraint("left_at IS NULL OR left_at >= joined_at", name="ck_project_cameras_interval"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: dialog = Start dialog or "Change cameras"; manual = added by hand;
    #: derived = reconstructed from the project's data.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="dialog")
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
