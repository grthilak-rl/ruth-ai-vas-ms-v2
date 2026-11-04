"""Customer reports (PDF), built as background jobs and kept for re-download.

Same lifecycle as violation_exports: a row the UI polls while it builds, a
file kept for the retention period, and a row that outlives the file as the
record of who generated which report. No foreign keys, for the same reason:
a report is a point-in-time document.

Revision ID: customer_reports
Revises: violation_exports
"""

import sqlalchemy as sa
from alembic import op

revision = "customer_reports"
down_revision = "violation_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_reports",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="building"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("stage", sa.String(64), nullable=True),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("format", sa.String(8), nullable=False, server_default="pdf"),
        sa.Column("preset", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_label", sa.String(64), nullable=False),
        sa.Column(
            "options",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("file_path", sa.String(512), nullable=True),
        sa.Column("filename", sa.String(200), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("incidents", sa.Integer(), nullable=True),
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
        "ix_customer_reports_status_expires", "customer_reports", ["status", "expires_at"]
    )
    op.create_index("ix_customer_reports_created_at", "customer_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_customer_reports_created_at", table_name="customer_reports")
    op.drop_index("ix_customer_reports_status_expires", table_name="customer_reports")
    op.drop_table("customer_reports")
