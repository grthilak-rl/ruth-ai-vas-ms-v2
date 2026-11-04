"""Shift reports, automatic per-shift reports and Regenerate.

customer_reports gains:
- trigger: manual (an admin), auto (the scheduler) or regenerate.
- shift_name: the shift a shift report covers.
- regenerated_from: the report a Regenerate re-built.
- attempts: builds started; an interrupted auto build is retried up to 3.

uq_customer_reports_auto_period makes "one auto report per shift
occurrence" a database fact: the scheduler inserts with ON CONFLICT DO
NOTHING, so a restart, a retry or two schedulers at once cannot create a
duplicate. Manual and regenerated reports are not constrained.

Revision ID: auto_reports
Revises: project_states_check
"""

import sqlalchemy as sa
from alembic import op

revision = "auto_reports"
down_revision = "project_states_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customer_reports",
        sa.Column("trigger", sa.String(16), nullable=False, server_default="manual"),
    )
    op.add_column("customer_reports", sa.Column("shift_name", sa.String(64), nullable=True))
    op.add_column(
        "customer_reports",
        sa.Column("regenerated_from", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "customer_reports",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_customer_reports_auto_period ON customer_reports "
        "(preset, period_start, period_end) WHERE trigger = 'auto'"
    )


def downgrade() -> None:
    op.drop_index("uq_customer_reports_auto_period", table_name="customer_reports")
    for column in ("attempts", "regenerated_from", "shift_name", "trigger"):
        op.drop_column("customer_reports", column)
