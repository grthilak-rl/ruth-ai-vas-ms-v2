"""Everything the customer report says, computed once from the database.

The headline unit is the incident (``app.services.incidents``), not the raw
detection: one person without gloves for ten minutes is one incident and a
dozen detections. Counting rules:

- Dismissed detections never count: false alarms, duplicates and
  exemptions alike. Operators only dismiss the obvious ones, so everything
  else counts by default.
- "verified" mode keeps only incidents with at least one member reviewed or
  resolved. It is optional and labelled as such on every page.
- Dismissed detections are grouped the same way and reported per type as a
  small note, so the customer sees how many alarms were set aside.

Presets set the windows (``report_windows``):

- daily: one shift day (start of the first shift -> same time next day),
  compared with the average of the 7 shift days before it; the over-time
  chart shows the last 30 days; a project-to-date block is added.
- weekly: 7 shift days, compared with the 7 before.
- custom: any range, compared with the same length immediately before.

Incidents never cross a report-day boundary (midnight, or the first shift's
start for daily/weekly), so a day's figure is the same in every report and
the per-day bars add up to the headline.

Comparisons use incidents per covered day, not totals: the baseline may
start before the current project (its data archived), and the current
period may run past now. A baseline with less than a day of data has no
comparison at all.

``build_report`` is pure (rows in, ReportData out) so it is unit-tested
without a database; ``load_report`` does the queries.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models import Device, Violation
from app.models.enums import EvidenceStatus, EvidenceType, ViolationStatus
from app.models.evidence import Evidence
from app.models.project import Project
from app.services.incidents import group_incidents
from app.services.report.branding import ReportBranding, get_branding
from app.services.shift_schedule import ShiftSchedule
from app.services.shift_service import ShiftService
from app.services.violation_labels import ViolationLabeler
from app.services.violation_severity import SEVERITY_RANK

logger = get_logger(__name__)

MODE_ALL = "all"
MODE_VERIFIED = "verified"

MODE_LABELS = {
    MODE_ALL: "All incidents, excluding those dismissed by an operator",
    MODE_VERIFIED: "Verified incidents only (reviewed or resolved by an operator)",
}

PRESET_DAILY = "daily"
PRESET_WEEKLY = "weekly"
PRESET_CUSTOM = "custom"
PRESETS = (PRESET_DAILY, PRESET_WEEKLY, PRESET_CUSTOM)

#: Daily reports compare with the average of this many days before.
DAILY_BASELINE_DAYS = 7
#: Daily reports chart this many days, ending with the report day.
DAILY_TREND_DAYS = 30

VERIFIED_STATUSES = {ViolationStatus.REVIEWED.value, ViolationStatus.RESOLVED.value}
DISMISSED = ViolationStatus.DISMISSED.value
UNASSIGNED_AREA = "Unassigned"
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

#: A baseline with less coverage than this has no comparison.
MIN_COMPARISON_DAYS = 1.0
#: A type first seen this soon after the project started was there from the
#: start: the partial-coverage note covers it, not a rollout note.
ROLLOUT_GRACE = timedelta(days=1)
#: Silence this long before the period ends reads as a type that stopped.
STOPPED_AFTER = timedelta(hours=48)


def _value(v) -> str:
    return getattr(v, "value", v)


@dataclass(frozen=True)
class Camera:
    name: str
    area: str


@dataclass
class ReportIncident:
    key: str
    area: str
    camera: str
    #: ViolationType value, e.g. "ppe_violation".
    family: str
    type_label: str
    severity: str
    #: Local (report timezone).
    started_at: datetime
    ended_at: datetime
    detections: int
    verified: bool
    shift: str | None
    #: Member ids, highest confidence first: the gallery's frame candidates.
    frame_candidates: list[UUID] = field(default_factory=list)

    @property
    def duration_minutes(self) -> float:
        return (self.ended_at - self.started_at).total_seconds() / 60


@dataclass
class Window:
    start: datetime
    end: datetime
    #: Days of [start, end) that have data: inside the project, before now.
    covered_days: float

    @property
    def days(self) -> float:
        return (self.end - self.start).total_seconds() / 86400


@dataclass(frozen=True)
class Windows:
    """Where a preset reads data; all UTC, ends exclusive."""

    start: datetime
    end: datetime
    baseline_start: datetime
    trend_start: datetime
    #: Minutes after local midnight that a report day starts.
    day_offset: int
    project_to_date: bool

    def fetch_from(self, data_from: datetime | None) -> datetime:
        lo = min(self.start, self.baseline_start, self.trend_start)
        if self.project_to_date and data_from:
            lo = min(lo, data_from)
        return lo


@dataclass
class ShiftStat:
    name: str
    start: str
    end: str
    incidents: int
    #: Hours this shift ran during the covered part of the period.
    hours: float

    @property
    def per_hour(self) -> float:
        return self.incidents / self.hours if self.hours else 0.0

    @property
    def hours_label(self) -> str:
        return f"{self.start}–{self.end}"


@dataclass
class PeriodTotals:
    incidents: int
    detections: int
    by_area: Counter
    by_type: Counter
    by_shift: Counter
    #: (area, type label) -> incidents.
    by_area_type: Counter = field(default_factory=Counter)


@dataclass
class AreaSummary:
    name: str
    incidents: int
    baseline_incidents: int
    by_type: Counter
    by_camera: Counter


@dataclass(frozen=True)
class RolloutNote:
    type_label: str
    #: "began" or "stopped".
    kind: str
    #: Local.
    at: datetime


@dataclass
class GalleryItem:
    incident: ReportIncident
    #: JPEG of the inferred frame cropped around the boxes; None without one.
    image: bytes | None


@dataclass
class ProjectToDate:
    since: datetime
    days: float
    totals: PeriodTotals


@dataclass
class ReportData:
    branding: ReportBranding
    project_name: str | None
    mode: str
    preset: str
    timezone: str
    period: Window
    previous: Window
    generated_at: datetime
    gap_minutes: int
    max_span_minutes: int
    day_offset: int

    #: Oldest first.
    incidents: list[ReportIncident]
    current: PeriodTotals
    prev: PeriodTotals
    areas: list[AreaSummary]
    #: Type label -> incidents dismissed by an operator in the period.
    dismissed_by_type: Counter
    #: Report days of the over-time chart (the period, or the last 30 for daily).
    by_day: list[tuple[date, int]]
    #: [weekday 0=Mon][hour] incident starts.
    heatmap: list[list[int]]
    shifts: list[ShiftStat]
    rollout: list[RolloutNote]
    project_to_date: ProjectToDate | None
    #: Filled by ``load_gallery``; empty when the gallery is off.
    gallery: list[GalleryItem] = field(default_factory=list)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def mode_label(self) -> str:
        return MODE_LABELS[self.mode]

    @property
    def is_daily(self) -> bool:
        return self.preset == PRESET_DAILY

    @property
    def report_day(self) -> date:
        return report_day_of(self.period.start.astimezone(self.tz), self.day_offset)

    @property
    def baseline_label(self) -> str:
        """How the comparison is named in sentences: 'the previous period'."""
        if self.is_daily:
            return f"the {DAILY_BASELINE_DAYS}-day average"
        return "the previous period"

    @property
    def has_comparison(self) -> bool:
        return self.previous.covered_days >= MIN_COMPARISON_DAYS

    @property
    def comparison_partial(self) -> bool:
        return self.has_comparison and self.previous.covered_days < self.previous.days - 0.01

    @property
    def period_incomplete(self) -> bool:
        return self.period.covered_days < self.period.days - 0.01

    def per_day(self, count: int, window: Window) -> float:
        return count / window.covered_days if window.covered_days else 0.0

    @property
    def incidents_per_day(self) -> float:
        return self.per_day(self.current.incidents, self.period)

    @property
    def prev_incidents_per_day(self) -> float | None:
        return self.per_day(self.prev.incidents, self.previous) if self.has_comparison else None

    def change(self, current: int, previous: int) -> float | None:
        """Relative change of the per-covered-day rate, or None."""
        if not self.has_comparison:
            return None
        prev_rate = self.per_day(previous, self.previous)
        if prev_rate == 0:
            return None
        return self.per_day(current, self.period) / prev_rate - 1

    @property
    def by_area(self) -> list[tuple[str, int]]:
        return self.current.by_area.most_common()

    @property
    def by_type(self) -> list[tuple[str, int]]:
        return self.current.by_type.most_common()

    @property
    def rollout_types(self) -> set[str]:
        return {n.type_label for n in self.rollout}


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------


def day_offset_minutes(schedule: ShiftSchedule) -> int:
    """A report day starts with the schedule's first shift, else at midnight."""
    if schedule.mode == "shifts" and schedule.shifts:
        return schedule.shifts[0].start_minute
    return 0


def report_day_of(local: datetime, offset: int) -> date:
    return (local - timedelta(minutes=offset)).date()


def day_start(day: date, schedule: ShiftSchedule) -> datetime:
    """UTC start of a report day: the first shift's start, local time."""
    offset = day_offset_minutes(schedule)
    local = datetime.combine(day, time(offset // 60, offset % 60), tzinfo=schedule.tzinfo)
    return local.astimezone(timezone.utc)


def preset_range(preset: str, day: date, schedule: ShiftSchedule) -> tuple[datetime, datetime]:
    """[start, end) of a daily report for ``day``, or a weekly one ending on it."""
    if preset == PRESET_DAILY:
        return day_start(day, schedule), day_start(day + timedelta(days=1), schedule)
    if preset == PRESET_WEEKLY:
        return day_start(day - timedelta(days=6), schedule), day_start(day + timedelta(days=1), schedule)
    raise ValueError(f"No preset range for {preset!r}")


def report_windows(preset: str, start: datetime, end: datetime, schedule: ShiftSchedule) -> Windows:
    if preset not in PRESETS:
        raise ValueError(f"Unknown report preset: {preset!r}")
    if preset == PRESET_DAILY:
        return Windows(
            start=start,
            end=end,
            baseline_start=start - timedelta(days=DAILY_BASELINE_DAYS),
            trend_start=end - timedelta(days=DAILY_TREND_DAYS),
            day_offset=day_offset_minutes(schedule),
            project_to_date=True,
        )
    return Windows(
        start=start,
        end=end,
        baseline_start=start - (end - start),
        trend_start=start,
        day_offset=day_offset_minutes(schedule) if preset == PRESET_WEEKLY else 0,
        project_to_date=False,
    )


# ---------------------------------------------------------------------------
# Pure part
# ---------------------------------------------------------------------------


def covered_days(start: datetime, end: datetime, data_from: datetime | None, now: datetime) -> float:
    lo = max(start, data_from) if data_from else start
    hi = min(end, now)
    return max((hi - lo).total_seconds(), 0) / 86400


def shift_of(local: datetime, schedule: ShiftSchedule) -> str | None:
    if schedule.mode != "shifts":
        return None
    minute = local.hour * 60 + local.minute
    for s in schedule.shifts:
        if (minute - s.start_minute) % 1440 < s.duration_minutes:
            return s.name
    return None


def _shift_hours(schedule: ShiftSchedule, start: datetime, end: datetime, tz: ZoneInfo) -> Counter:
    """Hours each shift ran in [start, end), walked at 15-minute resolution."""
    hours: Counter = Counter()
    if schedule.mode != "shifts" or end <= start:
        return hours
    step = timedelta(minutes=15)
    t = start
    while t < end:
        name = shift_of(t.astimezone(tz), schedule)
        if name:
            hours[name] += min(step, end - t).total_seconds() / 3600
        t += step
    return hours


def rollout_notes(
    seen: dict[str, tuple[datetime, datetime]],
    baseline_start: datetime,
    end: datetime,
    data_from: datetime | None,
    tz: ZoneInfo,
) -> list[RolloutNote]:
    """Types whose detection began or stopped inside [baseline_start, end).

    ``seen`` is each type's first and last detection ever (any status), so a
    quiet stretch inside the window is not mistaken for a start.
    """
    notes: list[RolloutNote] = []
    for label, (first, last) in sorted(seen.items()):
        from_start = data_from is not None and first < data_from + ROLLOUT_GRACE
        if baseline_start < first < end and not from_start:
            notes.append(RolloutNote(label, "began", first.astimezone(tz)))
        if baseline_start <= last and end - last >= STOPPED_AFTER:
            notes.append(RolloutNote(label, "stopped", last.astimezone(tz)))
    return notes


def build_report(
    *,
    rows: Sequence,
    cameras: dict[UUID, Camera],
    labeler: ViolationLabeler,
    schedule: ShiftSchedule,
    branding: ReportBranding,
    project_name: str | None,
    start: datetime,
    end: datetime,
    preset: str = PRESET_CUSTOM,
    mode: str = MODE_ALL,
    data_from: datetime | None = None,
    now: datetime | None = None,
    gap_minutes: int = 5,
    max_span_minutes: int = 60,
    type_seen: dict[str, tuple[datetime, datetime]] | None = None,
) -> ReportData:
    """``rows`` cover ``report_windows(...).fetch_from(data_from)`` to ``end``."""
    if mode not in MODE_LABELS:
        raise ValueError(f"Unknown report mode: {mode!r}")
    now = now or datetime.now(timezone.utc)
    tz = schedule.tzinfo
    win = report_windows(preset, start, end, schedule)
    period = Window(start, end, covered_days(start, end, data_from, now))
    previous = Window(
        win.baseline_start, start, covered_days(win.baseline_start, start, data_from, now)
    )
    gap, span = timedelta(minutes=gap_minutes), timedelta(minutes=max_span_minutes)

    def camera(device_id: UUID) -> Camera:
        return cameras.get(device_id) or Camera(name="Unknown camera", area=UNASSIGNED_AREA)

    def label(row) -> str:
        return labeler.short_label(row.type, row.type_detail, row.model_id)

    kept = sorted(
        (r for r in rows if _value(r.status) != DISMISSED), key=lambda r: r.timestamp
    )
    stamps = [r.timestamp for r in kept]
    dismissed = [
        r for r in rows if _value(r.status) == DISMISSED and start <= r.timestamp < end
    ]

    def day_cuts(lo: datetime, hi: datetime) -> list[datetime]:
        """Report-day starts strictly inside (lo, hi), UTC."""
        cuts = []
        day = report_day_of(lo.astimezone(tz), win.day_offset) + timedelta(days=1)
        while True:
            local = datetime.combine(
                day, time(win.day_offset // 60, win.day_offset % 60), tzinfo=tz
            )
            cut = local.astimezone(timezone.utc)
            if cut >= hi:
                return cuts
            cuts.append(cut)
            day += timedelta(days=1)

    def incidents_in(lo, hi) -> list:
        # Cut at report-day boundaries: a day's figure is then the same in
        # the daily report, the weekly one and the project-to-date total,
        # and the per-day bars always add up to the headline.
        edges = [lo, *day_cuts(lo, hi), hi]
        grouped = []
        for a, b in zip(edges, edges[1:]):
            members = kept[bisect_left(stamps, a):bisect_left(stamps, b)]
            grouped += group_incidents(members, gap, span)
        if mode == MODE_VERIFIED:
            grouped = [
                i for i in grouped if any(_value(m.status) in VERIFIED_STATUSES for m in i.members)
            ]
        return grouped

    def totals(grouped: list) -> PeriodTotals:
        by_area, by_type, by_shift, by_area_type = Counter(), Counter(), Counter(), Counter()
        for inc in grouped:
            area, kind = camera(inc.device_id).area, label(inc.members[0])
            by_area[area] += 1
            by_type[kind] += 1
            by_area_type[(area, kind)] += 1
            if name := shift_of(inc.first_at.astimezone(tz), schedule):
                by_shift[name] += 1
        return PeriodTotals(
            incidents=len(grouped),
            detections=sum(i.count for i in grouped),
            by_area=by_area,
            by_type=by_type,
            by_shift=by_shift,
            by_area_type=by_area_type,
        )

    current_groups = incidents_in(start, end)
    prev_groups = incidents_in(win.baseline_start, start)

    incidents: list[ReportIncident] = []
    for inc in current_groups:
        first = inc.members[0]
        cam = camera(inc.device_id)
        local_start = inc.first_at.astimezone(tz)
        incidents.append(
            ReportIncident(
                key=inc.key,
                area=cam.area,
                camera=cam.name,
                family=inc.type,
                type_label=label(first),
                severity=inc.severity(labeler.severity),
                started_at=local_start,
                ended_at=inc.last_at.astimezone(tz),
                detections=inc.count,
                verified=any(_value(m.status) in VERIFIED_STATUSES for m in inc.members),
                shift=shift_of(local_start, schedule),
                frame_candidates=[
                    m.id for m in sorted(inc.members, key=lambda m: -(m.confidence or 0))
                ],
            )
        )
    incidents.sort(key=lambda i: (i.started_at, i.key))

    current = totals(current_groups)
    prev = totals(prev_groups)

    # Over-time chart: report days from trend_start, bucketed by day offset.
    trend_groups = current_groups if win.trend_start == start else incidents_in(win.trend_start, end)
    offset = win.day_offset
    # Days before the project started have no data, not zero incidents.
    trend_from = max(win.trend_start, data_from) if data_from else win.trend_start
    first_day = report_day_of(min(trend_from, start).astimezone(tz), offset)
    last_day = report_day_of((end - timedelta(microseconds=1)).astimezone(tz), offset)
    per_day = Counter(report_day_of(i.first_at.astimezone(tz), offset) for i in trend_groups)
    by_day = [
        (first_day + timedelta(days=n), per_day[first_day + timedelta(days=n)])
        for n in range((last_day - first_day).days + 1)
    ]

    heatmap = [[0] * 24 for _ in range(7)]
    for i in incidents:
        heatmap[i.started_at.weekday()][i.started_at.hour] += 1

    covered_start = max(start, data_from) if data_from else start
    shift_hours = _shift_hours(schedule, covered_start, min(end, now), tz)
    shifts = [
        ShiftStat(
            name=s.name,
            start=s.start,
            end=s.end,
            incidents=current.by_shift[s.name],
            hours=shift_hours[s.name],
        )
        for s in (schedule.shifts if schedule.mode == "shifts" else [])
    ]

    areas: list[AreaSummary] = []
    for name, n in current.by_area.most_common():
        mine = [i for i in incidents if i.area == name]
        areas.append(
            AreaSummary(
                name=name,
                incidents=n,
                baseline_incidents=prev.by_area.get(name, 0),
                by_type=Counter(i.type_label for i in mine),
                by_camera=Counter(i.camera for i in mine),
            )
        )

    ptd = None
    if win.project_to_date and data_from and data_from < end:
        ptd = ProjectToDate(
            since=data_from.astimezone(tz),
            days=covered_days(data_from, end, data_from, now),
            totals=totals(incidents_in(data_from, end)),
        )

    dismissed_by_type = Counter(
        label(i.members[0]) for i in group_incidents(dismissed, gap, span)
    )

    return ReportData(
        branding=branding,
        project_name=project_name,
        mode=mode,
        preset=preset,
        timezone=schedule.timezone,
        period=period,
        previous=previous,
        generated_at=now,
        gap_minutes=gap_minutes,
        max_span_minutes=max_span_minutes,
        day_offset=offset,
        incidents=incidents,
        current=current,
        prev=prev,
        areas=areas,
        dismissed_by_type=dismissed_by_type,
        by_day=by_day,
        heatmap=heatmap,
        shifts=shifts,
        rollout=rollout_notes(type_seen or {}, win.baseline_start, end, data_from, tz),
        project_to_date=ptd,
    )


def gallery_order(incidents: Iterable[ReportIncident]) -> list[ReportIncident]:
    """Most severe, then longest, then most detections."""
    return sorted(
        incidents,
        key=lambda i: (-SEVERITY_RANK.get(i.severity, 0), -i.duration_minutes, -i.detections, i.key),
    )


def rank_for_gallery(
    incidents: Iterable[ReportIncident],
    limit: int,
    usable: Callable[[ReportIncident], bool] = lambda i: True,
) -> list[ReportIncident]:
    """``gallery_order``, spread across cameras and areas.

    First one per camera and a fair share per area (at least two), so one
    busy camera cannot fill the page with near-identical frames; the caps
    then relax in turn until ``limit`` is reached, preferring ``usable``
    incidents (those with a saved frame) throughout.
    """
    ordered = gallery_order(incidents)
    area_cap = max(2, math.ceil(limit / max(len({i.area for i in ordered}), 1)))
    passes = ((True, 1, area_cap), (True, None, area_cap), (True, None, None), (False, None, None))
    picked: list[ReportIncident] = []
    keys: set[str] = set()
    per_area: Counter = Counter()
    per_camera: Counter = Counter()
    for need_usable, camera_cap, cap in passes:
        for inc in ordered:
            if len(picked) == limit:
                return picked
            if inc.key in keys or (need_usable and not usable(inc)):
                continue
            if camera_cap is not None and per_camera[inc.camera] >= camera_cap:
                continue
            if cap is not None and per_area[inc.area] >= cap:
                continue
            picked.append(inc)
            keys.add(inc.key)
            per_area[inc.area] += 1
            per_camera[inc.camera] += 1
    return picked


# ---------------------------------------------------------------------------
# Database part
# ---------------------------------------------------------------------------


def camera_from_device(device: Device) -> Camera:
    """Area is the manway; without one, the location, then the camera itself."""
    name = (device.display_name or "").strip() or device.name
    area = (device.manway or "").strip() or (device.location or "").strip() or UNASSIGNED_AREA
    return Camera(name=name, area=area)


async def _project_for(db: AsyncSession, start: datetime, end: datetime) -> tuple[str | None, datetime | None]:
    """Name of the project the period falls in, and when its data starts.

    Rows from earlier projects are archived out of ``violations``, so the
    active project's start is where the live data begins.
    """
    projects = (await db.execute(select(Project).order_by(Project.started_at))).scalars().all()
    active = next((p for p in projects if p.state == "active"), None)
    overlapping = [
        p for p in projects if p.started_at < end and (p.ended_at is None or p.ended_at > start)
    ]
    name = overlapping[-1].name if overlapping else (active.name if active else None)
    return name, (active.started_at if active else None)


async def _type_seen(db: AsyncSession, labeler: ViolationLabeler) -> dict[str, tuple[datetime, datetime]]:
    """First and last detection of each type label, over all live data."""
    rows = (
        await db.execute(
            select(
                Violation.type,
                Violation.type_detail,
                Violation.model_id,
                func.min(Violation.timestamp),
                func.max(Violation.timestamp),
            ).group_by(Violation.type, Violation.type_detail, Violation.model_id)
        )
    ).all()
    seen: dict[str, tuple[datetime, datetime]] = {}
    for type_, detail, model_id, first, last in rows:
        key = labeler.short_label(type_, detail, model_id)
        if key in seen:
            first, last = min(first, seen[key][0]), max(last, seen[key][1])
        seen[key] = (first, last)
    return seen


async def load_report(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    preset: str = PRESET_CUSTOM,
    mode: str = MODE_ALL,
    camera_ids: list[str] | None = None,
    violation_types: list[str] | None = None,
    now: datetime | None = None,
) -> ReportData:
    settings = get_settings()
    schedule = await ShiftService(db).get_schedule()
    project_name, data_from = await _project_for(db, start, end)
    labeler = ViolationLabeler.current()
    win = report_windows(preset, start, end, schedule)

    filters = [Violation.timestamp >= win.fetch_from(data_from), Violation.timestamp < end]
    if camera_ids:
        filters.append(Violation.device_id.in_(camera_ids))
    if violation_types:
        filters.append(Violation.type.in_(violation_types))

    # Only the columns grouping and labelling read: a month is tens of
    # thousands of rows, and bounding boxes are fetched for the gallery only.
    rows = (
        await db.execute(
            select(
                Violation.id,
                Violation.device_id,
                Violation.type,
                Violation.type_detail,
                Violation.model_id,
                Violation.timestamp,
                Violation.status,
                Violation.severity,
                Violation.confidence,
            ).where(and_(*filters))
        )
    ).all()

    device_ids = {r.device_id for r in rows}
    devices = (
        (await db.execute(select(Device).where(Device.id.in_(device_ids)))).scalars().all()
        if device_ids
        else []
    )

    return build_report(
        rows=rows,
        cameras={d.id: camera_from_device(d) for d in devices},
        labeler=labeler,
        schedule=schedule,
        branding=await get_branding(db),
        project_name=project_name,
        start=start,
        end=end,
        preset=preset,
        mode=mode,
        data_from=data_from,
        now=now,
        gap_minutes=settings.incident_gap_minutes,
        max_span_minutes=settings.incident_max_span_minutes,
        type_seen=await _type_seen(db, labeler),
    )


#: Gallery crops, 4:3; printed at about 240 pt wide, so ~190 dpi.
GALLERY_PX = (640, 480)
#: Members per incident tried for a saved frame, best confidence first.
FRAME_CANDIDATES = 5
#: Incidents considered for the gallery, in gallery order.
GALLERY_POOL = 300


def _gallery_image(frame_path: Path, boxes) -> bytes | None:
    from io import BytesIO

    from app.services.frame_thumbnails import annotated_crop

    try:
        crop = annotated_crop(frame_path, boxes, GALLERY_PX, line=3)
    except Exception as exc:  # noqa: BLE001 - one bad frame must not sink the report
        logger.warning("Gallery frame unreadable", path=str(frame_path), error=str(exc))
        return None
    out = BytesIO()
    crop.save(out, "JPEG", quality=82)
    return out.getvalue()


@dataclass(frozen=True)
class GalleryPick:
    incident: ReportIncident
    #: The member whose saved frame represents the incident, and the file.
    violation_id: UUID | None
    frame_path: Path | None


async def select_gallery(
    db: AsyncSession,
    report: ReportData,
    size: int,
    exclude: Iterable[str] = (),
) -> list[GalleryPick]:
    """The top ``size`` incidents and the frame for each, in gallery order.

    ``exclude`` holds incident keys an admin removed; the next candidates
    fill in. Incidents with a saved frame are preferred; frameless ones only
    top up when there are not enough. Shared by the preview and the build,
    so what the admin approved is what the PDF shows.
    """
    removed = set(exclude)
    if size <= 0 or not report.incidents:
        return []
    pool = [i for i in gallery_order(report.incidents) if i.key not in removed][:GALLERY_POOL]
    ids = {vid for inc in pool for vid in inc.frame_candidates[:FRAME_CANDIDATES]}
    frames = dict(
        (
            await db.execute(
                select(Evidence.violation_id, Evidence.file_path).where(
                    Evidence.violation_id.in_(ids),
                    Evidence.evidence_type == EvidenceType.FRAME,
                    Evidence.status == EvidenceStatus.READY,
                    Evidence.file_path.isnot(None),
                )
            )
        ).all()
    ) if ids else {}
    root = Path(get_settings().evidence_frame_dir).resolve()

    def best_frame(inc: ReportIncident) -> tuple[UUID, Path] | None:
        for vid in inc.frame_candidates[:FRAME_CANDIDATES]:
            if rel := frames.get(vid):
                path = (root / rel).resolve()
                if path.is_relative_to(root) and path.is_file():
                    return vid, path
        return None

    chosen = {inc.key: best_frame(inc) for inc in pool}
    picked = rank_for_gallery(pool, size, usable=lambda i: chosen[i.key] is not None)
    return [
        GalleryPick(i, *(chosen[i.key] or (None, None))) for i in gallery_order(picked)
    ]


async def load_gallery(
    db: AsyncSession, report: ReportData, size: int, exclude: Iterable[str] = ()
) -> list[GalleryItem]:
    """``select_gallery``, with each frame cropped for print (in a thread)."""
    from starlette.concurrency import run_in_threadpool

    picks = await select_gallery(db, report, size, exclude)
    framed = [p.violation_id for p in picks if p.violation_id]
    boxes = dict(
        (
            await db.execute(
                select(Violation.id, Violation.bounding_boxes).where(Violation.id.in_(framed))
            )
        ).all()
    ) if framed else {}

    items: list[GalleryItem] = []
    for pick in picks:
        image = (
            await run_in_threadpool(_gallery_image, pick.frame_path, boxes.get(pick.violation_id))
            if pick.frame_path
            else None
        )
        items.append(GalleryItem(incident=pick.incident, image=image))
    return items
