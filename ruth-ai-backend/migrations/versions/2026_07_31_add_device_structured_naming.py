"""mirror VAS structured device naming (manway / in_out / display_name)

VAS phase 1 adds operator-facing structured names so cameras are identified by
location rather than by "CUG3PTZ10072". VAS owns these fields and DERIVES
display_name from manway + in_out + the identifier; Ruth mirrors all three on
each device sync and never recomputes display_name, so there is exactly one
implementation of the naming rule.

`devices.name` is unchanged and remains the stable identifier.

Backfill: none. All three columns start NULL and are populated by the next
device sync from VAS. Until then (and for any camera with no manway/in_out
set) the UI reads `display_name or name`, so cameras display exactly as they
do today.

Revision ID: add_device_structured_naming
Revises: add_bookmark_analyses
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "add_device_structured_naming"
down_revision: Union[str, None] = "add_bookmark_analyses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("manway", sa.String(length=64), nullable=True))
    op.create_index("ix_devices_manway", "devices", ["manway"])
    # Mirrored as plain text, not an enum: VAS owns the vocabulary, and a
    # second enum type here would need its own migration every time VAS
    # changes it.
    op.add_column("devices", sa.Column("in_out", sa.String(length=8), nullable=True))
    op.add_column(
        "devices", sa.Column("display_name", sa.String(length=400), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("devices", "display_name")
    op.drop_column("devices", "in_out")
    op.drop_index("ix_devices_manway", table_name="devices")
    op.drop_column("devices", "manway")
