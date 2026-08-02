"""Site-global application settings.

A small key/value store for configuration that belongs to the site rather
than to a user, a device or a session — the kind of thing that must
survive a browser change and be identical for every operator looking at
the same plant.

Kept generic on purpose: the shift schedule is the first tenant (key
`shift_schedule`), and later site-wide settings can join it without a
migration each time. The value is JSONB and its shape is owned by a
Pydantic model in the service layer, which is also where validation that
the database cannot express — such as "shifts must not overlap" — lives.
"""

import uuid
from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid

#: Key under which the site-global shift schedule is stored.
SHIFT_SCHEDULE_KEY = "shift_schedule"


class AppSetting(Base, TimestampMixin):
    """One site-global setting.

    Attributes:
        key: Stable identifier, unique across the site (e.g. "shift_schedule").
        value: JSONB payload; shape depends on the key.
        updated_by: Operator who last wrote this setting, when known.
    """

    __tablename__ = "app_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=generate_uuid,
    )

    key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )

    value: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )

    updated_by: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<AppSetting(key={self.key})>"
