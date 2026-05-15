"""BookmarkAnalysis model — async AI analysis jobs against VAS bookmarks.

A row represents one submitted analysis of a recorded bookmark. The job
lifecycle is async: API submits, worker picks it up, summary is written
when complete. Independent of the live InferenceLoop — bookmarks are
recorded video, not live streams.

vas_bookmark_id is a foreign reference to VAS, not Ruth. We never own
the bookmark; we annotate it.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_uuid
from app.models.enums import BookmarkAnalysisState


class BookmarkAnalysis(Base):
    """Async AI analysis job against a VAS bookmark.

    Each submission creates a new row. Re-runs of the same bookmark with
    different parameters are separate rows — analyses are immutable
    after they complete, so callers compare runs side by side instead
    of mutating an existing one.

    No relationships to other Ruth tables: bookmarks live in VAS.

    Indexes:
    - vas_bookmark_id  (list analyses for a specific bookmark)
    - state            (find pending/running jobs)
    - created_at DESC  (chronological listing of recent runs)
    """

    __tablename__ = "bookmark_analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=generate_uuid,
    )

    # VAS bookmark identifier — foreign reference, not a FK constraint.
    vas_bookmark_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    # AI model selection
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Submission-time parameters (e.g., tank_corners, capacity_liters).
    # Stored verbatim so a future re-run can be reproduced.
    parameters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    state: Mapped[BookmarkAnalysisState] = mapped_column(
        ENUM(
            BookmarkAnalysisState,
            name="bookmark_analysis_state",
            create_type=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        default=BookmarkAnalysisState.PENDING,
        nullable=False,
        index=True,
    )

    # Result blob — model-specific shape, set only when state=COMPLETED.
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Set only when state=FAILED.
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Lifecycle timestamps (explicit — no TimestampMixin here because we
    # don't track updated_at; immutability after terminal state means the
    # row should not be mutated again).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Future hook for user tracking (auth not wired yet — nullable).
    submitted_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<BookmarkAnalysis(id={self.id}, "
            f"vas_bookmark_id={self.vas_bookmark_id}, "
            f"model_id={self.model_id}, state={self.state.value})>"
        )
