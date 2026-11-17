"""Store each violation's location (area / side / display name) at write time.

Until now a violation stored only ``camera_name``; its area (manway), side
and display name were joined from the device's CURRENT values on every read.
Moving a camera to another manway therefore moved all of its past violations
in reports, filters, incident cards and exports.

New columns, written when the violation is created from VAS's placement of
the camera at that moment (app/services/placement_resolver.py):

    area                  location (manway) at the time, e.g. MW01 PF COLUMN
    in_out                IN / OUT at the time
    camera_display_name   display name at the time
    location_stamped_at   when the stamp was taken; NULL = not stamped yet
    location_source       vas | mirror (VAS unreachable, Ruth's copy used) |
                          backfill

Readers use the stored values whenever ``location_stamped_at`` is set
(even if area is NULL: the camera was not placed anywhere then) and fall
back to the live device only for rows not stamped yet. Existing rows are
NOT backfilled here: that needs confirmed placement history from VAS and is
done by scripts/backfill_violation_locations.py after the site confirms.

Not added to violations_archive (same as severity): archived rows keep
resolving at read time.

Revision ID: violation_location_stamp
Revises: auto_reports
"""

import sqlalchemy as sa
from alembic import op

revision = "violation_location_stamp"
down_revision = "auto_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("violations", sa.Column("area", sa.String(64), nullable=True))
    op.add_column("violations", sa.Column("in_out", sa.String(8), nullable=True))
    op.add_column(
        "violations", sa.Column("camera_display_name", sa.String(255), nullable=True)
    )
    op.add_column(
        "violations",
        sa.Column("location_stamped_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "violations", sa.Column("location_source", sa.String(16), nullable=True)
    )
    op.create_index("ix_violations_area", "violations", ["area"])


def downgrade() -> None:
    op.drop_index("ix_violations_area", table_name="violations")
    for col in ("location_source", "location_stamped_at", "camera_display_name", "in_out", "area"):
        op.drop_column("violations", col)
