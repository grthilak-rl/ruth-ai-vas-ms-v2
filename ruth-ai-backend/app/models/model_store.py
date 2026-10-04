"""Model store tables (Model Management admin area).

Additive and self-contained: nothing outside app/services/model_store and
app/api/v1/admin reads or writes these tables.

- model_store_models   one row per uploaded model. ``model_id`` is unique for
                       the life of the table: a deleted model keeps its row as
                       a tombstone, so the id is never handed out again.
- model_store_files    weight files that finished uploading into a draft.
- model_store_uploads  chunked upload sessions (staging area).

States are plain strings validated in the service layer rather than Postgres
enums, so later steps can add states without ALTER TYPE.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid

# Model states
MODEL_STATE_DRAFT = "draft"
MODEL_STATE_DELETED = "deleted"

# Upload states
UPLOAD_STATUS_UPLOADING = "uploading"
UPLOAD_STATUS_COMPLETED = "completed"
UPLOAD_STATUS_FAILED = "failed"
UPLOAD_STATUS_ABORTED = "aborted"
UPLOAD_STATUS_EXPIRED = "expired"


class ModelStoreModel(Base, TimestampMixin):
    """An uploaded model (draft until applied in a later step)."""

    __tablename__ = "model_store_models"
    __table_args__ = (Index("ix_model_store_models_model_id", "model_id", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    model_id: Mapped[str] = mapped_column(String(48), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=MODEL_STATE_DRAFT)
    # Set by the first Apply (Step 5). model_id is editable only while NULL.
    first_applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Where the draft directory went on delete, relative to the store root.
    trash_path: Mapped[str | None] = mapped_column(Text, nullable=True)


class ModelStoreFile(Base):
    """A weight file that finished uploading into a draft."""

    __tablename__ = "model_store_files"
    __table_args__ = (
        Index("ix_model_store_files_model_filename", "model_pk", "filename", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    model_pk: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_store_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Relative to the store root, e.g. drafts/<model_pk>/weights/hardhat.pt
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(Text, nullable=True)


class ModelStoreUpload(Base, TimestampMixin):
    """A chunked upload session. ``updated_at`` doubles as last activity."""

    __tablename__ = "model_store_uploads"
    __table_args__ = (
        # One in-flight upload per (model, filename): makes init idempotent,
        # which is what lets a reloaded page resume.
        Index(
            "ix_model_store_uploads_active_filename",
            "model_pk",
            "filename",
            unique=True,
            postgresql_where=text("status = 'uploading'"),
        ),
        Index("ix_model_store_uploads_status_updated", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    model_pk: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_store_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_last_modified: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=UPLOAD_STATUS_UPLOADING
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_store_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
