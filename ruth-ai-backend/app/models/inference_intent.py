"""What inference an operator *wants* running on a camera.

Separate from `devices` on purpose. Device rows are overwritten wholesale
by the VAS sync (`_sync_single_device`), so anything stored there is one
sync away from being silently reset — which is exactly how camera 74004
ran 21.3 hours with no inference and nothing said so (BL-11).

Separate from `stream_sessions` too, because a session records what *is*
happening. When the backend restarts, a session dies, or VAS drops a
stream, the session is gone and with it any record that somebody had
asked for inference at all. Intent has to outlive the thing it describes.

"Parked" is deliberately **not** a column. It is derived from
`consecutive_failures` and `last_attempt_at` by the reconciler, so there
is one source of truth and no state machine to get out of step with
itself. Two fields can disagree; a function cannot.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_uuid

#: desired_state values. Plain strings rather than an enum: this table is
#: written from several paths, and adding a value should not need a
#: migration — `suspended` was added a day after the table shipped.
INTENT_ACTIVE = "active"
INTENT_OFF = "off"
#: The camera was disabled in VAS while inference was wanted. Distinct
#: from `off`: nobody decided to stop analysing this camera, so the
#: models are kept and inference resumes by itself when the camera comes
#: back. Collapsing the two would mean re-enabling a camera silently
#: leaves it unmonitored, which is the failure BL-11 exists to prevent.
INTENT_SUSPENDED = "suspended"


class DeviceInferenceIntent(Base):
    """One row per camera: the inference an operator asked for.

    `off` is as meaningful as `active`. An operator who stops inference,
    or unticks the last model, is making a decision — and the reconciler
    must never override it. That is why stopping writes `off` rather than
    deleting the row: a missing row means "never configured", which is a
    different thing from "deliberately stopped".

    `suspended` is the third case and belongs to the system, not the
    operator: the camera was disabled in VAS while inference was wanted.
    The models stay recorded, so re-enabling the camera brings the same
    analysis back without anyone having to remember what was running.
    """

    __tablename__ = "device_inference_intent"
    __table_args__ = (
        Index("ix_intent_desired_state", "desired_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )

    #: One intent per device. ON DELETE CASCADE: a deleted camera has no
    #: intent, and a dangling row would make the reconciler chase a ghost.
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    desired_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=INTENT_ACTIVE
    )

    #: Same shape as stream_sessions.models, so a resume can hand it
    #: straight back without translation.
    models: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    inference_fps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: Per-camera failures only. A shared-dependency outage (VAS down, a
    #: runtime unreachable) must not park every camera at once, so the
    #: reconciler skips those cycles without touching this.
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Who last changed the intent. "operator" vs "reconciler" matters:
    #: any operator action resets the failure count, a reconciler attempt
    #: does not.
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<DeviceInferenceIntent device={self.device_id} "
            f"{self.desired_state} failures={self.consecutive_failures}>"
        )
