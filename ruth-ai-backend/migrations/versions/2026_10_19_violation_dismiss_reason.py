"""Add violations.dismiss_reason.

Why an operator dismissed a violation: a false-alarm kind (pipework/object,
wrong person, PPE actually worn, other) or "duplicate / already handled".
False alarms are exported for labelling. Plain text, not a Postgres enum, so
adding a reason needs no migration. Existing dismissals keep NULL: their
reason was never asked for.

Revision ID: violation_dismiss_reason
Revises: violation_severity
"""

import sqlalchemy as sa
from alembic import op

revision = "violation_dismiss_reason"
down_revision = "violation_severity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("violations", sa.Column("dismiss_reason", sa.String(32), nullable=True))
    op.create_index("ix_violations_dismiss_reason", "violations", ["dismiss_reason"])


def downgrade() -> None:
    op.drop_index("ix_violations_dismiss_reason", table_name="violations")
    op.drop_column("violations", "dismiss_reason")
