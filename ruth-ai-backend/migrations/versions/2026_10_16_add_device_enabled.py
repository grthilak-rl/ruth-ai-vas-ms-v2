"""mirror VAS's durable `enabled` policy flag onto Ruth devices

VAS has had three distinct per-device flags for a while:

    is_active     transient liveness; VAS resets it to False on every boot
    desired_state per-stream intent; rewritten by start/stop-stream
    enabled       durable operator policy, changed only by an explicit
                  enable/disable action ("not a soft delete")

`GET /api/devices` — the endpoint Ruth syncs from — already returns all of
them, but Ruth's VAS DTO only read `is_active`, so Ruth had no way to know a
camera had been retired. Ruth's camera lists therefore kept showing cameras
nobody intends to run, and the one flag Ruth did have was unusable as a
policy flag because every sync overwrites it from VAS's transient value.

This adds the missing column so Ruth can hide retired cameras by default.
It is a mirror, not a source of truth: the next device sync overwrites it
from VAS, and nothing in Ruth writes it.

Defaults to TRUE for existing rows, which is the correct backfill — a
camera is enabled unless VAS says otherwise, and the next sync (on startup,
or via POST /internal/sync/devices) corrects the ones that are not. At
authoring time 3 of VAS's 15 devices are disabled.

Revision ID: add_device_enabled
Revises: add_projects_and_archive
Create Date: 2026-10-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_device_enabled"
down_revision: Union[str, None] = "add_projects_and_archive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    # Indexed because it becomes the default filter on every camera list.
    op.create_index("ix_devices_enabled", "devices", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_devices_enabled", table_name="devices")
    op.drop_column("devices", "enabled")
