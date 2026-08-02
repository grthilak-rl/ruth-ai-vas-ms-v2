"""add app_settings key/value table for site-global configuration

The shift schedule (which shift is running now, and therefore which
violations count towards "this shift") is site-global: every operator
looking at the plant must see the same window, and reports built later
have to be able to reconstruct the same boundaries. That rules out
localStorage and per-user rows.

Stored as a generic key/value table rather than a dedicated
`shift_schedules` table because the constraint that actually matters —
shifts must tile the 24h day without overlapping or leaving gaps — is a
whole-schedule property that Postgres cannot express as a column
constraint. Validation therefore lives in the service layer either way,
and a KV table lets the next site-global setting arrive without another
migration.

First and currently only key: `shift_schedule`. No row is seeded: an
absent row means "continuous monitoring, no shifts configured", which is
a valid posture rather than an error, and the service materialises that
default.

Revision ID: add_app_settings
Revises: add_violation_type_detail
Create Date: 2026-08-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "add_app_settings"
down_revision: Union[str, None] = "add_violation_type_detail"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the app_settings table."""
    op.create_table(
        "app_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "key",
            sa.String(100),
            nullable=False,
            comment="Stable site-global setting identifier, e.g. shift_schedule",
        ),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Setting payload; shape depends on key",
        ),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Unique so a setting cannot end up with two competing rows, and so
    # the read path is a single indexed lookup.
    op.create_index(
        "ix_app_settings_key",
        "app_settings",
        ["key"],
        unique=True,
    )


def downgrade() -> None:
    """Drop the app_settings table."""
    op.drop_index("ix_app_settings_key", table_name="app_settings")
    op.drop_table("app_settings")
