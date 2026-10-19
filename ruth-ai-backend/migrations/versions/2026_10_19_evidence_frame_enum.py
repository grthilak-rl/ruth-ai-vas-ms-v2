"""Add the 'frame' value to the evidence_type enum.

Step 1 of 2. Postgres refuses to *use* an enum value in the same
transaction that adds it, and Alembic wraps each migration in one — so
adding the value and the column that will hold frame rows are separate
revisions. This one only widens the type.

Revision ID: evidence_frame_enum
Revises: add_device_enabled
"""

from alembic import op

revision = "evidence_frame_enum"
down_revision = "add_device_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS so a partially-applied deploy can be re-run.
    op.execute("ALTER TYPE evidence_type ADD VALUE IF NOT EXISTS 'frame'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum. Removing it would mean
    # recreating the type and rewriting every dependent column, which is a
    # far bigger risk than leaving an unused label in place.
    pass
