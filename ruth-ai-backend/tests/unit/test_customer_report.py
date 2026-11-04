"""Customer report: counting, periods, findings, recommendations, PDF, logo."""

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.models import ViolationStatus
from app.models.enums import ViolationType
from app.services.report.branding import LogoError, ReportBranding, prepare_logo
from app.services.report.data import (
    MODE_VERIFIED,
    rank_for_gallery,
    select_gallery,
    PRESET_CUSTOM,
    PRESET_DAILY,
    Camera,
    GalleryItem,
    build_report,
    preset_range,
    rollout_notes,
)
from app.services.report.insights import build_insights
from app.services.report.job import PeriodError, report_filename, report_period
from app.services.report.pdf import render_pdf
from app.services.report.recommendations import NOTHING_STOOD_OUT, build_recommendations
from app.services.shift_schedule import ShiftDefinition, ShiftSchedule
from app.services.violation_labels import ViolationLabeler

IST = ZoneInfo("Asia/Kolkata")
SCHEDULE = ShiftSchedule(
    mode="shifts",
    timezone="Asia/Kolkata",
    shifts=[
        ShiftDefinition(name="Day", start="07:00", end="19:00"),
        ShiftDefinition(name="Night", start="19:00", end="07:00"),
    ],
)
CAM_A, CAM_B, CAM_C = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
CAMERAS = {
    CAM_A: Camera(name="MW01_IN", area="MW01"),
    CAM_B: Camera(name="MW01_OUT", area="MW01"),
    CAM_C: Camera(name="MW02_OUT", area="MW02"),
}
LABELER = ViolationLabeler({})
DAY = date(2026, 10, 26)


def ist(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=IST).astimezone(timezone.utc)


def row(ts, cam=CAM_A, detail="missing_gloves", status=ViolationStatus.OPEN, conf=0.8):
    return SimpleNamespace(
        id=uuid.uuid4(),
        device_id=cam,
        type=ViolationType.PPE_VIOLATION,
        type_detail=detail,
        model_id="ppe",
        timestamp=ts,
        status=status,
        severity=None,
        confidence=conf,
    )


def run(rows, preset=PRESET_DAILY, day=DAY, start=None, end=None, **kw):
    if start is None:
        start, end = preset_range(preset, day, SCHEDULE)
    kw.setdefault("now", ist(day + timedelta(days=5), 12))
    return build_report(
        rows=rows,
        cameras=CAMERAS,
        labeler=LABELER,
        schedule=SCHEDULE,
        branding=ReportBranding(customer_name="ACME"),
        project_name="Turnaround",
        start=start,
        end=end,
        preset=preset,
        **kw,
    )


# --------------------------------------------------------------------------
# Counting
# --------------------------------------------------------------------------


def test_daily_period_follows_the_first_shift():
    start, end = preset_range(PRESET_DAILY, DAY, SCHEDULE)
    assert start == ist(DAY, 7) and end == ist(DAY + timedelta(days=1), 7)


def test_incident_is_cut_at_the_report_day_boundary():
    # One person, a detection every minute from 06:50 to 07:10: two shift days.
    rows = [row(ist(DAY, 6, 50) + timedelta(minutes=m)) for m in range(21)]
    r = run(rows)
    assert r.current.incidents == 1
    assert r.current.detections == 11  # 07:00..07:10
    assert r.prev.incidents == 1  # 06:50..06:59 belongs to the day before


def test_daily_bars_add_up_to_the_headline():
    rows = []
    for d in range(10):
        day = DAY - timedelta(days=d)
        rows += [row(ist(day, 6, 58) + timedelta(minutes=m)) for m in range(5)]
        rows += [row(ist(day, 12) + timedelta(minutes=20 * k), cam=CAM_C) for k in range(d % 3 + 1)]
    r = run(rows)
    assert r.by_day[-1] == (DAY, r.current.incidents)
    assert sum(n for _, n in r.by_day[-8:-1]) == r.prev.incidents


def test_dismissed_detections_are_not_counted_but_noted():
    rows = [
        row(ist(DAY, 9)),
        row(ist(DAY, 11), detail="missing_vest", status=ViolationStatus.DISMISSED),
    ]
    r = run(rows)
    assert r.current.incidents == 1
    assert r.dismissed_by_type == {"Missing safety vest": 1}


def test_verified_mode_keeps_incidents_with_a_reviewed_member():
    rows = [
        row(ist(DAY, 9)),
        row(ist(DAY, 9, 2), status=ViolationStatus.REVIEWED),
        row(ist(DAY, 14), cam=CAM_C),
    ]
    assert run(rows).current.incidents == 2
    assert run(rows, mode=MODE_VERIFIED).current.incidents == 1


def test_daily_compares_with_the_7_day_average():
    rows = [row(ist(DAY - timedelta(days=d), 10)) for d in range(1, 8)]  # 1 a day
    rows += [row(ist(DAY, 10)), row(ist(DAY, 15)), row(ist(DAY, 20))]
    r = run(rows)
    assert r.previous.days == pytest.approx(7)
    assert r.prev_incidents_per_day == pytest.approx(1)
    assert r.change(r.current.incidents, r.prev.incidents) == pytest.approx(2.0)


def test_comparison_is_per_covered_day_when_the_project_started_inside_it():
    rows = [row(ist(DAY - timedelta(days=d), 10)) for d in range(1, 3)]
    rows.append(row(ist(DAY, 10)))
    r = run(rows, data_from=ist(DAY - timedelta(days=2), 7))
    assert r.comparison_partial
    assert r.previous.covered_days == pytest.approx(2)
    assert r.change(1, 2) == pytest.approx(0)


def test_no_comparison_without_baseline_data():
    r = run([row(ist(DAY, 10))], data_from=ist(DAY, 7))
    assert not r.has_comparison
    assert r.change(1, 0) is None


def test_project_to_date_counts_since_the_project_started():
    rows = [row(ist(DAY - timedelta(days=d), 10)) for d in range(0, 4)]
    r = run(rows, data_from=ist(DAY - timedelta(days=3), 7))
    assert r.project_to_date.totals.incidents == 4


def test_custom_preset_buckets_by_calendar_day():
    start = datetime(2026, 10, 20, tzinfo=IST).astimezone(timezone.utc)
    end = datetime(2026, 10, 27, tzinfo=IST).astimezone(timezone.utc)
    r = run([row(ist(date(2026, 10, 21), 3))], preset=PRESET_CUSTOM, start=start, end=end)
    assert len(r.by_day) == 7
    assert dict(r.by_day)[date(2026, 10, 21)] == 1


# --------------------------------------------------------------------------
# Rollout notes
# --------------------------------------------------------------------------


def test_rollout_notes_began_stopped_and_grace():
    data_from = ist(date(2026, 10, 16), 13)
    seen = {
        "Missing gloves": (ist(date(2026, 10, 19), 10), ist(DAY, 9)),  # began inside
        "Missing safety vest": (data_from, ist(date(2026, 10, 19), 9)),  # stopped inside
        "Missing hard hat": (data_from + timedelta(hours=2), ist(DAY, 9)),  # from the start
    }
    notes = rollout_notes(seen, ist(date(2026, 10, 19), 7), ist(DAY + timedelta(days=1), 7), data_from, IST)
    assert {(n.type_label, n.kind) for n in notes} == {
        ("Missing gloves", "began"),
        ("Missing safety vest", "stopped"),
    }


# --------------------------------------------------------------------------
# Periods and file names
# --------------------------------------------------------------------------


def test_report_period_daily_weekly_custom():
    s, e, label = report_period("daily", SCHEDULE, day=DAY, today=DAY + timedelta(days=1))
    assert (s, e, label) == (ist(DAY, 7), ist(DAY + timedelta(days=1), 7), "26 Oct 2026")
    s, e, label = report_period("weekly", SCHEDULE, day=DAY, today=DAY)
    assert s == ist(DAY - timedelta(days=6), 7) and label == "20–26 Oct 2026"
    s, e, _ = report_period("custom", SCHEDULE, start=date(2026, 10, 1), end=date(2026, 10, 1), today=DAY)
    assert e - s == timedelta(days=1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"preset": "daily", "day": DAY + timedelta(days=1)},
        {"preset": "daily"},
        {"preset": "custom", "start": DAY, "end": DAY - timedelta(days=1)},
        {"preset": "custom", "start": date(2026, 1, 1), "end": DAY},
    ],
)
def test_report_period_rejects(kwargs):
    preset = kwargs.pop("preset")
    with pytest.raises(PeriodError):
        report_period(preset, SCHEDULE, today=DAY, **kwargs)


def test_report_filename():
    assert report_filename("ACME Ltd.", "daily", DAY, DAY) == "ACME-Ltd-daily-safety-report-2026-10-26.pdf"
    assert report_filename(None, "weekly", DAY - timedelta(days=6), DAY) == (
        "weekly-safety-report-2026-10-20_to_2026-10-26.pdf"
    )


# --------------------------------------------------------------------------
# Findings and recommendations
# --------------------------------------------------------------------------


def busy_rows():
    """MW01 dominated by gloves, mostly 08:00-10:00, mostly one camera."""
    rows = []
    for k in range(30):
        rows.append(row(ist(DAY, 8) + timedelta(minutes=7 * k), cam=CAM_A))
    for k in range(4):
        rows.append(row(ist(DAY, 16) + timedelta(minutes=30 * k), cam=CAM_B))
    for k in range(6):
        rows.append(row(ist(DAY, 22) + timedelta(minutes=30 * k), cam=CAM_C, detail="missing_hardhat"))
    return rows


def test_findings_name_the_top_area_and_type():
    texts = [i.text for i in build_insights(run(busy_rows()))]
    assert any(t.startswith("MW01 accounts for") for t in texts)


def test_recommendations_follow_the_templates():
    recs = [r.text for r in build_recommendations(run(busy_rows()))]
    assert any(t.startswith("At MW01, missing gloves accounts for") for t in recs)
    # Rounds at MW01 also qualify, but two recommendations per area is the cap.
    assert any(t.startswith("Most of MW01's incidents (") for t in recs)
    assert sum("MW01" in t for t in recs) == 2


def test_recommendations_fall_back_when_nothing_stands_out():
    rows = [row(ist(DAY, h), cam=c) for h, c in ((8, CAM_A), (13, CAM_C), (20, CAM_B))]
    assert [x.text for x in build_recommendations(run(rows))] == [NOTHING_STOOD_OUT]


def test_camera_rule_skips_single_camera_areas():
    recs = [r.text for r in build_recommendations(run(busy_rows()))]
    assert not any("MW02's incidents" in t for t in recs)


# --------------------------------------------------------------------------
# PDF and logo
# --------------------------------------------------------------------------


def _jpeg() -> bytes:
    from PIL import Image

    out = BytesIO()
    Image.new("RGB", (640, 480), (90, 120, 160)).save(out, "JPEG")
    return out.getvalue()


def test_render_pdf_every_section():
    r = run(busy_rows(), data_from=ist(DAY - timedelta(days=10), 7))
    r.gallery = [GalleryItem(r.incidents[0], _jpeg()), GalleryItem(r.incidents[-1], None)]
    pdf = render_pdf(r)
    assert pdf.startswith(b"%PDF")
    # Cover, summary, areas, trend, where/when, evidence, recommendations, appendix.
    assert len(re.findall(rb"/Type /Page\b(?!s)", pdf)) >= 8


def test_render_pdf_without_incidents():
    assert render_pdf(run([])).startswith(b"%PDF")


def test_prepare_logo_reencodes_and_bounds():
    from PIL import Image

    src = BytesIO()
    Image.new("RGBA", (2000, 500), (255, 0, 0, 128)).save(src, "PNG")
    png = prepare_logo(src.getvalue())
    with Image.open(BytesIO(png)) as out:
        assert out.format == "PNG" and out.size[0] <= 600 and out.mode == "RGBA"


@pytest.mark.parametrize("data", [b"not an image", b"\x00" * (1024 * 1024 + 1)])
def test_prepare_logo_rejects(data):
    with pytest.raises(LogoError):
        prepare_logo(data)


def test_prepare_logo_rejects_other_formats():
    from PIL import Image

    gif = BytesIO()
    Image.new("RGB", (10, 10)).save(gif, "GIF")
    with pytest.raises(LogoError):
        prepare_logo(gif.getvalue())


def test_gallery_spreads_across_cameras_then_fills():
    r = run(busy_rows())
    picked = rank_for_gallery(r.incidents, 3)
    assert len({i.camera for i in picked}) == 3
    # Asking for more than there are cameras relaxes the caps to fill.
    assert len(rank_for_gallery(r.incidents, 10)) == 10
    # Incidents without a frame only fill what framed ones cannot.
    framed = {r.incidents[0].key}
    picked = rank_for_gallery(r.incidents, 2, usable=lambda i: i.key in framed)
    assert picked[0].key in framed


def test_exempt_dismissal_is_excluded_but_never_labelled():
    from app.models.dismiss_reasons import REASON_LABELS, DismissReason
    from app.services.false_positive_export import is_false_alarm

    assert not is_false_alarm("exempt")
    assert REASON_LABELS[DismissReason.EXEMPT] == "Exempt / not required"
    rows = [row(ist(DAY, 9)), row(ist(DAY, 11), status=ViolationStatus.DISMISSED)]
    assert run(rows).current.incidents == 1


class _NoFrames:
    """A session whose queries find nothing: every candidate is frameless."""

    async def execute(self, _stmt):
        return SimpleNamespace(all=lambda: [])


async def test_removed_gallery_candidates_are_replaced_by_the_next():
    r = run(busy_rows())
    first = await select_gallery(_NoFrames(), r, 3)
    removed = first[0].incident.key
    again = await select_gallery(_NoFrames(), r, 3, exclude=[removed])
    assert len(again) == 3
    assert removed not in {p.incident.key for p in again}
    assert {p.incident.key for p in first[1:]} <= {p.incident.key for p in again}
