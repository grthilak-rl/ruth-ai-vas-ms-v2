"""Bulk violation-evidence exports, tracked as background jobs.

"Download snapshots" on the Violations page can cover thousands of
violations and hundreds of megabytes (measured: 1.48 GB for every violation
on site to date), which no request can hold open. The job therefore has a
row the UI polls and a sweeper later cleans up.

Deliberately a table and not in-memory state: the backend restarts, and a
job an operator is watching must not disappear without a word. A row left
in `building` by a restart is reaped and reported as failed, which at least
says what happened.

No foreign keys: an export is a point-in-time copy of evidence, and
deleting a violation (or archiving a project) should not retroactively
rewrite the record of what was exported. The `request` JSON keeps the
filters, so the row stays meaningful on its own.

Revision ID: violation_exports
Revises: device_inference_intent
"""

import sqlalchemy as sa
from alembic import op

revision = "violation_exports"
down_revision = "device_inference_intent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "violation_exports",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="building",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "request",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("images", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("no_frame", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_path", sa.String(512), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_violation_exports_status_expires",
        "violation_exports",
        ["status", "expires_at"],
    )
    op.create_index(
        "ix_violation_exports_created_at", "violation_exports", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_violation_exports_created_at", table_name="violation_exports")
    op.drop_index(
        "ix_violation_exports_status_expires", table_name="violation_exports"
    )
    op.drop_table("violation_exports")
