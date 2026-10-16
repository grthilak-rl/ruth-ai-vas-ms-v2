"""add projects + archive tables (Start New Project)

Adds the `projects` table and five `*_archive` tables. Creates no index on,
and changes no column of, any existing table: at this revision the live
schema is untouched, so the backend behaves identically until the new admin
action is actually used.

The archive tables intentionally have no foreign keys and store the enum
columns as text — see app/models/archive.py for why. Practical consequence
for this migration: it does not touch the enum types, so it cannot fail on
a value that has since been added or removed.

Measured on the live database at authoring time (2026-10-16):
    violations        116 953 rows   103 MB
    evidence          116 937 rows    36 MB
    events             13 318 rows   9.4 MB
    stream_sessions        79 rows
    bookmark_analyses       0 rows
    -> ~234k rows, ~150 MB to move. Comfortably one transaction.

Upgrade creates empty tables; it moves no data and is safe to run with the
backend up. Downgrade drops them, which DOES destroy archived data — it
refuses while any archive table is non-empty rather than discarding history
silently.

Revision ID: add_projects_and_archive
Revises: stream_session_models
Create Date: 2026-10-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "add_projects_and_archive"
down_revision: Union[str, None] = "stream_session_models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ARCHIVE_TABLES = (
    "violations_archive",
    "events_archive",
    "evidence_archive",
    "stream_sessions_archive",
    "bookmark_analyses_archive",
)

#: Every archive table carries these.
def _archive_columns() -> list[sa.Column]:
    return [
        sa.Column("archive_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # projects
    # -------------------------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_by", sa.String(length=255), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_by", sa.String(length=255), nullable=True),
        sa.Column("archive_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_counts", postgresql.JSONB(), nullable=True),
        sa.Column("backup_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
        sa.UniqueConstraint("archive_batch_id", name="uq_projects_archive_batch_id"),
        sa.CheckConstraint(
            "state IN ('active', 'archived')", name="ck_projects_state"
        ),
    )
    op.create_index("ix_projects_state", "projects", ["state"])
    # At most one project collecting data at a time. This is what makes two
    # concurrent "start new project" calls impossible to both commit, even if
    # the advisory lock in ProjectService were bypassed.
    op.create_index(
        "uq_projects_one_active",
        "projects",
        ["state"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )

    # -------------------------------------------------------------------------
    # violations_archive
    # -------------------------------------------------------------------------
    op.create_table(
        "violations_archive",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stream_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("type_detail", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("camera_name", sa.String(length=255), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column("bounding_boxes", postgresql.JSONB(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        *_archive_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_violations_archive_batch", "violations_archive", ["archive_batch_id"]
    )
    op.create_index(
        "ix_violations_archive_project_timestamp",
        "violations_archive",
        ["project_id", "timestamp"],
    )

    # -------------------------------------------------------------------------
    # events_archive
    # -------------------------------------------------------------------------
    op.create_table(
        "events_archive",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stream_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("violation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column("bounding_boxes", postgresql.JSONB(), nullable=True),
        sa.Column("frame_id", sa.String(length=255), nullable=True),
        sa.Column("inference_time_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        *_archive_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_archive_batch", "events_archive", ["archive_batch_id"])

    # -------------------------------------------------------------------------
    # evidence_archive  (+ VAS paths captured at archive time)
    # -------------------------------------------------------------------------
    op.create_table(
        "evidence_archive",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("violation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("vas_snapshot_id", sa.String(length=255), nullable=True),
        sa.Column("vas_bookmark_id", sa.String(length=255), nullable=True),
        sa.Column("bookmark_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # Ruth stores no media paths of its own; these mirror VAS's at the
        # moment of archiving so an archived violation stays traceable to a
        # file after VAS retention removes the row.
        sa.Column("vas_file_path", sa.Text(), nullable=True),
        sa.Column("vas_video_file_path", sa.Text(), nullable=True),
        sa.Column("vas_thumbnail_path", sa.Text(), nullable=True),
        sa.Column("vas_file_size", sa.BigInteger(), nullable=True),
        sa.Column(
            "vas_paths_resolved",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        *_archive_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evidence_archive_batch", "evidence_archive", ["archive_batch_id"]
    )

    # -------------------------------------------------------------------------
    # stream_sessions_archive
    # -------------------------------------------------------------------------
    op.create_table(
        "stream_sessions_archive",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vas_stream_id", sa.String(length=255), nullable=True),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=True),
        sa.Column("inference_fps", sa.Integer(), nullable=False),
        sa.Column("confidence_threshold", sa.Float(), nullable=False),
        sa.Column("model_config", postgresql.JSONB(), nullable=True),
        sa.Column("models", postgresql.JSONB(), nullable=True),
        sa.Column("models_revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("frames_processed", sa.Integer(), nullable=False),
        sa.Column("events_count", sa.Integer(), nullable=False),
        sa.Column("violations_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        *_archive_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stream_sessions_archive_batch",
        "stream_sessions_archive",
        ["archive_batch_id"],
    )

    # -------------------------------------------------------------------------
    # bookmark_analyses_archive
    # -------------------------------------------------------------------------
    op.create_table(
        "bookmark_analyses_archive",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vas_bookmark_id", sa.String(length=255), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=True),
        sa.Column("parameters", postgresql.JSONB(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by", sa.String(length=255), nullable=True),
        *_archive_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bookmark_analyses_archive_batch",
        "bookmark_analyses_archive",
        ["archive_batch_id"],
    )


def downgrade() -> None:
    """Drop the new tables, refusing if that would discard archived data.

    Dropping `violations_archive` with rows in it destroys the only copy of
    a closed project's history that is still in the database (the pg_dump
    taken at archive time aside). Downgrade is meant for backing out an
    unused deployment, so it declines rather than deciding for the operator.
    """
    bind = op.get_bind()
    non_empty = []
    for table in ARCHIVE_TABLES:
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar() or 0
        if count:
            non_empty.append(f"  {table}: {count} rows")
    if non_empty:
        raise RuntimeError(
            "Refusing to drop the archive tables: they hold archived project "
            "data, which this downgrade would destroy. Restore the data into "
            "the live tables first (or drop the tables by hand if you are "
            "certain), then re-run the downgrade.\n" + "\n".join(non_empty)
        )

    op.drop_table("bookmark_analyses_archive")
    op.drop_table("stream_sessions_archive")
    op.drop_table("evidence_archive")
    op.drop_table("events_archive")
    op.drop_table("violations_archive")
    op.drop_index("uq_projects_one_active", table_name="projects")
    op.drop_index("ix_projects_state", table_name="projects")
    op.drop_table("projects")
