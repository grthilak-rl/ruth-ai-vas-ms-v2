"""Automatic per-shift customer reports.

Every minute, while auto reports are on and the project is active, the
scheduler makes sure every shift that ended at least ``settle_minutes`` ago
has a report, looking back to when auto reports were switched on (or the
project was last resumed), at most 7 days. Off by default.

Restart-safe by construction:

- The customer_reports table is the queue. Each tick inserts the missing
  shift occurrences with ON CONFLICT DO NOTHING against a unique index on
  (preset, period) for auto rows, so a restart, a retry or two schedulers
  cannot create a duplicate, and a shift missed while the backend was down
  is simply found missing on the next tick.
- A build is remembered only in this process. An auto row left "building"
  by a restart, or that failed, is started again until it has been tried
  MAX_AUTO_ATTEMPTS times, then given up with a reason.
- Shift occurrences come from the schedule as it is now; a row stores its
  own period, so editing the schedule affects future shifts only.

Idle while the project is not active, or auto reports are off, or there is
no shift schedule; the reason is logged once per change, not every minute.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.app_setting import AUTO_REPORTS_KEY, AppSetting
from app.models.customer_report import TRIGGER_AUTO, CustomerReport
from app.models.violation_export import EXPORT_BUILDING, EXPORT_FAILED
from app.services.report.data import PRESET_SHIFT, report_day_of, day_offset_minutes, shift_occurrence
from app.services.shift_schedule import ShiftSchedule

logger = get_logger(__name__)

TICK_SECONDS = 60
LOOKBACK = timedelta(days=7)
MAX_AUTO_ATTEMPTS = 3
DEFAULT_SETTLE_MINUTES = 15
#: Defaults for auto reports: the same as the Export page's defaults.
AUTO_OPTIONS = {"format": "pdf", "mode": "all", "gallery": True, "gallery_size": 12, "gallery_exclude": []}


class AutoReportSettings(BaseModel):
    enabled: bool = False
    settle_minutes: int = Field(default=DEFAULT_SETTLE_MINUTES, ge=0, le=240)
    #: When auto reports were last switched on: the lookback never reaches
    #: before it, so switching on does not back-fill a week of reports.
    enabled_at: datetime | None = None


async def get_auto_settings(db: AsyncSession) -> tuple[AutoReportSettings, AppSetting | None]:
    row = (
        await db.execute(select(AppSetting).where(AppSetting.key == AUTO_REPORTS_KEY))
    ).scalars().first()
    if row is None:
        return AutoReportSettings(), None
    try:
        return AutoReportSettings.model_validate(row.value), row
    except Exception as exc:  # noqa: BLE001
        logger.error("Stored auto-report settings unreadable; auto reports off", error=str(exc))
        return AutoReportSettings(), row


async def save_auto_settings(
    db: AsyncSession, *, enabled: bool, settle_minutes: int, by: str | None, now: datetime | None = None
) -> AutoReportSettings:
    current, row = await get_auto_settings(db)
    now = now or datetime.now(timezone.utc)
    settings = AutoReportSettings(
        enabled=enabled,
        settle_minutes=settle_minutes,
        enabled_at=(now if enabled and not current.enabled else current.enabled_at if enabled else None),
    )
    value = settings.model_dump(mode="json")
    if row is None:
        db.add(AppSetting(key=AUTO_REPORTS_KEY, value=value, updated_by=by))
    else:
        row.value = value
        row.updated_by = by
    await db.commit()
    return settings


# ---------------------------------------------------------------------------
# Decisions (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Occurrence:
    day: date
    shift: str
    start: datetime
    end: datetime


def lookback_start(now: datetime, enabled_at: datetime | None, resumed_at: datetime | None) -> datetime:
    """The earliest a due shift may end: switched on, resumed, 7 days."""
    since = now - LOOKBACK
    for t in (enabled_at, resumed_at):
        if t and t > since:
            since = t
    return since


def due_occurrences(
    schedule: ShiftSchedule, now: datetime, since: datetime, settle: timedelta
) -> list[Occurrence]:
    """Shift occurrences that ended in (since, now - settle], oldest first."""
    if schedule.mode != "shifts" or not schedule.shifts:
        return []
    tz, offset = schedule.tzinfo, day_offset_minutes(schedule)
    cutoff = now - settle
    first = report_day_of(since.astimezone(tz), offset) - timedelta(days=1)
    last = report_day_of(now.astimezone(tz), offset)
    out = []
    day = first
    while day <= last:
        for s in schedule.shifts:
            start, end = shift_occurrence(day, schedule, s.name)
            if since < end <= cutoff:
                out.append(Occurrence(day, s.name, start, end))
        day += timedelta(days=1)
    return sorted(out, key=lambda o: o.start)


def missing(due: list[Occurrence], existing: set[tuple[datetime, datetime]]) -> list[Occurrence]:
    """Due occurrences with no auto report yet (by exact period)."""
    return [o for o in due if (o.start, o.end) not in existing]


START = "start"
GIVE_UP = "give_up"


def next_action(status: str, attempts: int, running_here: bool) -> str | None:
    """What to do with an auto row this tick.

    building + not running in this process = new, or interrupted by a
    restart; failed = a build that raised. Either is (re)started until it
    has been tried MAX_AUTO_ATTEMPTS times.
    """
    if running_here or status not in (EXPORT_BUILDING, EXPORT_FAILED):
        return None
    if attempts < MAX_AUTO_ATTEMPTS:
        return START
    return GIVE_UP if status == EXPORT_BUILDING else None


def occurrence_label(o: Occurrence) -> str:
    from app.services.report.pdf import day_range_text

    return f"{o.shift}, {day_range_text(o.day, o.day, long=False)}"


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


class AutoReportScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        #: Report ids being built by this process.
        self._running: set[uuid.UUID] = set()
        #: Why the last tick did nothing, to log only changes.
        self._idle_for: str | None = None
        self.last_tick_at: datetime | None = None

    @property
    def idle_reason(self) -> str | None:
        return self._idle_for

    def _idle(self, reason: str) -> dict:
        if reason != self._idle_for:
            logger.info("Auto shift reports idle", reason=reason)
            self._idle_for = reason
        return {"idle": reason}

    def _active(self) -> None:
        if self._idle_for is not None:
            logger.info("Auto shift reports active", previously=self._idle_for)
            self._idle_for = None

    async def tick(self, session_factory, now: datetime | None = None, launch=None) -> dict:
        from app.services.project_lifecycle import current_project, is_running, site_state
        from app.services.shift_service import ShiftService

        now = now or datetime.now(timezone.utc)
        self.last_tick_at = now
        async with session_factory() as db:
            state = await site_state(db)
            if not is_running(state):
                return self._idle(f"project {state}")
            settings, _ = await get_auto_settings(db)
            if not settings.enabled:
                return self._idle("auto reports are off")
            schedule = await ShiftService(db).get_schedule()
            if schedule.mode != "shifts" or not schedule.shifts:
                return self._idle("no shift schedule")
            self._active()

            project = await current_project(db)
            since = lookback_start(now, settings.enabled_at, project.resumed_at if project else None)
            due = due_occurrences(schedule, now, since, timedelta(minutes=settings.settle_minutes))
            queued = await self._enqueue(db, due, now)
            to_start = await self._claim(db, now - LOOKBACK - timedelta(days=1))

        for report_id in to_start:
            self._launch(report_id, session_factory, launch)
        return {"due": len(due), "queued": queued, "started": len(to_start)}

    async def _enqueue(self, db: AsyncSession, due: list[Occurrence], now: datetime) -> int:
        if not due:
            return 0
        existing = set(
            (
                await db.execute(
                    select(CustomerReport.period_start, CustomerReport.period_end).where(
                        CustomerReport.trigger == TRIGGER_AUTO,
                        CustomerReport.preset == PRESET_SHIFT,
                        CustomerReport.period_start >= due[0].start,
                    )
                )
            ).all()
        )
        todo = missing(due, existing)
        for o in todo:
            options = {**AUTO_OPTIONS, "preset": PRESET_SHIFT, "day": o.day.isoformat(), "shift": o.shift}
            stmt = (
                insert(CustomerReport)
                .values(
                    id=uuid.uuid4(),
                    status=EXPORT_BUILDING,
                    stage="Queued",
                    done=0,
                    total=4,
                    format="pdf",
                    preset=PRESET_SHIFT,
                    mode="all",
                    period_start=o.start,
                    period_end=o.end,
                    period_label=occurrence_label(o),
                    options=options,
                    trigger=TRIGGER_AUTO,
                    shift_name=o.shift,
                    attempts=0,
                    created_by=None,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=["preset", "period_start", "period_end"],
                    index_where=CustomerReport.trigger == TRIGGER_AUTO,
                )
            )
            await db.execute(stmt)
        await db.commit()
        if todo:
            logger.info("Auto shift reports queued", count=len(todo), first=occurrence_label(todo[0]))
        return len(todo)

    async def _claim(self, db: AsyncSession, horizon: datetime) -> list[uuid.UUID]:
        rows = (
            await db.execute(
                select(CustomerReport).where(
                    CustomerReport.trigger == TRIGGER_AUTO,
                    CustomerReport.status.in_((EXPORT_BUILDING, EXPORT_FAILED)),
                    CustomerReport.created_at >= horizon,
                )
            )
        ).scalars().all()
        start: list[uuid.UUID] = []
        now = datetime.now(timezone.utc)
        for row in rows:
            action = next_action(row.status, row.attempts, row.id in self._running)
            if action == START:
                await db.execute(
                    update(CustomerReport)
                    .where(CustomerReport.id == row.id)
                    .values(status=EXPORT_BUILDING, error=None, stage="Queued",
                            attempts=row.attempts + 1, updated_at=now)
                )
                start.append(row.id)
            elif action == GIVE_UP:
                await db.execute(
                    update(CustomerReport)
                    .where(CustomerReport.id == row.id)
                    .values(status=EXPORT_FAILED, stage=None, updated_at=now,
                            error=f"gave up after {MAX_AUTO_ATTEMPTS} attempts")
                )
        await db.commit()
        return start

    def _launch(self, report_id: uuid.UUID, session_factory, launch) -> None:
        from app.services.report.job import run_report_job

        self._running.add(report_id)
        coro = (launch or run_report_job)(report_id, session_factory)
        task = asyncio.ensure_future(coro)
        task.add_done_callback(lambda _t: self._running.discard(report_id))

    async def _loop(self) -> None:
        from app.core.database import get_session_factory

        while True:
            try:
                factory = get_session_factory()
                if factory is not None:
                    await self.tick(factory)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - keep scheduling
                logger.warning("Auto shift report tick failed", error=str(e))
            await asyncio.sleep(TICK_SECONDS)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="auto-shift-reports")
            logger.info("Auto shift report scheduler started", tick_seconds=TICK_SECONDS)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


auto_report_scheduler = AutoReportScheduler()
