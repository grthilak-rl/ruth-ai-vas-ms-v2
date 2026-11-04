"""The customer report as a PDF: cover, executive summary, charts, ...

Layout is A4 portrait. The cover is drawn straight onto the canvas; every
other page is flowables inside a frame, with a header naming the customer
and project, and a footer naming the period, the counting basis and
"page n of N" — so a page printed on its own still says what it counts.
"""

from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO
from typing import Callable

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Image,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.services.report import charts
from app.services.report.branding import VENDOR_LOGO
from app.services.report.data import (
    DAILY_BASELINE_DAYS,
    PRESET_DAILY,
    PRESET_SHIFT,
    PRESET_WEEKLY,
    WEEKDAYS,
    AreaSummary,
    ReportData,
    Window,
    report_day_of,
)
from app.services.report.insights import build_insights, fmt_int, fmt_pct, fmt_rate
from app.services.report.recommendations import build_recommendations
from app.services.report.theme import (
    ACCENT,
    CRITICAL,
    FONT,
    FONT_BOLD,
    GOOD,
    GRID,
    INK,
    INK_2,
    MUTED,
    PANEL,
    RULE,
    WHITE,
    register_fonts,
)

PAGE_W, PAGE_H = A4
MARGIN_X = 48
MARGIN_TOP = 70
MARGIN_BOTTOM = 56
CONTENT_W = PAGE_W - 2 * MARGIN_X

REPORT_TITLE = "Safety Compliance Report"
TITLES = {
    PRESET_DAILY: "Daily Safety Compliance Report",
    PRESET_SHIFT: "Shift Safety Compliance Report",
    PRESET_WEEKLY: "Weekly Safety Compliance Report",
}


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("body", fontName=FONT, fontSize=9, leading=13.5, textColor=INK)
    return {
        "body": base,
        "h1": ParagraphStyle("h1", base, fontName=FONT_BOLD, fontSize=19, leading=24, spaceAfter=4),
        "h2": ParagraphStyle("h2", base, fontName=FONT_BOLD, fontSize=11.5, leading=15,
                             spaceBefore=14, spaceAfter=2),
        "lead": ParagraphStyle("lead", base, fontSize=10.5, leading=16, textColor=INK_2),
        "caption": ParagraphStyle("caption", base, fontSize=7.8, leading=11, textColor=MUTED,
                                  spaceAfter=6),
        "small": ParagraphStyle("small", base, fontSize=7.8, leading=11.5, textColor=INK_2),
        "insight": ParagraphStyle("insight", base, fontSize=9.5, leading=14, alignment=TA_LEFT),
        "num": ParagraphStyle("num", base, fontName=FONT_BOLD, fontSize=9.5, leading=14,
                              textColor=ACCENT),
        "cell_label": ParagraphStyle("cell_label", base, fontSize=6.8, leading=9, textColor=INK_2),
        "cell_value": ParagraphStyle("cell_value", base, fontName=FONT_BOLD, fontSize=11, leading=14),
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def day_range_text(first: date, last: date, long: bool = True) -> str:
    """'20–26 October 2026' / '28 Sep – 4 Oct 2026' (both days included)."""
    month = "%B" if long else "%b"
    if first == last:
        return first.strftime(f"%-d {month} %Y")
    if (first.year, first.month) == (last.year, last.month):
        return f"{first.day}–{last.strftime(f'%-d {month} %Y')}"
    if first.year == last.year:
        return f"{first.strftime(f'%-d {month}')} – {last.strftime(f'%-d {month} %Y')}"
    return f"{first.strftime(f'%-d {month} %Y')} – {last.strftime(f'%-d {month} %Y')}"


def _days(r: ReportData, w: Window) -> tuple[date, date]:
    """First and last report day of a window (days start at the day offset)."""
    last = w.end - timedelta(microseconds=1)
    return (
        report_day_of(w.start.astimezone(r.tz), r.day_offset),
        report_day_of(last.astimezone(r.tz), r.day_offset),
    )


def period_days(r: ReportData) -> tuple[date, date]:
    """First and last report day the report covers."""
    return _days(r, r.period)


def _period(r: ReportData, long: bool = True) -> str:
    first, last = _days(r, r.period)
    if r.is_shift:
        name, start, end = r.shift
        when = first.strftime("%A %-d %B %Y" if long else "%-d %b %Y")
        return f"{name} ({start}–{end}), {when}" if long else f"{when}, {name}"
    if r.is_daily and long:
        return first.strftime("%A %-d %B %Y")
    return day_range_text(first, last, long)


def _prev_period(r: ReportData) -> str:
    return day_range_text(*_days(r, r.previous), long=False)


def _day_hours(r: ReportData) -> str:
    """'shift day 07:00 to 07:00' when days do not start at midnight."""
    if r.is_shift:
        return f"shift {r.shift[1]} to {r.shift[2]}"
    if not r.day_offset:
        return ""
    hhmm = f"{r.day_offset // 60:02d}:{r.day_offset % 60:02d}"
    return f"shift day {hhmm} to {hhmm}"


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _who(r: ReportData) -> str:
    """Customer · project, once when they are the same name."""
    parts = [x for x in (r.branding.customer_name, r.project_name) if x]
    return " · ".join(dict.fromkeys(parts))


def _title(r: ReportData) -> str:
    return TITLES.get(r.preset, REPORT_TITLE)


def _type_heading(r: ReportData) -> str:
    families = {i.family for i in r.incidents}
    return "PPE type" if families <= {"ppe_violation"} else "type"


def _vs(r: ReportData) -> str:
    """Short comparison label for tiles and cards."""
    if r.single_period:
        return f"vs {DAILY_BASELINE_DAYS}-day avg"
    return "per day vs previous" if r.comparison_partial else "vs previous"


def _rollout_text(r: ReportData) -> str | None:
    """The footnote for types that began or stopped inside the comparison."""
    if not r.rollout or not r.has_comparison:
        return None
    parts = [
        f"detection of {_esc(n.type_label.lower())} began on {n.at:%-d %b}"
        if n.kind == "began"
        else f"no {_esc(n.type_label.lower())} detections since {n.at:%-d %b}"
        for n in r.rollout
    ]
    text = "; ".join(parts)
    return (
        f"* {text[0].upper()}{text[1:]}. These fall inside the comparison window, so changes "
        f"for these types reflect when detection started or stopped, not a change on site."
    )


# ---------------------------------------------------------------------------
# Page furniture
# ---------------------------------------------------------------------------


def _numbered_canvas(r: ReportData) -> type:
    """A canvas that knows the page count, for "page n of N" footers."""

    class NumberedCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for number, state in enumerate(self._pages, start=1):
                self.__dict__.update(state)
                if number > 1:
                    _footer(self, r, number, total)
                super().showPage()
            super().save()

    return NumberedCanvas


def _header(c: pdfcanvas.Canvas, r: ReportData) -> None:
    c.saveState()
    y = PAGE_H - 40
    c.setFont(FONT_BOLD, 8)
    c.setFillColor(INK)
    c.drawString(MARGIN_X, y, _who(r) or _title(r))
    c.setFont(FONT, 8)
    c.setFillColor(MUTED)
    c.drawRightString(PAGE_W - MARGIN_X, y, _title(r))
    c.setStrokeColor(RULE)
    c.setLineWidth(0.6)
    c.line(MARGIN_X, y - 9, PAGE_W - MARGIN_X, y - 9)
    c.restoreState()


def _footer(c: pdfcanvas.Canvas, r: ReportData, number: int, total: int) -> None:
    c.saveState()
    y = 30
    c.setStrokeColor(RULE)
    c.setLineWidth(0.6)
    c.line(MARGIN_X, y + 12, PAGE_W - MARGIN_X, y + 12)
    c.setFont(FONT, 7)
    c.setFillColor(MUTED)
    c.drawString(MARGIN_X, y, f"{_period(r, long=False)}  ·  Counting: {r.mode_label}")
    c.drawRightString(PAGE_W - MARGIN_X, y, f"Page {number} of {total}")
    c.restoreState()


def _draw_image(c, path, x, y, max_w, max_h, anchor="sw") -> float:
    """Draw an image fitted in max_w × max_h; returns the drawn width."""
    img = ImageReader(str(path))
    iw, ih = img.getSize()
    scale = min(max_w / iw, max_h / ih)
    w, h = iw * scale, ih * scale
    if anchor == "nw":
        y -= h
    c.drawImage(img, x, y, w, h, mask="auto")
    return w


def _cover(c: pdfcanvas.Canvas, r: ReportData) -> None:
    c.saveState()
    # A band down the left edge: the only large area of colour in the report.
    c.setFillColor(ACCENT)
    c.rect(0, 0, 14, PAGE_H, stroke=0, fill=1)

    x = MARGIN_X + 10
    top = PAGE_H - 72
    logo = r.branding.logo_file()
    if logo:
        _draw_image(c, logo, x, top, 170, 64, anchor="nw")
    elif r.branding.customer_name:
        c.setFont(FONT_BOLD, 22)
        c.setFillColor(INK)
        c.drawString(x, top - 22, r.branding.customer_name)

    y = PAGE_H * 0.58
    title = _title(r)
    size = 32
    while c.stringWidth(title, FONT_BOLD, size) > PAGE_W - x - MARGIN_X:
        size -= 1
    c.setFillColor(ACCENT)
    c.rect(x, y + 64, 36, 3, stroke=0, fill=1)
    c.setFont(FONT_BOLD, size)
    c.setFillColor(INK)
    c.drawString(x, y + 22, title)
    c.setFont(FONT, 15)
    c.setFillColor(INK_2)
    c.drawString(x, y - 6, _period(r))

    when = ", ".join(x for x in (_day_hours(r), r.timezone) if x)
    rows = [
        ("Customer", r.branding.customer_name or "—"),
        ("Project", r.project_name or "—"),
        ("Period", f"{_period(r)} ({when})"),
        ("Counting", r.mode_label),
        ("Generated", r.generated_at.astimezone(r.tz).strftime("%-d %b %Y, %H:%M")),
    ]
    y -= 62
    for label, value in rows:
        c.setFont(FONT, 8)
        c.setFillColor(MUTED)
        c.drawString(x, y, label.upper())
        c.setFont(FONT, 10)
        c.setFillColor(INK)
        c.drawString(x + 78, y, value)
        y -= 21

    # Prepared by
    c.setStrokeColor(RULE)
    c.setLineWidth(0.6)
    c.line(x, 96, PAGE_W - MARGIN_X, 96)
    c.setFont(FONT, 7.5)
    c.setFillColor(MUTED)
    c.drawString(x, 74, "Prepared by")
    if VENDOR_LOGO.is_file():
        _draw_image(c, VENDOR_LOGO, x + 48, 58, 60, 34)
    c.drawRightString(
        PAGE_W - MARGIN_X, 74, "AI video analytics · Confidential: for the customer's internal use"
    )
    c.restoreState()


# ---------------------------------------------------------------------------
# Flowables
# ---------------------------------------------------------------------------


def _draw_delta(c, x, y, change: float | None, note: str, none_text: str = "No comparison"):
    """Arrow + signed change. More incidents is worse: up = critical, down =
    good, never colour alone."""
    c.setFont(FONT, 7.5)
    if change is None:
        c.setFillColor(MUTED)
        c.drawString(x, y, none_text)
        return
    flat = abs(change) < 0.05
    c.setFillColor(MUTED if flat else (CRITICAL if change > 0 else GOOD))
    p = c.beginPath()
    if flat:
        p.rect(x, y + 2, 7, 1.6)
    else:
        tip, base = (y + 6.5, y) if change > 0 else (y, y + 6.5)
        p.moveTo(x, base)
        p.lineTo(x + 7, base)
        p.lineTo(x + 3.5, tip)
        p.close()
    c.drawPath(p, stroke=0, fill=1)
    c.setFillColor(INK_2)
    word = "No change" if flat else f"{'+' if change > 0 else '–'}{fmt_pct(abs(change))}"
    c.drawString(x + 11, y, f"{word} {note}")


class KpiTiles(Flowable):
    """A row of KPI tiles: label, value, context line, change vs baseline."""

    GAP = 8
    HEIGHT = 92

    def __init__(self, tiles: list[dict], width: float):
        super().__init__()
        self.tiles = tiles
        self.width = width

    def wrap(self, *_):
        return self.width, self.HEIGHT

    def draw(self):
        c = self.canv
        n = len(self.tiles)
        w = (self.width - self.GAP * (n - 1)) / n
        for i, t in enumerate(self.tiles):
            x = i * (w + self.GAP)
            c.setFillColor(PANEL)
            c.roundRect(x, 0, w, self.HEIGHT, 5, stroke=0, fill=1)
            pad = 10
            c.setFont(FONT, 7.2)
            c.setFillColor(INK_2)
            c.drawString(x + pad, self.HEIGHT - 17, t["label"].upper())

            value = t["value"]
            size = 22 if len(value) <= 7 else 13
            while size > 9 and c.stringWidth(value, FONT_BOLD, size) > w - 2 * pad:
                size -= 0.5
            c.setFont(FONT_BOLD, size)
            c.setFillColor(INK)
            c.drawString(x + pad, self.HEIGHT - 45, value)

            c.setFont(FONT, 7.5)
            c.setFillColor(INK_2)
            c.drawString(x + pad, self.HEIGHT - 60, t.get("context", ""))
            _draw_delta(c, x + pad, 12, t.get("change"), t.get("change_note", ""),
                        t.get("none_text", "No comparison"))


class AreaCard(Flowable):
    """One area: incidents, change, incidents by type, top camera."""

    HEIGHT = 140
    TYPE_ROWS = 4

    def __init__(self, area: AreaSummary, r: ReportData, width: float):
        super().__init__()
        self.area = area
        self.r = r
        self.width = width

    def wrap(self, *_):
        return self.width, self.HEIGHT

    def draw(self):
        c, a, r = self.canv, self.area, self.r
        w, h, pad = self.width, self.HEIGHT, 11
        c.setFillColor(PANEL)
        c.roundRect(0, 0, w, h, 5, stroke=0, fill=1)

        count = fmt_int(a.incidents)
        c.setFont(FONT_BOLD, 16)
        c.setFillColor(INK)
        c.drawRightString(w - pad, h - 24, count)
        name_w = w - 2 * pad - c.stringWidth(count, FONT_BOLD, 16) - 8
        c.setFont(FONT_BOLD, 10)
        c.drawString(pad, h - 22, charts._truncate(a.name, FONT_BOLD, 10, name_w))

        share = a.incidents / r.current.incidents if r.current.incidents else 0
        c.setFont(FONT, 7.2)
        c.setFillColor(MUTED)
        c.drawRightString(w - pad, h - 36, f"incidents · {fmt_pct(share)} of all")
        _draw_delta(c, pad, h - 36, r.change(a.incidents, a.baseline_incidents), _vs(r),
                    "No previous data" if not r.has_comparison else "New in this period")

        c.setStrokeColor(GRID)
        c.setLineWidth(0.6)
        c.line(pad, h - 46, w - pad, h - 46)

        rows = a.by_type.most_common()
        if len(rows) > self.TYPE_ROWS:
            rest = rows[self.TYPE_ROWS - 1:]
            rows = rows[: self.TYPE_ROWS - 1] + [(f"{len(rest)} other types", sum(n for _, n in rest))]
        label_w, value_w = 82, 30
        bar_max = w - 2 * pad - label_w - value_w
        top = max((n for _, n in rows), default=1)
        y = h - 61
        for label, n in rows:
            c.setFont(FONT, 7.5)
            c.setFillColor(INK)
            c.drawString(pad, y, charts._truncate(label, FONT, 7.5, label_w - 6))
            c.setFillColor(WHITE)
            c.roundRect(pad + label_w, y - 0.5, bar_max, 6, 1.5, stroke=0, fill=1)
            c.setFillColor(ACCENT)
            bw = max(bar_max * n / top, 2)
            c.roundRect(pad + label_w, y - 0.5, bw, 6, 1.5, stroke=0, fill=1)
            c.setFont(FONT_BOLD, 7.5)
            c.setFillColor(INK)
            c.drawRightString(w - pad, y, fmt_int(n))
            y -= 14

        if a.by_camera:
            cam, n = a.by_camera.most_common(1)[0]
            c.setFont(FONT, 7)
            c.setFillColor(MUTED)
            c.drawString(pad, 11, "TOP CAMERA")
            tail = f" · {fmt_pct(n / a.incidents)}"
            c.setFont(FONT, 7.5)
            c.setFillColor(INK)
            room = w - 2 * pad - 52 - c.stringWidth(tail, FONT, 7.5)
            name = charts._truncate(cam, FONT, 7.5, room)
            c.drawString(pad + 52, 11, name)
            c.setFillColor(MUTED)
            c.drawString(pad + 52 + c.stringWidth(name, FONT, 7.5), 11, tail)


def _tiles(r: ReportData) -> list[dict]:
    total = r.current.incidents
    vs = _vs(r)
    rolled = r.rollout_types
    tiles = [
        {
            "label": "Incidents",
            "value": fmt_int(total),
            "context": (
                f"{DAILY_BASELINE_DAYS}-day average: {fmt_rate(r.prev_incidents_per_day)} a {r.unit}"
                if r.single_period and r.has_comparison
                else f"{fmt_rate(r.incidents_per_day)} a day on average"
            ),
            "change": r.change(total, r.prev.incidents),
            "change_note": vs,
        }
    ]
    if r.by_area:
        area, n = r.by_area[0]
        tiles.append({
            "label": "Top area",
            "value": area,
            "context": f"{fmt_int(n)} incidents · {fmt_pct(n / total)} of all",
            "change": r.change(n, r.prev.by_area.get(area, 0)),
            "change_note": vs,
        })
    if r.by_type:
        label, n = r.by_type[0]
        tiles.append({
            "label": "Top issue",
            "value": label,
            "context": f"{fmt_int(n)} incidents · {fmt_pct(n / total)} of all",
            "change": r.change(n, r.prev.by_type.get(label, 0)),
            "change_note": vs + (" *" if label in rolled else ""),
        })
    active = [s for s in r.shifts if s.hours > 0]
    if active and total:
        s = max(active, key=lambda s: s.per_hour)
        tiles.append({
            "label": "Highest-rate shift",
            "value": s.name,
            "context": f"{s.hours_label} · {fmt_rate(s.per_hour)} incidents/hour",
            "change": r.change(s.incidents, r.prev.by_shift.get(s.name, 0)),
            "change_note": vs,
        })
    for t in tiles:
        if not total:
            t["change"] = None
        if not r.has_comparison:
            t["none_text"] = "No previous data"
    return tiles


def _counting_note(r: ReportData) -> str:
    text = (
        f"An <b>incident</b> is one or more detections from the same camera and of the same "
        f"type, each within {r.gap_minutes} minutes of the previous, lasting at most "
        f"{r.max_span_minutes} minutes. Incidents are the unit of this report; raw detections "
        f"are shown for reference only. Detections an operator dismissed (false alarms, "
        f"duplicates, or people and places the PPE rule does not apply to) are not counted."
    )
    if r.is_shift:
        name, start, end = r.shift
        text += (
            f" The period is one shift, {name} ({start} to {end}); it is compared with the same "
            f"shift on the {DAILY_BASELINE_DAYS} days before."
        )
    elif r.day_offset:
        text += f" Days are shift days: each runs from the first shift's start ({_day_hours(r)})."
    return text


def _project_to_date(r: ReportData, st: dict) -> list:
    ptd = r.project_to_date
    if ptd is None:
        return []
    t = ptd.totals
    top_area = t.by_area.most_common(1)
    top_type = t.by_type.most_common(1)
    cells = [
        ("INCIDENTS", fmt_int(t.incidents)),
        ("A DAY ON AVERAGE", fmt_rate(t.incidents / ptd.days) if ptd.days else "—"),
        ("RAW DETECTIONS", fmt_int(t.detections)),
        ("TOP AREA", top_area[0][0] if top_area else "—"),
        ("TOP ISSUE", top_type[0][0] if top_type else "—"),
    ]
    widths = [70, 80, 82, 140, CONTENT_W - 372 - 24]
    row = [
        [Paragraph(label, st["cell_label"]), Paragraph(_esc(value), st["cell_value"])]
        for label, value in cells
    ]
    table = Table([row], colWidths=widths)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    project = f"{_esc(r.project_name)}, " if r.project_name else ""
    heading = Paragraph(
        f"<b>Project to date</b> · {project}since {ptd.since:%-d %b %Y} "
        f"({ptd.days:.0f} day{'s' * (round(ptd.days) != 1)})",
        st["small"],
    )
    box = Table([[heading], [table]], colWidths=[CONTENT_W])
    box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
        ("ROUNDEDCORNERS", [5, 5, 5, 5]),
    ]))
    return [Spacer(1, 12), box]


def summary_section(r: ReportData, st: dict) -> list:
    areas = len(r.current.by_area)
    cameras = len({i.camera for i in r.incidents})
    out: list = [Paragraph("Executive summary", st["h1"])]
    where = (
        f"across {areas} area{'s' * (areas != 1)} and {cameras} camera{'s' * (cameras != 1)}"
    )
    if not r.current.incidents:
        lead = f"No safety incidents were recorded {'in' if r.is_shift else 'on' if r.is_daily else 'from'} {_period(r)}."
    elif r.is_shift:
        lead = (
            f"In {_period(r)}, AI recorded <b>{fmt_int(r.current.incidents)} safety incidents</b> "
            f"{where}."
        )
    elif r.is_daily:
        lead = (
            f"On {_period(r)} ({_day_hours(r) or 'midnight to midnight'}), AI recorded "
            f"<b>{fmt_int(r.current.incidents)} safety incidents</b> {where}."
        )
    else:
        lead = (
            f"From {_period(r)}, AI recorded <b>{fmt_int(r.current.incidents)} safety "
            f"incidents</b> {where}: on average {fmt_rate(r.incidents_per_day)} a day."
        )
    out += [Paragraph(lead, st["lead"]), Spacer(1, 14), KpiTiles(_tiles(r), CONTENT_W), Spacer(1, 8)]

    baseline = f"{DAILY_BASELINE_DAYS}-day average" if r.single_period else "previous period"
    secondary = f"Raw detections: <b>{fmt_int(r.current.detections)}</b>"
    if r.has_comparison:
        prev = (
            fmt_rate(r.per_day(r.prev.detections, r.previous)) + f" a {r.unit}"
            if r.single_period
            else fmt_int(r.prev.detections)
        )
        secondary += f" ({baseline}: {prev})"
    dismissed = sum(r.dismissed_by_type.values())
    if dismissed:
        secondary += (
            f". Dismissed by operators, not counted: {fmt_int(dismissed)} "
            f"incident{'s' * (dismissed != 1)}"
        )
    notes = [secondary + "."]

    if r.period_incomplete:
        notes.append(
            f"The period is not complete: data up to "
            f"{min(r.period.end, r.generated_at).astimezone(r.tz):%-d %b, %H:%M}."
        )
    if not r.has_comparison:
        notes.append(f"No comparison: there is no data for the {baseline} ({_prev_period(r)}).")
    elif r.comparison_partial:
        notes.append(
            f"Changes compare incidents per {r.unit}: the {baseline} ({_prev_period(r)}) has data for "
            f"{r.previous.covered_days:.0f} of {r.previous.expected:.0f} {r.unit}s, because monitoring "
            f"for this project started during it."
        )
    if rollout := _rollout_text(r):
        notes.append(rollout)
    out += [Paragraph(n, st["small"]) for n in notes]

    out += _project_to_date(r, st)

    insights = build_insights(r)
    if insights:
        out += [Paragraph("Key findings", st["h2"]), _numbered([i.text for i in insights], st)]

    out += [Spacer(1, 16), _note_box(_counting_note(r), st)]
    return out


def _note_box(html: str, st: dict) -> Table:
    box = Table([[Paragraph(html, st["small"])]], colWidths=[CONTENT_W])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LINEBEFORE", (0, 0), (0, -1), 2, ACCENT),
    ]))
    return box


def areas_section(r: ReportData, st: dict) -> list:
    out: list = [
        Paragraph("Areas at a glance", st["h1"]),
        Paragraph(
            f"Each manway or work area, largest first: its incidents and change against "
            f"{r.baseline_label}, what they were, and the camera that saw most of them.",
            st["lead"],
        ),
        Spacer(1, 12),
    ]
    if not r.areas:
        return out + [Paragraph("No incidents in this period.", st["body"])]
    gap = 10
    card_w = (CONTENT_W - gap) / 2
    cards = [AreaCard(a, r, card_w) for a in r.areas]
    if len(cards) % 2:
        cards.append(Spacer(card_w, 1))
    rows = [cards[i:i + 2] for i in range(0, len(cards), 2)]
    grid = Table(rows, colWidths=[card_w + gap, card_w])
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), gap),
    ]))
    out.append(grid)
    if r.rollout and r.has_comparison:
        out.append(Paragraph(
            "Area changes include the detection start/stop dates noted on the summary page.",
            st["caption"],
        ))
    return out


def trend_section(r: ReportData, st: dict) -> list:
    out: list = [Paragraph("Over time and by type", st["h1"]), Spacer(1, 4)]

    ref = r.prev_incidents_per_day
    if r.is_shift:
        name, s_start, s_end = r.shift
        first = r.by_day[0][0] if r.by_day else r.report_day
        since = f" (since monitoring started on {first:%-d %b})" if len(r.by_day) < 30 else ""
        heading = f"Incidents in {name}, last {len(r.by_day)} shifts{since}"
        caption = (
            f"One bar per {name} ({s_start}–{s_end}, {r.timezone}); the report's shift is "
            f"highlighted."
            + (f" Dashed line: this shift's {DAILY_BASELINE_DAYS}-day average before it."
               if ref is not None else "")
        )
        ref_label = f"{DAILY_BASELINE_DAYS}-day average"
    elif r.is_daily:
        first = r.by_day[0][0] if r.by_day else r.report_day
        since = (
            f" (since monitoring started on {first:%-d %b})"
            if len(r.by_day) < 30
            else ""
        )
        heading = f"Incidents per day, last {len(r.by_day)} days{since}"
        caption = (
            f"The report day is highlighted. Days are shift days ({_day_hours(r) or 'midnight to midnight'}, "
            f"{r.timezone})."
            + (f" Dashed line: the {DAILY_BASELINE_DAYS}-day average before the report day."
               if ref is not None else "")
        )
        ref_label = f"{DAILY_BASELINE_DAYS}-day average"
    else:
        heading = "Incidents per day"
        caption = (
            f"Incidents by the day they started, local time ({r.timezone})."
            + (" Dashed line: the previous period's daily average." if ref is not None else "")
        )
        ref_label = "Previous period average"
    out += [
        Paragraph(heading, st["h2"]),
        Paragraph(caption, st["caption"]),
        charts.daily_bars(
            r.by_day, CONTENT_W, 190, reference=ref,
            reference_label=ref_label if ref is not None else None,
            highlight=r.report_day if r.single_period else None,
        ),
    ]

    dismissed = r.dismissed_by_type
    notes = {k: f"+{v} dismissed" for k, v in dismissed.items()}
    by_type = r.by_type
    out += [
        Paragraph(f"Incidents by {_type_heading(r)}", st["h2"]),
        Paragraph(
            "Share of all incidents in the period."
            + (" “Dismissed” shows incidents operators set aside (false alarms, duplicates "
               "or exemptions); they are not counted." if dismissed else ""),
            st["caption"],
        ),
        charts.hbars(by_type, CONTENT_W, total=r.current.incidents, annotations=notes)
        if by_type
        else Paragraph("No incidents in this period.", st["body"]),
    ]
    only_dismissed = [(k, v) for k, v in dismissed.items() if k not in r.current.by_type]
    if only_dismissed:
        out.append(Spacer(1, 4))
        out.append(Paragraph(
            "Dismissed only: "
            + " · ".join(f"{_esc(k)} {v}" for k, v in only_dismissed),
            st["caption"],
        ))
    if rollout := _rollout_text(r):
        out += [Spacer(1, 6), Paragraph(rollout, st["caption"])]
    return out


#: Areas charted by name; the rest are summed as "Other areas".
AREA_CHART_ROWS = 10
#: Appendix rows; beyond this the XLSX lists them all.
APPENDIX_MAX_ROWS = 1500


def _numbered(items: list[str], st: dict) -> Table:
    rows = [
        [Paragraph(str(n), st["num"]), Paragraph(_esc(text), st["insight"])]
        for n, text in enumerate(items, start=1)
    ]
    table = Table(rows, colWidths=[22, CONTENT_W - 22])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, GRID),
    ]))
    return table


def _grid_style(extra: list | None = None) -> TableStyle:
    return TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK_2),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, RULE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        *(extra or []),
    ])


def where_when_section(r: ReportData, st: dict) -> list:
    out: list = [Paragraph("Where and when", st["h1"]), Spacer(1, 4)]
    areas = r.by_area
    if len(areas) > AREA_CHART_ROWS:
        rest = areas[AREA_CHART_ROWS - 1:]
        areas = areas[: AREA_CHART_ROWS - 1] + [
            (f"Other areas ({len(rest)})", sum(n for _, n in rest))
        ]
    out += [
        Paragraph("Incidents by area", st["h2"]),
        Paragraph("Areas are manways or work areas, from the camera's configured area.",
                  st["caption"]),
        charts.hbars(areas, CONTENT_W, total=r.current.incidents)
        if areas
        else Paragraph("No incidents in this period.", st["body"]),
    ]
    if r.is_shift:
        out += [
            Paragraph("When incidents start, hour by hour", st["h2"]),
            Paragraph(
                f"Incidents by the hour of the shift they started in, local time ({r.timezone}).",
                st["caption"],
            ),
            charts.hour_bars(r.by_hour, CONTENT_W, 170),
        ]
    else:
        out += [
            Paragraph("When incidents start", st["h2"]),
            Paragraph(
                f"Incidents by the weekday and hour they started, local time ({r.timezone}). "
                f"Darker cells had more incidents.",
                st["caption"],
            ),
            charts.heatmap(r.heatmap, CONTENT_W, WEEKDAYS),
        ]
    out += _shifts_block(r, st)
    return out


def _shifts_block(r: ReportData, st: dict) -> list:
    active = [s for s in r.shifts if s.hours > 0]
    if not active:
        return []
    labels = {s.name: f"{s.name} ({s.hours_label})" for s in active}
    vs = _vs(r)
    rows = [["Shift", "Hours", "Hours monitored", "Incidents", "Per hour", f"Change {vs}"]]
    for s in active:
        change = r.change(s.incidents, r.prev.by_shift.get(s.name, 0))
        rows.append([
            s.name,
            s.hours_label,
            f"{s.hours:,.0f}",
            fmt_int(s.incidents),
            fmt_rate(s.per_hour),
            "—" if change is None else f"{'+' if change >= 0 else '–'}{fmt_pct(abs(change))}",
        ])
    table = Table(rows, colWidths=[110, 70, 80, 65, 60, CONTENT_W - 385], repeatRows=1)
    table.setStyle(_grid_style([("ALIGN", (2, 0), (-1, -1), "RIGHT")]))
    return [
        CondPageBreak(220),
        Paragraph("Shifts", st["h2"]),
        Paragraph(
            "Shift names and hours come from the site's shift schedule. Per hour compares "
            "shifts of different lengths fairly: incidents divided by the hours the shift ran "
            "in the period.",
            st["caption"],
        ),
        charts.hbars(
            [(labels[s.name], s.incidents) for s in active],
            CONTENT_W,
            total=r.current.incidents,
            annotations={labels[s.name]: f"{fmt_rate(s.per_hour)} per hour" for s in active},
        ),
        Spacer(1, 8),
        table,
    ]


def gallery_section(r: ReportData, st: dict) -> list:
    if not r.gallery:
        return []
    out: list = [
        Paragraph("Evidence", st["h1"]),
        Paragraph(
            f"The {len(r.gallery)} most significant incidents of the period: most severe "
            f"first, then the longest, spread across areas and cameras. Each image is the "
            f"frame the AI analysed, cropped around the detection (red box).",
            st["lead"],
        ),
        Spacer(1, 10),
    ]
    gap = 12
    card_w = (CONTENT_W - gap) / 2
    img_h = card_w * 3 / 4
    cells = []
    for item in r.gallery:
        inc = item.incident
        if item.image:
            picture = Image(BytesIO(item.image), width=card_w, height=img_h)
        else:
            picture = Table([[Paragraph("No saved frame for this incident", st["caption"])]],
                            colWidths=[card_w], rowHeights=[img_h])
            picture.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
        minutes = max(1, round(inc.duration_minutes))
        cells.append([
            picture,
            Spacer(1, 4),
            Paragraph(f"<b>{_esc(inc.type_label)}</b> · {_esc(inc.area)}", st["body"]),
            Paragraph(
                f"{inc.started_at:%a %-d %b, %H:%M} · {minutes} min · "
                f"{fmt_int(inc.detections)} detection{'s' * (inc.detections != 1)}"
                f"<br/>{_esc(inc.camera)}",
                st["small"],
            ),
        ])
    if len(cells) % 2:
        cells.append("")
    rows = [cells[i:i + 2] for i in range(0, len(cells), 2)]
    grid = Table(rows, colWidths=[card_w + gap, card_w])
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
    ]))
    out.append(grid)
    return out


def recommendations_section(r: ReportData, st: dict) -> list:
    recs = build_recommendations(r)
    if not recs:
        return []
    return [
        Paragraph("Recommendations", st["h1"]),
        Paragraph(
            "Where to look first, from the hotspots in this report. Each recommendation names "
            "the numbers it rests on.",
            st["lead"],
        ),
        Spacer(1, 6),
        _numbered([rec.text for rec in recs], st),
        Spacer(1, 16),
        _note_box(
            "These recommendations come from fixed rules applied to the figures in this "
            "report. They point to where and when incidents concentrate, not to their cause; "
            "site knowledge decides the right response.",
            st,
        ),
    ]


def appendix_section(r: ReportData, st: dict) -> list:
    total = len(r.incidents)
    shown = r.incidents[:APPENDIX_MAX_ROWS]
    if total > len(shown):
        lead = (
            f"The first {fmt_int(len(shown))} of {fmt_int(total)} incidents, oldest first. "
            f"The XLSX report lists them all."
        )
    else:
        lead = f"All {fmt_int(total)} incidents in the period, oldest first."
    out: list = [Paragraph("Appendix: incident list", st["h1"]), Paragraph(lead, st["lead"]),
                 Spacer(1, 8)]
    if not shown:
        return out + [Paragraph("No incidents in this period.", st["body"])]
    widths = [64, 38, 92, 128, 86, 44, CONTENT_W - 452]
    rows = [["Start", "Minutes", "Area", "Camera", "Type", "Detections", "Reviewed"]]
    for i in shown:
        rows.append([
            f"{i.started_at:%-d %b %H:%M}",
            str(max(1, round(i.duration_minutes))),
            charts._truncate(i.area, FONT, 7.5, widths[2] - 8),
            charts._truncate(i.camera, FONT, 7.5, widths[3] - 8),
            charts._truncate(i.type_label, FONT, 7.5, widths[4] - 8),
            fmt_int(i.detections),
            "Yes" if i.verified else "",
        ])
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(_grid_style([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("ALIGN", (5, 0), (5, -1), "RIGHT")]))
    out.append(table)
    return out


#: Section name -> builder. Order is the report's order. A builder that
#: returns nothing (no shifts, gallery off) adds no page.
SECTIONS: dict[str, Callable[[ReportData, dict], list]] = {
    "summary": summary_section,
    "areas": areas_section,
    "trend": trend_section,
    "where": where_when_section,
    "gallery": gallery_section,
    "recommendations": recommendations_section,
    "appendix": appendix_section,
}


def render_pdf(r: ReportData, sections: list[str] | None = None) -> bytes:
    """The report; ``sections`` limits it to some content pages (the cover always)."""
    register_fonts()
    st = _styles()
    out = BytesIO()
    doc = BaseDocTemplate(
        out,
        pagesize=A4,
        title=f"{_title(r)} · {_period(r, long=False)}",
        author="AI",
        subject=_who(r),
    )
    content_frame = Frame(MARGIN_X, MARGIN_BOTTOM, CONTENT_W, PAGE_H - MARGIN_TOP - MARGIN_BOTTOM,
                          leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate("cover", [Frame(0, 0, PAGE_W, PAGE_H)], onPage=lambda c, d: _cover(c, r)),
        PageTemplate("content", [content_frame], onPage=lambda c, d: _header(c, r)),
    ])

    story: list = [NextPageTemplate("content"), PageBreak()]
    first = True
    for name in sections or list(SECTIONS):
        flowables = SECTIONS[name](r, st)
        if not flowables:
            continue
        if not first:
            story.append(PageBreak())
        story += flowables
        first = False
    doc.build(story, canvasmaker=_numbered_canvas(r))
    return out.getvalue()
