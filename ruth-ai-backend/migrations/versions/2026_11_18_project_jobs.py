"""Project lifecycle jobs: Start/Stop/End/Resume run in the background.

Adds one table, ``project_jobs``. No existing table or row is touched.
At most one job is queued or running (``uq_project_jobs_one_active``).

Revision ID: project_jobs
Revises: projects_as_tags
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "project_jobs"
down_revision = "projects_as_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(32), nullable=True),
        sa.Column("stage_detail", sa.Text(), nullable=True),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("backup_path", sa.Text(), nullable=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", name="fk_project_jobs_project_id"),
            nullable=True,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "action IN ('start', 'stop', 'end', 'resume')", name="ck_project_jobs_action"
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed', 'interrupted')",
            name="ck_project_jobs_state",
        ),
    )
    op.create_index("ix_project_jobs_created_at", "project_jobs", ["created_at"])
    op.execute(
        "CREATE UNIQUE INDEX uq_project_jobs_one_active ON project_jobs ((true))"
        " WHERE state IN ('queued', 'running')"
    )


def downgrade() -> None:
    op.drop_table("project_jobs")
