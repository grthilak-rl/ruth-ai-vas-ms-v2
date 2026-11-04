"""Charts for the customer report, drawn with ReportLab's vector shapes.

Hand-built rather than reportlab.graphics.charts: the stock charts' look
(heavy axes, boxed plots, default fonts) is hard to strip, and these four
forms are a few dozen shapes each. Conventions throughout: recessive
gridlines and no axis box, bars with rounded data ends and square at the
baseline, labels in text inks, selective value labels.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Sequence

from reportlab.graphics.shapes import Drawing, Line, Path, Rect, String
from reportlab.pdfbase.pdfmetrics import stringWidth

from app.services.report.theme import (
    ACCENT,
    EMPTY_CELL,
    FONT,
    FONT_BOLD,
    GRID,
    INK,
    INK_2,
    MUTED,
    REFERENCE,
    SEQUENTIAL,
)

LABEL_SIZE = 7.5
VALUE_SIZE = 7.5
BAR_RADIUS = 2.0


def nice_ticks(max_value: float, target: int = 4) -> list[float]:
    """0 and round steps covering max_value."""
    if max_value <= 0:
        return [0, 1]
    raw = max_value / target
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    count = math.ceil(max_value / step)
    return [i * step for i in range(count + 1)]


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if v >= 1 or v == 0 else f"{v:.1f}"


def _truncate(text: str, font: str, size: float, width: float) -> str:
    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


def _bar_up(x: float, y: float, w: float, h: float, color) -> Path | Rect:
    """Vertical bar, square at the baseline, rounded at the data end."""
    r = min(BAR_RADIUS, w / 2, h)
    if r <= 0.2:
        return Rect(x, y, w, h, fillColor=color, strokeColor=None)
    k = 0.5523 * r
    p = Path(fillColor=color, strokeColor=None)
    p.moveTo(x, y)
    p.lineTo(x, y + h - r)
    p.curveTo(x, y + h - r + k, x + r - k, y + h, x + r, y + h)
    p.lineTo(x + w - r, y + h)
    p.curveTo(x + w - r + k, y + h, x + w, y + h - r + k, x + w, y + h - r)
    p.lineTo(x + w, y)
    p.closePath()
    return p


def _bar_right(x: float, y: float, w: float, h: float, color) -> Path | Rect:
    """Horizontal bar, square at the baseline (left), rounded at the right."""
    r = min(BAR_RADIUS, h / 2, w)
    if r <= 0.2:
        return Rect(x, y, w, h, fillColor=color, strokeColor=None)
    k = 0.5523 * r
    p = Path(fillColor=color, strokeColor=None)
    p.moveTo(x, y)
    p.lineTo(x + w - r, y)
    p.curveTo(x + w - r + k, y, x + w, y + r - k, x + w, y + r)
    p.lineTo(x + w, y + h - r)
    p.curveTo(x + w, y + h - r + k, x + w - r + k, y + h, x + w - r, y + h)
    p.lineTo(x, y + h)
    p.closePath()
    return p


def daily_bars(
    days: Sequence[tuple[date, int]],
    width: float,
    height: float = 170,
    reference: float | None = None,
    reference_label: str | None = None,
    highlight: date | None = None,
) -> Drawing:
    """Incidents per day, with an optional dashed reference (previous avg).

    With ``highlight``, that day is the full blue and the rest recede to a
    light step of the same hue; its value is the one labelled.
    """
    d = Drawing(width, height)
    values = [n for _, n in days]
    top = max(values + [reference or 0, 1])
    ticks = nice_ticks(top)
    y_max = ticks[-1]

    axis_w = max(stringWidth(_fmt(t), FONT, LABEL_SIZE) for t in ticks) + 6
    left, right, bottom = axis_w, 4, 26
    top_pad = 26 if reference is not None else 14
    plot_w = width - left - right
    plot_h = height - bottom - top_pad

    def y_of(v: float) -> float:
        return bottom + plot_h * v / y_max

    for t in ticks:
        y = y_of(t)
        d.add(Line(left, y, width - right, y, strokeColor=GRID, strokeWidth=0.6 if t else 0.9))
        d.add(String(left - 5, y - 2.5, _fmt(t), fontName=FONT, fontSize=LABEL_SIZE,
                     fillColor=MUTED, textAnchor="end"))

    n = max(len(days), 1)
    slot = plot_w / n
    bar_w = min(slot * 0.68, 26)
    # Thin the date labels so they never collide.
    label_every = max(1, math.ceil(n / max(1, plot_w // 34)))
    if highlight is not None:
        marked = next((i for i, (day, _) in enumerate(days) if day == highlight), None)
    else:
        marked = max(range(n), key=lambda i: values[i]) if values else None
    # Count label positions back from the last day, so the newest is labelled.
    shown = {i for i in range(n) if (n - 1 - i) % label_every == 0}
    if highlight is not None and marked is not None:
        shown = {i for i in shown if abs(i - marked) >= label_every} | {marked}

    for i, (day, v) in enumerate(days):
        x = left + slot * i + (slot - bar_w) / 2
        color = ACCENT if highlight is None or i == marked else SEQUENTIAL[1]
        if v:
            d.add(_bar_up(x, bottom, bar_w, y_of(v) - bottom, color))
        cx = x + bar_w / 2
        if i in shown:
            font = FONT_BOLD if highlight is not None and i == marked else FONT
            d.add(String(cx, bottom - 10, day.strftime("%a"), fontName=font, fontSize=LABEL_SIZE,
                         fillColor=MUTED, textAnchor="middle"))
            d.add(String(cx, bottom - 19, day.strftime("%d %b").lstrip("0"), fontName=font,
                         fontSize=LABEL_SIZE, fillColor=INK_2, textAnchor="middle"))
        if i == marked and v:
            d.add(String(cx, y_of(v) + 3, _fmt(v), fontName=FONT_BOLD, fontSize=VALUE_SIZE,
                         fillColor=INK, textAnchor="middle"))

    if reference is not None:
        y = y_of(reference)
        d.add(Line(left, y, width - right, y, strokeColor=REFERENCE, strokeWidth=1,
                   strokeDashArray=[3, 2.5]))
        if reference_label:
            # Keyed above the plot rather than on the line, where bars hide it.
            label = f"{reference_label}: {_fmt(reference)}"
            ly = height - 8
            lx = width - right - stringWidth(label, FONT, LABEL_SIZE)
            d.add(Line(lx - 22, ly + 2.5, lx - 5, ly + 2.5, strokeColor=REFERENCE, strokeWidth=1,
                       strokeDashArray=[3, 2.5]))
            d.add(String(lx, ly, label, fontName=FONT, fontSize=LABEL_SIZE, fillColor=INK_2))
    return d


def hbars(
    items: Sequence[tuple[str, int]],
    width: float,
    total: int | None = None,
    row_height: float = 17,
    label_width: float | None = None,
    annotations: dict[str, str] | None = None,
) -> Drawing:
    """Sorted horizontal bars: label, bar, "value · share" (and a note)."""
    total = total if total is not None else sum(v for _, v in items)
    annotations = annotations or {}
    rows = max(len(items), 1)
    height = rows * row_height + 4
    d = Drawing(width, height)

    if label_width is None:
        label_width = min(
            max((stringWidth(k, FONT, 8) for k, _ in items), default=40) + 10,
            width * 0.36,
        )
    value_w = 74
    bar_x = label_width
    bar_max = width - label_width - value_w
    top = max((v for _, v in items), default=1) or 1
    bar_h = min(row_height * 0.58, 10)

    for i, (key, v) in enumerate(items):
        y_mid = height - 2 - row_height * (i + 0.5)
        d.add(String(0, y_mid - 2.8, _truncate(key, FONT, 8, label_width - 10), fontName=FONT,
                     fontSize=8, fillColor=INK))
        w = bar_max * v / top
        d.add(Rect(bar_x, y_mid - bar_h / 2, bar_max, bar_h, fillColor=EMPTY_CELL, strokeColor=None))
        if w > 0:
            d.add(_bar_right(bar_x, y_mid - bar_h / 2, w, bar_h, ACCENT))
        share = f" · {round(100 * v / total)}%" if total else ""
        d.add(String(bar_x + bar_max + 6, y_mid - 2.8, f"{v:,}", fontName=FONT_BOLD,
                     fontSize=8, fillColor=INK))
        vw = stringWidth(f"{v:,}", FONT_BOLD, 8)
        d.add(String(bar_x + bar_max + 6 + vw, y_mid - 2.8, share, fontName=FONT, fontSize=8,
                     fillColor=MUTED))
        if note := annotations.get(key):
            d.add(String(bar_x + bar_max + 6 + vw + stringWidth(share, FONT, 8) + 4, y_mid - 2.8,
                         note, fontName=FONT, fontSize=6.5, fillColor=MUTED))
    return d


def heatmap(matrix: Sequence[Sequence[int]], width: float, row_labels: Sequence[str]) -> Drawing:
    """Weekday × hour grid on the sequential ramp, with its key."""
    cols = len(matrix[0]) if matrix else 24
    rows = len(matrix)
    left, bottom, key_h = 28, 16, 26
    gap = 1.2
    cell_w = (width - left) / cols
    cell_h = min(cell_w * 0.9, 16)
    height = key_h + bottom + rows * cell_h
    d = Drawing(width, height)
    peak = max((v for row in matrix for v in row), default=0)

    def color(v: int):
        if v == 0 or peak == 0:
            return EMPTY_CELL
        idx = min(len(SEQUENTIAL) - 1, int(len(SEQUENTIAL) * v / (peak + 1e-9)))
        return SEQUENTIAL[idx]

    for r, row in enumerate(matrix):
        y = key_h + bottom + (rows - r - 1) * cell_h
        d.add(String(left - 6, y + cell_h / 2 - 2.6, row_labels[r], fontName=FONT,
                     fontSize=LABEL_SIZE, fillColor=INK_2, textAnchor="end"))
        for c, v in enumerate(row):
            d.add(Rect(left + c * cell_w + gap / 2, y + gap / 2, cell_w - gap, cell_h - gap,
                       rx=1.2, ry=1.2, fillColor=color(v), strokeColor=None))
    for c in range(0, cols, 3):
        d.add(String(left + c * cell_w + cell_w / 2, key_h + bottom - 10, f"{c:02d}",
                     fontName=FONT, fontSize=LABEL_SIZE, fillColor=MUTED, textAnchor="middle"))

    # Key: the ramp with its ends labelled.
    sw = 16
    more = f"More (busiest hour: {peak:,})"
    swatches = [EMPTY_CELL] + SEQUENTIAL
    kx = width - stringWidth(more, FONT, LABEL_SIZE) - 4 - len(swatches) * sw
    d.add(String(kx - 4, 6, "None", fontName=FONT, fontSize=LABEL_SIZE, fillColor=MUTED,
                 textAnchor="end"))
    for i, c in enumerate(swatches):
        d.add(Rect(kx + i * sw, 4, sw - 1.2, 8, rx=1, ry=1, fillColor=c, strokeColor=None))
    d.add(String(kx + len(swatches) * sw + 4, 6, more, fontName=FONT, fontSize=LABEL_SIZE,
                 fillColor=MUTED))
    return d


def hour_bars(hours: Sequence[tuple[int, int]], width: float, height: float = 170) -> Drawing:
    """Incidents per hour of a shift, in shift order (e.g. 07 .. 18)."""
    d = Drawing(width, height)
    values = [n for _, n in hours]
    ticks = nice_ticks(max(values + [1]))
    y_max = ticks[-1]
    axis_w = max(stringWidth(_fmt(t), FONT, LABEL_SIZE) for t in ticks) + 6
    left, right, bottom, top_pad = axis_w, 4, 18, 14
    plot_w, plot_h = width - left - right, height - bottom - top_pad

    def y_of(v: float) -> float:
        return bottom + plot_h * v / y_max

    for t in ticks:
        y = y_of(t)
        d.add(Line(left, y, width - right, y, strokeColor=GRID, strokeWidth=0.6 if t else 0.9))
        d.add(String(left - 5, y - 2.5, _fmt(t), fontName=FONT, fontSize=LABEL_SIZE,
                     fillColor=MUTED, textAnchor="end"))
    n = max(len(hours), 1)
    slot = plot_w / n
    bar_w = min(slot * 0.68, 26)
    peak = max(range(n), key=lambda i: values[i]) if values else None
    for i, (hour, v) in enumerate(hours):
        x = left + slot * i + (slot - bar_w) / 2
        if v:
            d.add(_bar_up(x, bottom, bar_w, y_of(v) - bottom, ACCENT))
        cx = x + bar_w / 2
        d.add(String(cx, bottom - 11, f"{hour:02d}", fontName=FONT, fontSize=LABEL_SIZE,
                     fillColor=MUTED, textAnchor="middle"))
        if i == peak and v:
            d.add(String(cx, y_of(v) + 3, _fmt(v), fontName=FONT_BOLD, fontSize=VALUE_SIZE,
                         fillColor=INK, textAnchor="middle"))
    return d
