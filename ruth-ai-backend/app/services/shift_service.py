"""Shift schedule persistence and shift-scoped violation counts.

Wraps the pure logic in `app.services.shift_schedule` with the database:
reading and writing the site-global schedule, and answering "how many
violations on this camera are still unreviewed in the shift running right
now".

The count is deliberately computed here rather than in the frontend. The
frontend would otherwise need its own copy of the midnight-crossing
arithmetic and its own clock, and a shift rollover between two polls
would let the window and the counts disagree.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Violation, ViolationStatus
from app.models.app_setting import SHIFT_SCHEDULE_KEY, AppSetting
from app.services.shift_schedule import (
    ShiftSchedule,
    ShiftScheduleError,
    ShiftWindow,
    default_schedule,
    resolve_current_shift,
    validate_schedule,
)

logger = get_logger(__name__)

#: A violation counts towards the shift badge only while it is still
#: waiting on an operator. `reviewed`, `dismissed` and `resolved` have all
#: been acted on. Reopening (dismissed -> open) puts it back in the count,
#: which is correct: the badge reports current unreviewed state, not a
#: running total of everything ever detected.
UNREVIEWED_STATUS = ViolationStatus.OPEN


class ShiftService:
    """Reads/writes the shift schedule and counts against its window."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_schedule(self) -> ShiftSchedule:
        """Return the site schedule, or the continuous default.

        An absent row is not an error — it means the site runs continuous
        monitoring and has not divided the day into shifts.
        """
        stmt = select(AppSetting).where(AppSetting.key == SHIFT_SCHEDULE_KEY)
        result = await self.db.execute(stmt)
        row = result.scalars().first()

        if row is None:
            return default_schedule()

        try:
            return ShiftSchedule.model_validate(row.value)
        except Exception as exc:  # noqa: BLE001
            # A stored value we can no longer parse must not take the
            # monitoring grid down; fall back to continuous and say so.
            logger.error(
                "Stored shift schedule is unreadable, using continuous default",
                error=str(exc),
            )
            return default_schedule()

    async def set_schedule(
        self,
        schedule: ShiftSchedule,
        updated_by: str | None = None,
    ) -> ShiftSchedule:
        """Validate and persist the site schedule.

        Raises:
            ShiftScheduleError: if the shifts overlap or leave a gap.
        """
        validate_schedule(schedule)

        payload = schedule.model_dump(mode="json")

        stmt = select(AppSetting).where(AppSetting.key == SHIFT_SCHEDULE_KEY)
        result = await self.db.execute(stmt)
        row = result.scalars().first()

        if row is None:
            row = AppSetting(key=SHIFT_SCHEDULE_KEY, value=payload, updated_by=updated_by)
            self.db.add(row)
        else:
            row.value = payload
            row.updated_by = updated_by

        await self.db.commit()

        logger.info(
            "Shift schedule updated",
            mode=schedule.mode,
            timezone=schedule.timezone,
            shift_count=len(schedule.shifts),
        )
        return schedule

    async def get_current_window(self, now: datetime | None = None) -> ShiftWindow:
        """Resolve the shift window containing `now` (default: this instant).

        Raises:
            ShiftScheduleError: if the stored schedule leaves `now`
                uncovered. Validation rejects gaps, so this can only
                happen for a schedule written before that rule existed.
        """
        schedule = await self.get_schedule()
        return resolve_current_shift(schedule, now or datetime.now(timezone.utc))

    async def count_unreviewed_by_camera(
        self,
        window: ShiftWindow,
        camera_ids: list[UUID] | None = None,
    ) -> dict[UUID, int]:
        """Count still-unreviewed violations per camera within `window`.

        Counts every model type running on the feed — the badge answers
        "how much is waiting for me on this camera", not "how much of one
        kind".

        The window is half-open, [start, end): a violation detected at the
        rollover instant belongs to the incoming shift only, never both.

        Indexing: measured at 120k violations over 90 days, Postgres serves
        this from `ix_violations_timestamp` — the shift window is the most
        selective predicate, so it walks that range (a few hundred rows)
        and filters status and device_id in memory, ~0.7ms. It does not
        choose `ix_violations_device_status_timestamp`, whose leading
        device_id column would mean one scan per camera on the grid. Both
        indexes already exist; no new one is needed, and the query wants no
        reshaping to coax a different plan.

        Args:
            window: The shift window to count within.
            camera_ids: Restrict to these cameras. None counts all.

        Returns:
            camera_id -> count. Cameras with no matching violations are
            absent; callers backfill zeros for the cameras they asked
            about.
        """
        stmt = (
            select(Violation.device_id, func.count().label("count"))
            .where(
                Violation.status == UNREVIEWED_STATUS,
                Violation.timestamp >= window.start,
                Violation.timestamp < window.end,
            )
            .group_by(Violation.device_id)
        )

        if camera_ids:
            stmt = stmt.where(Violation.device_id.in_(camera_ids))

        result = await self.db.execute(stmt)
        return {row.device_id: row.count for row in result.all()}


__all__ = ["ShiftService", "ShiftScheduleError", "UNREVIEWED_STATUS"]
