"""add model_config to stream_sessions

Revision ID: 2026_01_18_0003
Revises: 2026_01_18_0002
Create Date: 2026-01-18 12:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2026_01_18_0003'
down_revision: Union[str, None] = '2026_01_18_0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add model_config JSONB column to stream_sessions table.

    This column stores model-specific configuration such as:
    - Tank corners/ROI for tank overflow monitoring
    - Detection zones for PPE monitoring
    - Custom thresholds per model
    """
    op.add_column(
        'stream_sessions',
        sa.Column(
            'model_config',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='Model-specific configuration (ROI, thresholds, etc.)'
        )
    )


def downgrade() -> None:
    """Remove model_config column from stream_sessions table."""
    op.drop_column('stream_sessions', 'model_config')
