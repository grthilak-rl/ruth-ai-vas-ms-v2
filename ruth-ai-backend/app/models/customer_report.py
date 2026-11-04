"""A customer report (PDF), built in the background and kept for re-download.

Same shape and lifecycle as ``violation_exports`` (building -> ready ->
expired, or failed), for the same reasons: a month's report takes seconds,
the backend can restart mid-build, and the file must outlive the request so
the same report can be downloaded and resent later. Expired rows stay: who
generated which report for which period is the audit trail.

``done``/``total`` count build stages, not rows; ``stage`` names the
current one for the progress bar.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_uuid
from app.models.violation_export import EXPORT_BUILDING


class CustomerReport(Base):
    """One requested customer report."""

    __tablename__ = "customer_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=EXPORT_BUILDING)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    format: Mapped[str] = mapped_column(String(8), nullable=False, default="pdf")
    #: daily, weekly or custom.
    preset: Mapped[str] = mapped_column(String(16), nullable=False)
    #: all or verified.
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: As the report names it, e.g. "3 November 2026" or "28 Oct – 3 Nov 2026".
    period_label: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The request as received (gallery, gallery size, ...).
    options: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Incidents in the report, for the recent list.
    incidents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_customer_reports_status_expires", "status", "expires_at"),
        Index("ix_customer_reports_created_at", "created_at"),
    )
