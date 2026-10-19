"""Add evidence.file_path (and the archive mirror).

Step 2 of 2, after the 'frame' enum value exists.

`file_path` holds the saved inferred frame — the exact JPEG the model was
given. Every other reference on this table is a VAS id that Ruth proxies;
this is the first file Ruth owns, which is why the archive gets a column
too: a project archive has to record where the file was, and the archive
run is what decides whether it survives.

Revision ID: evidence_file_path
Revises: evidence_frame_enum
"""

import sqlalchemy as sa
from alembic import op

revision = "evidence_file_path"
down_revision = "evidence_frame_enum"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("file_path", sa.String(512), nullable=True))
    op.add_column(
        "evidence_archive", sa.Column("file_path", sa.String(512), nullable=True)
    )
    # Finding a violation's frame is a per-violation lookup already covered by
    # ix on violation_id; this partial index is for the cleanup job, which
    # sweeps for rows that still have a file.
    op.create_index(
        "ix_evidence_file_path_present",
        "evidence",
        ["id"],
        unique=False,
        postgresql_where=sa.text("file_path IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_file_path_present", table_name="evidence")
    op.drop_column("evidence_archive", "file_path")
    op.drop_column("evidence", "file_path")
