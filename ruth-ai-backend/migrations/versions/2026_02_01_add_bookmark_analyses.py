"""Add bookmark_analyses table

Revision ID: add_bookmark_analyses
Revises: add_zone_intrusion_type
Create Date: 2026-02-01 00:00:00.000000

Async AI analysis jobs against VAS bookmarks (Phase D.1 foundation).
Each row is one submitted analysis; the worker transitions
pending -> running -> completed/failed and writes the summary blob.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "add_bookmark_analyses"
down_revision: Union[str, None] = "add_zone_intrusion_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the lifecycle enum first; idempotent via checkfirst.
    bookmark_analysis_state_enum = postgresql.ENUM(
        "pending",
        "running",
        "completed",
        "failed",
        name="bookmark_analysis_state",
        create_type=False,
    )
    bookmark_analysis_state_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "bookmark_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vas_bookmark_id", sa.String(255), nullable=False, index=True),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=True),
        sa.Column("parameters", postgresql.JSONB(), nullable=True),
        sa.Column(
            "state",
            bookmark_analysis_state_enum,
            nullable=False,
            server_default="pending",
            index=True,
        ),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by", sa.String(255), nullable=True),
    )

    # Chronological listing: "most recent analyses across all bookmarks"
    # is a default UI view, so a dedicated index pays off.
    op.create_index(
        "ix_bookmark_analyses_created_at_desc",
        "bookmark_analyses",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_bookmark_analyses_created_at_desc", table_name="bookmark_analyses")
    op.drop_table("bookmark_analyses")

    bookmark_analysis_state_enum = postgresql.ENUM(
        "pending",
        "running",
        "completed",
        "failed",
        name="bookmark_analysis_state",
    )
    bookmark_analysis_state_enum.drop(op.get_bind(), checkfirst=True)
