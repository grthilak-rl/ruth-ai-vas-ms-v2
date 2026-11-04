"""Project Stop / Resume / End, and the archive columns archiving was losing.

projects gets the lifecycle record:
- stopped_at/by, resumed_at/by: who stopped or resumed the site, and when.
- lifecycle_snapshot: per camera, VAS's enabled flag and desired state as
  they were when Stop began. Resume restores exactly this, so a camera
  that was already off before Stop stays off afterwards.
- lifecycle_error: the last per-camera failure of a Stop/Resume, kept until
  the next attempt succeeds (both are safe to retry).
States stay plain strings: active, stopping, stopped, resuming, ended,
archived.

violations_archive gets severity and dismiss_reason. The live table gained
them on 2026-10-19 but the archive copy did not, so starting a new project
would have silently dropped every dismissal reason (exempt included). No
backfill: the archive holds only the pre-project data, archived before
either column existed.

Revision ID: project_lifecycle
Revises: customer_reports
"""

import sqlalchemy as sa
from alembic import op

revision = "project_lifecycle"
down_revision = "customer_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("projects", sa.Column("stopped_by", sa.String(255), nullable=True))
    op.add_column("projects", sa.Column("resumed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("projects", sa.Column("resumed_by", sa.String(255), nullable=True))
    op.add_column(
        "projects",
        sa.Column("lifecycle_snapshot", sa.dialects.postgresql.JSONB(), nullable=True),
    )
    op.add_column("projects", sa.Column("lifecycle_error", sa.Text(), nullable=True))
    op.add_column("violations_archive", sa.Column("severity", sa.String(16), nullable=True))
    op.add_column("violations_archive", sa.Column("dismiss_reason", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("violations_archive", "dismiss_reason")
    op.drop_column("violations_archive", "severity")
    for column in (
        "lifecycle_error", "lifecycle_snapshot", "resumed_by", "resumed_at", "stopped_by", "stopped_at",
    ):
        op.drop_column("projects", column)
