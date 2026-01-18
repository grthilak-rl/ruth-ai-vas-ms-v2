"""Add PPE detection event types

Revision ID: 2026_01_18_0002
Revises: 2026_01_13_0001
Create Date: 2026-01-18 03:58:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2026_01_18_0002'
down_revision = '2026_01_13_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add PPE detection event and violation types to enums."""

    # Add new event types to eventtype enum
    op.execute("ALTER TYPE eventtype ADD VALUE IF NOT EXISTS 'ppe_violation'")
    op.execute("ALTER TYPE eventtype ADD VALUE IF NOT EXISTS 'ppe_compliant'")

    # Add new violation type to violationtype enum
    op.execute("ALTER TYPE violationtype ADD VALUE IF NOT EXISTS 'ppe_violation'")


def downgrade() -> None:
    """Cannot remove enum values in PostgreSQL.

    PostgreSQL does not support removing enum values.
    To downgrade, you would need to:
    1. Create new enum types without the PPE values
    2. Migrate all data to use new enums
    3. Drop old enum types
    4. Rename new enums to old names

    This is complex and destructive, so we leave it as a no-op.
    The presence of unused enum values is harmless.
    """
    pass
