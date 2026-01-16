"""SQLAlchemy base model and mixins.

Provides:
- Declarative base for all models
- Common timestamp mixin for created_at/updated_at
- UUID primary key generation
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models.

    All models inherit from this class to share:
    - Common type annotations
    - Metadata for migrations
    - Table naming conventions
    """

    pass


class TimestampMixin:
    """Mixin providing created_at and updated_at timestamps.

    Timestamps are always stored in UTC.
    - created_at: Set once at insert time
    - updated_at: Updated on every modification
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


def generate_uuid() -> uuid.UUID:
    """Generate a new UUID v4 for primary keys."""
    return uuid.uuid4()
