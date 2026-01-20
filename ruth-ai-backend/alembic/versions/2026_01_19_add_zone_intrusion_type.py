"""Add zone_intrusion and zone_exit to violation_type enum

Revision ID: add_zone_intrusion_type
Revises: 2026_01_18_0003_add_model_config
Create Date: 2026-01-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_zone_intrusion_type'
down_revision: Union[str, None] = '2026_01_18_0003_add_model_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new violation types to the enum
    op.execute("ALTER TYPE violation_type ADD VALUE IF NOT EXISTS 'zone_intrusion'")
    op.execute("ALTER TYPE violation_type ADD VALUE IF NOT EXISTS 'zone_exit'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing values from enums easily
    # Would require recreating the enum type
    pass
