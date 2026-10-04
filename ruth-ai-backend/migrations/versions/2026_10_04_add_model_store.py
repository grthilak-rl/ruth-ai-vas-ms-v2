"""add model_store_* tables for the Model Management admin area

Purely additive: creates three new tables and their indexes. No existing
table, column, type or row is touched, and downgrade drops only what this
revision creates.

- model_store_models   uploaded models; model_id unique forever (deleted
                       models stay as tombstones so an id is never reused)
- model_store_files    completed weight files in a draft
- model_store_uploads  chunked upload sessions

States are VARCHAR, not Postgres enums, so later steps can add states
without ALTER TYPE.

Revision ID: add_model_store
Revises: add_app_settings
Create Date: 2026-10-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "add_model_store"
down_revision: Union[str, None] = "add_app_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    """Create model_store_models, model_store_files, model_store_uploads."""
    op.create_table(
        "model_store_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "model_id",
            sa.String(48),
            nullable=False,
            comment="Runtime model id; unique forever (tombstones keep it)",
        ),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column(
            "state",
            sa.String(16),
            nullable=False,
            server_default="draft",
            comment="draft | deleted (later steps add more)",
        ),
        sa.Column("first_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("trash_path", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index(
        "ix_model_store_models_model_id",
        "model_store_models",
        ["model_id"],
        unique=True,
    )

    op.create_table(
        "model_store_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "model_pk",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_store_models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_by", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_model_store_files_model_filename",
        "model_store_files",
        ["model_pk", "filename"],
        unique=True,
    )

    op.create_table(
        "model_store_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "model_pk",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_store_models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=False),
        sa.Column("expected_sha256", sa.String(64), nullable=True),
        sa.Column("client_last_modified", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="uploading",
            comment="uploading | completed | failed | aborted | expired",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_store_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", sa.Text(), nullable=True),
        *_timestamps(),
    )
    # One in-flight upload per (model, filename): idempotent init / resume.
    op.create_index(
        "ix_model_store_uploads_active_filename",
        "model_store_uploads",
        ["model_pk", "filename"],
        unique=True,
        postgresql_where=sa.text("status = 'uploading'"),
    )
    # Stale-staging cleanup scans by status and last activity.
    op.create_index(
        "ix_model_store_uploads_status_updated",
        "model_store_uploads",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    """Drop exactly the three tables (and their indexes) created above."""
    op.drop_index("ix_model_store_uploads_status_updated", table_name="model_store_uploads")
    op.drop_index("ix_model_store_uploads_active_filename", table_name="model_store_uploads")
    op.drop_table("model_store_uploads")
    op.drop_index("ix_model_store_files_model_filename", table_name="model_store_files")
    op.drop_table("model_store_files")
    op.drop_index("ix_model_store_models_model_id", table_name="model_store_models")
    op.drop_table("model_store_models")
