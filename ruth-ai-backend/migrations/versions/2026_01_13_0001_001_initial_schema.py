"""Initial Ruth AI schema

Revision ID: 001
Revises: None
Create Date: 2026-01-13

Creates the initial database schema for Ruth AI including:
- Enums: stream_state, event_type, violation_type, violation_status, evidence_type, evidence_status
- Tables: devices, stream_sessions, events, violations, evidence
- Indexes: for time-series queries, status filtering, and relationships

This migration is reversible - downgrade will drop all tables and enums.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Create ENUMs first
    stream_state_enum = postgresql.ENUM(
        "live",
        "stopped",
        "starting",
        "stopping",
        "error",
        name="stream_state",
        create_type=False,
    )
    stream_state_enum.create(op.get_bind(), checkfirst=True)

    event_type_enum = postgresql.ENUM(
        "fall_detected",
        "no_fall",
        "person_detected",
        "unknown",
        name="event_type",
        create_type=False,
    )
    event_type_enum.create(op.get_bind(), checkfirst=True)

    violation_type_enum = postgresql.ENUM(
        "fall_detected",
        name="violation_type",
        create_type=False,
    )
    violation_type_enum.create(op.get_bind(), checkfirst=True)

    violation_status_enum = postgresql.ENUM(
        "open",
        "reviewed",
        "dismissed",
        "resolved",
        name="violation_status",
        create_type=False,
    )
    violation_status_enum.create(op.get_bind(), checkfirst=True)

    evidence_type_enum = postgresql.ENUM(
        "snapshot",
        "bookmark",
        name="evidence_type",
        create_type=False,
    )
    evidence_type_enum.create(op.get_bind(), checkfirst=True)

    evidence_status_enum = postgresql.ENUM(
        "pending",
        "processing",
        "ready",
        "failed",
        name="evidence_status",
        create_type=False,
    )
    evidence_status_enum.create(op.get_bind(), checkfirst=True)

    # Create devices table
    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "vas_device_id", sa.String(255), nullable=False, unique=True, index=True
        ),
        sa.Column("name", sa.String(255), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True, index=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Create stream_sessions table
    op.create_table(
        "stream_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("vas_stream_id", sa.String(255), nullable=True, index=True),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=True),
        sa.Column("inference_fps", sa.Integer(), nullable=False, default=10),
        sa.Column("confidence_threshold", sa.Float(), nullable=False, default=0.7),
        sa.Column(
            "state",
            stream_state_enum,
            nullable=False,
            default="starting",
            index=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("frames_processed", sa.Integer(), nullable=False, default=0),
        sa.Column("events_count", sa.Integer(), nullable=False, default=0),
        sa.Column("violations_count", sa.Integer(), nullable=False, default=0),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Create composite index for finding active sessions per device
    op.create_index(
        "ix_stream_sessions_device_state",
        "stream_sessions",
        ["device_id", "state"],
    )

    # Create violations table (before events, since events reference violations)
    op.create_table(
        "violations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "stream_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stream_sessions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "type",
            violation_type_enum,
            nullable=False,
            index=True,
        ),
        sa.Column(
            "status",
            violation_status_enum,
            nullable=False,
            default="open",
            index=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), nullable=False, index=True
        ),
        sa.Column("camera_name", sa.String(255), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("bounding_boxes", postgresql.JSONB(), nullable=True),
        sa.Column("reviewed_by", sa.String(255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Create composite indexes for violations
    op.create_index(
        "ix_violations_status_timestamp",
        "violations",
        ["status", "timestamp"],
    )
    op.create_index(
        "ix_violations_device_status_timestamp",
        "violations",
        ["device_id", "status", "timestamp"],
    )

    # Create events table
    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "stream_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stream_sessions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "violation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("violations.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "event_type",
            event_type_enum,
            nullable=False,
            index=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), nullable=False, index=True
        ),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("bounding_boxes", postgresql.JSONB(), nullable=True),
        sa.Column("frame_id", sa.String(255), nullable=True),
        sa.Column("inference_time_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Create composite indexes for events (high-volume table)
    op.create_index(
        "ix_events_device_timestamp",
        "events",
        ["device_id", "timestamp"],
    )
    op.create_index(
        "ix_events_device_type_timestamp",
        "events",
        ["device_id", "event_type", "timestamp"],
    )

    # Create evidence table
    op.create_table(
        "evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "violation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("violations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "evidence_type",
            evidence_type_enum,
            nullable=False,
            index=True,
        ),
        sa.Column(
            "status",
            evidence_status_enum,
            nullable=False,
            default="pending",
            index=True,
        ),
        sa.Column("vas_snapshot_id", sa.String(255), nullable=True),
        sa.Column("vas_bookmark_id", sa.String(255), nullable=True),
        sa.Column("bookmark_duration_seconds", sa.Integer(), nullable=True, default=15),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, default=0),
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Create composite index for evidence
    op.create_index(
        "ix_evidence_violation_type",
        "evidence",
        ["violation_id", "evidence_type"],
    )


def downgrade() -> None:
    """Downgrade database schema."""
    # Drop tables in reverse order (respecting foreign keys)
    op.drop_table("evidence")
    op.drop_table("events")
    op.drop_table("violations")
    op.drop_table("stream_sessions")
    op.drop_table("devices")

    # Drop ENUMs
    op.execute("DROP TYPE IF EXISTS evidence_status")
    op.execute("DROP TYPE IF EXISTS evidence_type")
    op.execute("DROP TYPE IF EXISTS violation_status")
    op.execute("DROP TYPE IF EXISTS violation_type")
    op.execute("DROP TYPE IF EXISTS event_type")
    op.execute("DROP TYPE IF EXISTS stream_state")
