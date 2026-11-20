"""add model_notes and model_recommendations (Settings -> AI Models)

Purely additive: two new tables and their indexes. No existing table,
column or row is touched; downgrade drops only what this creates.

- model_notes            dated observations about a model, written by an
                         admin (or "imported" from the evaluation record).
                         ``internal`` hides a note from the camera picker.
- model_recommendations  the recommended model per violation type, with
                         the note that explains why. At most one active
                         row per type; replaced or cleared rows keep
                         ``cleared_at`` as history.

Both hang off model_store_models rows, which are never deleted (a deleted
draft is a tombstone), so notes survive install, uninstall and Delete.
``project_id`` has no foreign key on purpose: projects are ended, never
deleted, and the store tables stay creatable on their own.

Revision ID: model_notes
Revises: product_branding
Create Date: 2026-11-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "model_notes"
down_revision: Union[str, None] = "product_branding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "model_pk",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_store_models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("internal", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("edited_by", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_model_notes_model_observed", "model_notes", ["model_pk", "observed_on"])

    op.create_table(
        "model_recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("violation_type", sa.String(64), nullable=False),
        sa.Column(
            "model_pk",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_store_models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "note_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_notes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("set_by", sa.Text(), nullable=False),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleared_by", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_model_recommendations_active_type",
        "model_recommendations",
        ["violation_type"],
        unique=True,
        postgresql_where=sa.text("cleared_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_model_recommendations_active_type", table_name="model_recommendations")
    op.drop_table("model_recommendations")
    op.drop_index("ix_model_notes_model_observed", table_name="model_notes")
    op.drop_table("model_notes")
