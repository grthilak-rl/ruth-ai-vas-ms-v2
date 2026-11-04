"""Plain-language findings for the executive summary.

Rule-based, not generated: the same data always reads the same way, and
every sentence can be traced to a number in the report. Each rule offers at
most one candidate with a salience score; the summary keeps the top few.
Rules stay quiet below their threshold, so a flat week says less rather than
inventing drama.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.services.report.data import ReportData

WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

MAX_INSIGHTS = 4
#: Incidents this long or longer read as sustained, not a brief lapse.
LONG_INCIDENT_MINUTES = 30
PEAK_WINDOW_HOURS = 3
#: The top area gets its own finding from this share of incidents.
TOP_AREA_SHARE = 0.2
#: An area's per-day change from which it reads as rising.
RISING = 0.3


@dataclass(frozen=True)
class Insight:
    text: str
    score: float


def fmt_int(n: float) -> str:
    return f"{round(n):,}"


def fmt_pct(share: float) -> str:
    return f"{round(share * 100)}%"


def fmt_rate(n: float) -> str:
    return f"{n:,.1f}" if n < 10 else fmt_int(n)


def fmt_hhmm(hour: int) -> str:
    return f"{hour % 24:02d}:00"


def _trend(r: ReportData) -> Insight | None:
    change = r.change(r.current.incidents, r.prev.incidents)
    if change is None or abs(change) < 0.10:
        return None
    if r.single_period:
        text = (
            f"{fmt_int(r.current.incidents)} incidents this {r.unit}: {fmt_pct(abs(change))} "
            f"{'above' if change > 0 else 'below'} {r.baseline_label} of "
            f"{fmt_rate(r.prev_incidents_per_day)} a {r.unit}."
        )
    else:
        word = "rose" if change > 0 else "fell"
        text = (
            f"Incidents per day {word} {fmt_pct(abs(change))} compared with {r.baseline_label} "
            f"(from {fmt_rate(r.prev_incidents_per_day)} to {fmt_rate(r.incidents_per_day)} a day)."
        )
    if r.comparison_partial:
        text += (
            f" Only {r.previous.covered_days:.0f} of the {r.previous.expected:.0f} comparison "
            f"{r.unit}s have data."
        )
    return Insight(text, 0.5 + min(abs(change), 1.0))


def _area(r: ReportData) -> Insight | None:
    if not r.by_area or r.current.incidents == 0:
        return None
    area, n = r.by_area[0]
    share = n / r.current.incidents
    if share < TOP_AREA_SHARE or len(r.by_area) < 2:
        return None
    types = Counter(i.type_label for i in r.incidents if i.area == area)
    top_type, tn = types.most_common(1)[0]
    text = f"{area} accounts for {fmt_pct(share)} of all incidents"
    if tn / n >= 0.5:
        text += f", mostly {top_type.lower()} ({fmt_pct(tn / n)} of them)"
    # A rising top area is said here, not again by _rising_area.
    change = r.change(n, r.prev.by_area.get(area, 0))
    if change is not None and change >= RISING:
        text += f", and it is up {fmt_pct(change)} per day on {r.baseline_label}"
    return Insight(text + ".", share * 1.6)


def _type(r: ReportData) -> Insight | None:
    if not r.by_type or r.current.incidents == 0:
        return None
    label, n = r.by_type[0]
    share = n / r.current.incidents
    if share < 0.4:
        return None
    return Insight(
        f"{label} is the most common issue: {fmt_pct(share)} of incidents "
        f"({fmt_int(n)} of {fmt_int(r.current.incidents)}).",
        share,
    )


def _peak_window(r: ReportData) -> Insight | None:
    total = r.current.incidents
    if total < 20:
        return None
    by_hour = [sum(r.heatmap[d][h] for d in range(7)) for h in range(24)]
    best_start, best = max(
        ((h, sum(by_hour[(h + k) % 24] for k in range(PEAK_WINDOW_HOURS))) for h in range(24)),
        key=lambda x: (x[1], -x[0]),
    )
    share = best / total
    uniform = PEAK_WINDOW_HOURS / 24
    if share < 2 * uniform:
        return None
    return Insight(
        f"Incidents cluster between {fmt_hhmm(best_start)} and "
        f"{fmt_hhmm(best_start + PEAK_WINDOW_HOURS)}: {fmt_pct(share)} of them start in "
        f"these {PEAK_WINDOW_HOURS} hours.",
        (share - uniform) * 2.5,
    )


def _shifts(r: ReportData) -> Insight | None:
    active = [s for s in r.shifts if s.hours > 0]
    if len(active) < 2 or r.current.incidents < 20:
        return None
    hi = max(active, key=lambda s: s.per_hour)
    lo = min(active, key=lambda s: s.per_hour)
    if lo.per_hour == 0:
        return None
    ratio = hi.per_hour / lo.per_hour
    if ratio < 1.3:
        return None
    return Insight(
        f"{hi.name} ({hi.start}–{hi.end}) has {ratio:.1f}× the incident rate of "
        f"{lo.name} ({lo.start}–{lo.end}), per hour on shift.",
        min(ratio - 1, 1.2),
    )


def _weekday(r: ReportData) -> Insight | None:
    if r.period.covered_days < 14 or r.current.incidents < 50:
        return None
    per_day: Counter = Counter()
    day_count: Counter = Counter()
    for d, n in r.by_day:
        per_day[d.weekday()] += n
        day_count[d.weekday()] += 1
    avg = {wd: per_day[wd] / day_count[wd] for wd in day_count}
    overall = sum(per_day.values()) / sum(day_count.values())
    wd, top = max(avg.items(), key=lambda x: x[1])
    if not overall or top / overall < 1.3:
        return None
    return Insight(
        f"{WEEKDAY_NAMES[wd]}s are the busiest, with {top / overall:.1f}× the average "
        f"daily number of incidents.",
        min(top / overall - 1, 1.0),
    )


def _long_incidents(r: ReportData) -> Insight | None:
    if r.current.incidents < 10:
        return None
    long = [i for i in r.incidents if i.duration_minutes >= LONG_INCIDENT_MINUTES]
    share = len(long) / r.current.incidents
    if share < 0.1:
        return None
    return Insight(
        f"{fmt_int(len(long))} incidents ({fmt_pct(share)}) lasted {LONG_INCIDENT_MINUTES} minutes "
        f"or longer: sustained non-compliance rather than a brief lapse.",
        share * 1.5,
    )


def _rising_area(r: ReportData) -> Insight | None:
    if not r.has_comparison or r.current.incidents == 0:
        return None
    best = None
    for rank, (area, n) in enumerate(r.by_area):
        share = n / r.current.incidents
        if share < 0.1 or (rank == 0 and share >= TOP_AREA_SHARE):
            continue
        change = r.change(n, r.prev.by_area.get(area, 0))
        if change is not None and change >= RISING and (best is None or change > best[1]):
            best = (area, change)
    if best is None:
        return None
    area, change = best
    return Insight(
        f"{area} is rising: {fmt_pct(change)} more incidents per day than {r.baseline_label}.",
        min(change, 1.0) * 0.8,
    )


RULES = (_trend, _area, _type, _peak_window, _shifts, _weekday, _long_incidents, _rising_area)


def build_insights(report: ReportData, limit: int = MAX_INSIGHTS) -> list[Insight]:
    found = [i for i in (rule(report) for rule in RULES) if i is not None]
    return sorted(found, key=lambda i: -i.score)[:limit]
