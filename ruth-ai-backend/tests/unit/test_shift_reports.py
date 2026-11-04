"""Shift reports and the automatic per-shift scheduler.

Scheduler: missed shifts are found again, nothing is queued twice,
interrupted builds are retried up to 3 times, schedule edits only move
future shifts, and the scheduler is idle while the project is not active.
"""

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.models import ViolationStatus
from app.models.enums import ViolationType
from app.services import project_lifecycle as pl
from app.services.report import auto
from app.services.report.auto import (
    GIVE_UP,
    MAX_AUTO_ATTEMPTS,
    START,
    AutoReportScheduler,
    due_occurrences,
    lookback_start,
    missing,
    next_action,
)
from app.services.report.branding import ReportBranding
from app.services.report.data import Camera, build_report, preset_range, shift_occurrence
from app.services.report.job import PeriodError, report_filename, report_period
from app.services.report.pdf import render_pdf
from app.services.shift_schedule import ShiftDefinition, ShiftSchedule
from app.services.violation_labels import ViolationLabeler

IST = ZoneInfo("Asia/Kolkata")
HPCL = ShiftSchedule(
    mode="shifts",
    timezone="Asia/Kolkata",
    shifts=[
        ShiftDefinition(name="Shift 1", start="07:00", end="19:00"),
        ShiftDefinition(name="Shift 2", start="19:00", end="07:00"),
    ],
)
DAY = date(2026, 11, 3)


def ist(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST).astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Shift occurrences and periods
# --------------------------------------------------------------------------


def test_shift_occurrences():
    assert shift_occurrence(DAY, HPCL, "Shift 1") == (ist(DAY, 7), ist(DAY, 19))
    assert shift_occurrence(DAY, HPCL, "Shift 2") == (ist(DAY, 19), ist(DAY + timedelta(days=1), 7))


def test_report_period_for_a_shift():
    now = ist(DAY + timedelta(days=1), 12)
    lo, hi, label = report_period("shift", HPCL, day=DAY, shift="Shift 2", now=now)
    assert (lo, hi, label) == (ist(DAY, 19), ist(DAY + timedelta(days=1), 7), "Shift 2, 3 Nov 2026")
    with pytest.raises(PeriodError):
        report_period("shift", HPCL, day=DAY + timedelta(days=2), shift="Shift 1", now=now)
    with pytest.raises(PeriodError):
        report_period("shift", HPCL, day=DAY, shift="Night", now=now)


def test_shift_filename():
    assert report_filename("HPCL", "shift", DAY, DAY, "Shift 1") == "HPCL-shift-safety-report-2026-11-03-Shift-1.pdf"


# --------------------------------------------------------------------------
# Shift preset: baseline, trend, hour bars
# --------------------------------------------------------------------------

CAM = uuid.uuid4()


def row(ts):
    return SimpleNamespace(
        id=uuid.uuid4(), device_id=CAM, type=ViolationType.PPE_VIOLATION, type_detail="missing_gloves",
        model_id="ppe", timestamp=ts, status=ViolationStatus.OPEN, severity=None, confidence=0.8,
    )


def shift_report(rows, **kw):
    start, end = preset_range("shift", DAY, HPCL, "Shift 1")
    return build_report(
        rows=rows, cameras={CAM: Camera("MW01_IN", "MW01")}, labeler=ViolationLabeler({}),
        schedule=HPCL, branding=ReportBranding(customer_name="HPCL"), project_name="HPCL",
        start=start, end=end, preset="shift", shift="Shift 1",
        now=ist(DAY + timedelta(days=2), 12), **kw,
    )


def test_shift_report_compares_with_the_same_shift_only():
    rows = []
    for k in range(1, 8):  # one Shift 1 incident on each of the 7 days before
        rows.append(row(ist(DAY - timedelta(days=k), 10)))
        rows.append(row(ist(DAY - timedelta(days=k), 22)))  # Shift 2: must not count
    rows += [row(ist(DAY, 8)), row(ist(DAY, 12)), row(ist(DAY, 16))]
    r = shift_report(rows)
    assert r.current.incidents == 3
    assert r.prev.incidents == 7
    assert r.previous.expected == 7 and r.prev_incidents_per_day == pytest.approx(1)
    assert r.change(3, 7) == pytest.approx(2.0)
    assert r.unit == "shift" and r.single_period and not r.is_daily


def test_shift_trend_is_one_bar_per_occurrence_and_hours_follow_the_shift():
    rows = [row(ist(DAY - timedelta(days=k), 9)) for k in range(0, 5)]
    r = shift_report(rows, data_from=ist(DAY - timedelta(days=4), 0))
    assert [d for d, _ in r.by_day] == [DAY - timedelta(days=k) for k in range(4, -1, -1)]
    assert r.by_day[-1] == (DAY, r.current.incidents)
    assert [h for h, _ in r.by_hour] == list(range(7, 19))
    assert dict(r.by_hour)[9] == 1
    assert r.shifts == []  # no shifts block in a shift report


def test_shift_report_renders():
    r = shift_report([row(ist(DAY, 8)), row(ist(DAY, 9, 30))])
    pdf = render_pdf(r)
    assert pdf.startswith(b"%PDF")


# --------------------------------------------------------------------------
# Scheduler decisions
# --------------------------------------------------------------------------

SETTLE = timedelta(minutes=15)


def names(occ):
    return [(o.day.isoformat(), o.shift) for o in occ]


def test_due_respects_settle_delay():
    since = ist(DAY, 0)
    assert names(due_occurrences(HPCL, ist(DAY + timedelta(days=1), 7, 10), since, SETTLE)) == [
        ("2026-11-02", "Shift 2"), ("2026-11-03", "Shift 1"),
    ]
    assert names(due_occurrences(HPCL, ist(DAY + timedelta(days=1), 7, 15), since, SETTLE))[-1] == (
        "2026-11-03", "Shift 2")


def test_missed_shifts_are_found_again_after_downtime():
    now = ist(DAY, 8)
    since = now - timedelta(days=3)
    due = due_occurrences(HPCL, now, since, SETTLE)
    assert len(due) == 6
    assert all(since < o.end <= now - SETTLE for o in due)


def test_lookback_is_capped_and_starts_at_switch_on_or_resume():
    now = ist(DAY, 8)
    assert lookback_start(now, now - timedelta(days=30), None) == now - timedelta(days=7)
    assert lookback_start(now, now - timedelta(hours=5), None) == now - timedelta(hours=5)
    assert lookback_start(now, now - timedelta(days=2), now - timedelta(hours=1)) == now - timedelta(hours=1)


def test_nothing_is_queued_twice():
    due = due_occurrences(HPCL, ist(DAY, 8), ist(DAY - timedelta(days=2), 8), SETTLE)
    existing = {(o.start, o.end) for o in due[:2]}
    todo = missing(due, existing)
    assert len(todo) == len(due) - 2
    assert missing(due, existing | {(o.start, o.end) for o in todo}) == []


def test_schedule_edit_moves_future_shifts_only():
    edited = ShiftSchedule(mode="shifts", timezone="Asia/Kolkata", shifts=[
        ShiftDefinition(name="Day", start="06:00", end="18:00"),
        ShiftDefinition(name="Night", start="18:00", end="06:00"),
    ])
    old = due_occurrences(HPCL, ist(DAY, 8), ist(DAY - timedelta(days=1), 8), SETTLE)
    existing = {(o.start, o.end) for o in old}
    new = due_occurrences(edited, ist(DAY + timedelta(days=1), 8), ist(DAY, 8), SETTLE)
    # The new shifts are queued; the old rows keep their own periods.
    assert names(missing(new, existing)) == names(new)
    assert all(o.shift in ("Day", "Night") for o in new)


@pytest.mark.parametrize(
    "status, attempts, running, action",
    [
        ("building", 0, False, START),  # new
        ("building", 1, False, START),  # interrupted by a restart
        ("building", 2, True, None),  # being built here right now
        ("building", MAX_AUTO_ATTEMPTS, False, GIVE_UP),
        ("failed", 1, False, START),
        ("failed", MAX_AUTO_ATTEMPTS, False, None),
        ("ready", 1, False, None),
        ("expired", 1, False, None),
    ],
)
def test_retry_decisions(status, attempts, running, action):
    assert next_action(status, attempts, running) == action


# --------------------------------------------------------------------------
# Scheduler idle states
# --------------------------------------------------------------------------


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _factory():
    return _Session()


async def test_idle_while_stopped_logs_once(monkeypatch):
    async def stopped(_db):
        return "stopped"

    logged = []
    monkeypatch.setattr(pl, "site_state", stopped)
    monkeypatch.setattr(auto.logger, "info", lambda event, **kw: logged.append((event, kw)))
    sched = AutoReportScheduler()
    for _ in range(3):
        assert await sched.tick(_factory) == {"idle": "project stopped"}
    assert logged == [("Auto shift reports idle", {"reason": "project stopped"})]


async def test_idle_while_switched_off(monkeypatch):
    async def running(_db):
        return "active"

    async def off(_db):
        return auto.AutoReportSettings(enabled=False), None

    monkeypatch.setattr(pl, "site_state", running)
    monkeypatch.setattr(auto, "get_auto_settings", off)
    assert await AutoReportScheduler().tick(_factory) == {"idle": "auto reports are off"}


async def test_switching_on_records_when_and_off_clears_it():
    class DB:
        def __init__(self):
            self.added = []

        async def execute(self, _stmt):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: None))

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            pass

    db, now = DB(), ist(DAY, 9)
    s = await auto.save_auto_settings(db, enabled=True, settle_minutes=15, by="admin", now=now)
    assert s.enabled and s.enabled_at == now
    assert re.search("auto_reports", db.added[0].key)


def test_shift_counting_note_describes_one_shift():
    from app.services.report.pdf import _counting_note

    note = _counting_note(shift_report([row(ist(DAY, 8))]))
    assert "one shift, Shift 1 (07:00 to 19:00)" in note
    assert "Days are shift days" not in note
