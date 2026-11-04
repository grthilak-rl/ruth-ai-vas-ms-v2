"""Building a customer report in the background, and sweeping old ones.

The violation-export pattern, applied to the PDF: the request creates a
row and returns; a task owns its own session, reports its stage, renders in
a worker thread (ReportLab is CPU-bound and the inference loop shares this
event loop) and writes the file atomically. One report builds at a time;
others wait their turn. Files are kept for the retention period so a report
can be downloaded and resent; the row outlives the file.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.customer_report import CustomerReport
from app.models.violation_export import (
    EXPORT_BUILDING,
    EXPORT_EXPIRED,
    EXPORT_FAILED,
    EXPORT_READY,
)
from app.services.report.data import (
    PRESET_CUSTOM,
    PRESET_DAILY,
    PRESET_SHIFT,
    PRESET_WEEKLY,
    load_gallery,
    load_report,
    preset_range,
)
from app.services.report.pdf import day_range_text, period_days, render_pdf
from app.services.shift_schedule import ShiftSchedule

logger = get_logger(__name__)

STAGES = ("Loading data", "Preparing evidence", "Rendering PDF", "Saving")

#: One build at a time: a report is seconds of CPU, and two at once would
#: only slow both and the inference loop with them.
_build_lock = asyncio.Lock()


class PeriodError(ValueError):
    """A requested period the report cannot cover; the message is for the user."""


def report_period(
    preset: str,
    schedule: ShiftSchedule,
    *,
    day: date | None = None,
    start: date | None = None,
    end: date | None = None,
    today: date | None = None,
    shift: str | None = None,
    now: datetime | None = None,
) -> tuple[datetime, datetime, str]:
    """(start UTC, end UTC exclusive, label) for a request.

    Daily and weekly follow the shift day; a shift report is one shift of a
    shift day; custom runs midnight to midnight over both dates inclusive.
    """
    tz = schedule.tzinfo
    today = today or datetime.now(tz).date()
    max_days = get_settings().customer_report_max_days
    if preset == PRESET_SHIFT:
        if day is None or not shift:
            raise PeriodError("Pick a day and a shift.")
        try:
            lo, hi = preset_range(preset, day, schedule, shift)
        except ValueError as e:
            raise PeriodError(str(e)) from e
        if lo > (now or datetime.now(timezone.utc)):
            raise PeriodError("That shift has not started yet.")
        return lo, hi, f"{shift}, {day_range_text(day, day, long=False)}"
    if preset in (PRESET_DAILY, PRESET_WEEKLY):
        if day is None:
            raise PeriodError("Pick a day.")
        if day > today:
            raise PeriodError("The day is in the future.")
        lo, hi = preset_range(preset, day, schedule)
        first = day if preset == PRESET_DAILY else day - timedelta(days=6)
        return lo, hi, day_range_text(first, day, long=False)
    if preset == PRESET_CUSTOM:
        if start is None or end is None:
            raise PeriodError("Pick a start and an end date.")
        if end < start:
            raise PeriodError("The end date is before the start date.")
        if start > today:
            raise PeriodError("The period starts in the future.")
        if (end - start).days + 1 > max_days:
            raise PeriodError(f"A custom period can be at most {max_days} days.")
        lo = datetime.combine(start, time(0), tzinfo=tz).astimezone(timezone.utc)
        hi = datetime.combine(end + timedelta(days=1), time(0), tzinfo=tz).astimezone(timezone.utc)
        return lo, hi, day_range_text(start, end, long=False)
    raise PeriodError(f"Unknown period type {preset!r}.")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")


def report_filename(
    customer: str | None, preset: str, first: date, last: date, shift: str | None = None
) -> str:
    """'HPCL-daily-safety-report-2026-11-03.pdf', '...-shift-...-2026-11-03-Shift-1.pdf'."""
    span = f"{first:%Y-%m-%d}" if first == last else f"{first:%Y-%m-%d}_to_{last:%Y-%m-%d}"
    if shift and _slug(shift):
        span += f"-{_slug(shift)}"
    prefix = f"{_slug(customer)}-" if customer and _slug(customer) else ""
    return f"{prefix}{preset}-safety-report-{span}.pdf"


async def _touch(db: AsyncSession, report_id: uuid.UUID, **values) -> None:
    values["updated_at"] = datetime.now(timezone.utc)
    await db.execute(update(CustomerReport).where(CustomerReport.id == report_id).values(**values))
    await db.commit()


async def _stage(db: AsyncSession, report_id: uuid.UUID, index: int) -> None:
    await _touch(db, report_id, stage=STAGES[index], done=index, total=len(STAGES))


def _write(path: Path, data: bytes) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.partial")
    tmp.write_bytes(data)
    tmp.replace(path)
    return len(data)


async def run_report_job(report_id: uuid.UUID, session_factory) -> None:
    """Build the report for an already-created row. Owns its own session."""
    out_dir = Path(get_settings().customer_report_dir)
    try:
        async with _build_lock, session_factory() as db:
            row = await db.get(CustomerReport, report_id)
            if row is None:
                return
            options = row.options or {}
            await _stage(db, report_id, 0)
            report = await load_report(
                db,
                start=row.period_start,
                end=row.period_end,
                preset=row.preset,
                mode=row.mode,
                shift=row.shift_name,
            )

            await _stage(db, report_id, 1)
            if options.get("gallery", True):
                report.gallery = await load_gallery(
                    db,
                    report,
                    int(options.get("gallery_size", 12)),
                    exclude=options.get("gallery_exclude") or (),
                )

            await _stage(db, report_id, 2)
            pdf = await run_in_threadpool(render_pdf, report)

            await _stage(db, report_id, 3)
            first, last = period_days(report)
            filename = report_filename(
                report.branding.customer_name, row.preset, first, last, row.shift_name
            )
            path = out_dir / f"{report_id}.pdf"
            size = await run_in_threadpool(_write, path, pdf)
            await _touch(
                db,
                report_id,
                status=EXPORT_READY,
                stage=None,
                done=len(STAGES),
                file_path=str(path),
                filename=filename,
                size_bytes=size,
                incidents=report.current.incidents,
                expires_at=datetime.now(timezone.utc)
                + timedelta(days=get_settings().customer_report_retention_days),
            )
            logger.info(
                "Customer report ready",
                report_id=str(report_id),
                preset=row.preset,
                incidents=report.current.incidents,
                gallery=len(report.gallery),
                size_kb=size // 1024,
            )
    except Exception as e:  # noqa: BLE001 - a failed job must say so
        logger.error("Customer report failed", report_id=str(report_id), error=str(e))
        try:
            async with session_factory() as db:
                await _touch(db, report_id, status=EXPORT_FAILED, stage=None, error=str(e)[:2000])
        except Exception:
            logger.error("Could not mark report failed", report_id=str(report_id))


async def sweep_customer_reports(session_factory, *, now: datetime | None = None) -> dict:
    """Delete report files past retention; fail builds a restart abandoned."""
    now = now or datetime.now(timezone.utc)
    removed = abandoned = 0
    async with session_factory() as db:
        rows = (
            await db.execute(
                select(CustomerReport).where(
                    CustomerReport.status.in_([EXPORT_READY, EXPORT_BUILDING])
                )
            )
        ).scalars().all()
        for row in rows:
            if row.status == EXPORT_READY and row.expires_at and row.expires_at <= now:
                if row.file_path:
                    try:
                        await run_in_threadpool(Path(row.file_path).unlink, True)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Could not delete expired report", report_id=str(row.id), error=str(e))
                row.status = EXPORT_EXPIRED
                row.file_path = None
                row.updated_at = now
                removed += 1
            elif row.status == EXPORT_BUILDING and now - row.updated_at > timedelta(hours=1):
                row.status = EXPORT_FAILED
                row.error = "build did not finish (backend restarted)"
                row.stage = None
                row.updated_at = now
                abandoned += 1
        if removed or abandoned:
            await db.commit()
    if removed or abandoned:
        logger.info("Swept customer reports", removed=removed, abandoned=abandoned)
    return {"removed": removed, "abandoned": abandoned}
