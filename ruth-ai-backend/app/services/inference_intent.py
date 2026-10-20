"""Reading and writing what inference an operator wants on a camera.

One module so every writer agrees. The picker, start-inference and
stop-inference all funnel through here, in the caller's transaction, so
intent can never disagree with the action that caused it.

Parking is computed, not stored — see ``parked_until``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import (
    INTENT_ACTIVE,
    INTENT_OFF,
    INTENT_SUSPENDED,
    DeviceInferenceIntent,
)

logger = get_logger(__name__)

#: Consecutive per-camera failures before a camera is parked. Two, not
#: one: a single failure is often a transient VAS hiccup that the next
#: cycle clears, and parking on it would make the reconciler useless on a
#: flaky link.
PARK_AFTER_FAILURES = 2

#: Capped backoff once parked. A parked camera is still retried — it is
#: not given up on — but at a rate that will not hammer a broken camera
#: for hours. The last value repeats.
BACKOFF_MINUTES: tuple[int, ...] = (5, 15, 60)


def backoff_for(consecutive_failures: int) -> timedelta:
    """How long to wait before retrying a parked camera."""
    if consecutive_failures < PARK_AFTER_FAILURES:
        return timedelta(0)
    index = min(consecutive_failures - PARK_AFTER_FAILURES, len(BACKOFF_MINUTES) - 1)
    return timedelta(minutes=BACKOFF_MINUTES[index])


def is_parked(intent: DeviceInferenceIntent) -> bool:
    """Has this camera failed enough times to be parked?

    Derived rather than stored so there is no flag to fall out of step
    with the counter it is supposed to describe.
    """
    return intent.consecutive_failures >= PARK_AFTER_FAILURES


def retry_due_at(intent: DeviceInferenceIntent) -> Optional[datetime]:
    """When a parked camera may next be retried; None if not parked."""
    if not is_parked(intent) or intent.last_attempt_at is None:
        return None
    return intent.last_attempt_at + backoff_for(intent.consecutive_failures)


def may_attempt(intent: DeviceInferenceIntent, now: datetime) -> bool:
    """Is this camera due for a resume attempt?"""
    due = retry_due_at(intent)
    return due is None or now >= due


class InferenceIntentService:
    """Write-through for desired inference state."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get(self, device_id: UUID) -> Optional[DeviceInferenceIntent]:
        result = await self._db.execute(
            select(DeviceInferenceIntent).where(
                DeviceInferenceIntent.device_id == device_id
            )
        )
        return result.scalars().first()

    async def all_active(self) -> Sequence[DeviceInferenceIntent]:
        result = await self._db.execute(
            select(DeviceInferenceIntent).where(
                DeviceInferenceIntent.desired_state == INTENT_ACTIVE
            )
        )
        return list(result.scalars().all())

    async def set_active(
        self,
        device_id: UUID,
        models: list[dict[str, Any]],
        *,
        updated_by: str = "operator",
        inference_fps: int | None = None,
        confidence_threshold: float | None = None,
    ) -> DeviceInferenceIntent:
        """Record that inference is wanted here, with these models.

        Any operator action clears the failure count: the operator has
        changed the situation, so the reconciler's opinion of this camera
        — including that it was parked — is out of date.
        """
        intent = await self.get(device_id)
        if intent is None:
            intent = DeviceInferenceIntent(device_id=device_id)
            self._db.add(intent)
        intent.desired_state = INTENT_ACTIVE
        intent.models = models
        if inference_fps is not None:
            intent.inference_fps = inference_fps
        if confidence_threshold is not None:
            intent.confidence_threshold = confidence_threshold
        intent.consecutive_failures = 0
        intent.last_error = None
        intent.updated_at = datetime.now(timezone.utc)
        intent.updated_by = updated_by
        return intent

    async def set_off(
        self, device_id: UUID, *, updated_by: str = "operator"
    ) -> DeviceInferenceIntent:
        """Record that inference is deliberately stopped here.

        The row is kept, not deleted. A missing row means "never
        configured"; `off` means "somebody decided". The reconciler must
        be able to tell those apart, because it may act on the first and
        must never act on the second.
        """
        intent = await self.get(device_id)
        if intent is None:
            intent = DeviceInferenceIntent(device_id=device_id)
            self._db.add(intent)
        intent.desired_state = INTENT_OFF
        intent.consecutive_failures = 0
        intent.last_error = None
        intent.updated_at = datetime.now(timezone.utc)
        intent.updated_by = updated_by
        return intent

    async def suspend(self, intent: DeviceInferenceIntent) -> None:
        """The camera was disabled in VAS while inference was wanted.

        Keeps `models` untouched. That is the whole point: re-enabling the
        camera must bring back the same analysis without anyone having to
        remember what was running on it, which is exactly the knowledge
        that got lost when a camera went quiet before BL-11.
        """
        intent.desired_state = INTENT_SUSPENDED
        intent.consecutive_failures = 0
        intent.last_error = None
        intent.updated_at = datetime.now(timezone.utc)
        intent.updated_by = "reconciler-disabled"

    async def unsuspend(self, intent: DeviceInferenceIntent) -> None:
        """The camera is enabled again; want its old models back."""
        intent.desired_state = INTENT_ACTIVE
        intent.consecutive_failures = 0
        intent.last_error = None
        intent.updated_at = datetime.now(timezone.utc)
        intent.updated_by = "reconciler-reenabled"

    async def record_attempt(
        self, intent: DeviceInferenceIntent, *, error: str | None
    ) -> None:
        """Note a resume attempt by the reconciler.

        Only per-camera outcomes reach here. A skipped cycle — video
        offline, VAS unreachable — must not call this, or a shared
        outage would park the whole fleet.
        """
        intent.last_attempt_at = datetime.now(timezone.utc)
        if error is None:
            intent.consecutive_failures = 0
            intent.last_error = None
        else:
            intent.consecutive_failures += 1
            intent.last_error = error[:2000]
        intent.updated_by = "reconciler"
