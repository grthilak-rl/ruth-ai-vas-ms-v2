"""Recommendations from hotspots, on the approved sentence templates.

Like the findings, these are rules, not generated text: each names the
numbers it rests on. At most four, ranked by how many incidents they
concern, no more than two about one area. Types whose detection began or
stopped inside the comparison window are left out of the change-based
rule, so a model rollout never reads as a deteriorating site. Nothing here
refers to review backlogs: operators only dismiss obvious false alarms.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.services.report.data import PRESET_DAILY, ReportData
from app.services.report.insights import fmt_hhmm, fmt_int, fmt_pct

MAX_RECOMMENDATIONS = 4
PER_AREA = 2
#: Below this many incidents a hotspot is noise, not a pattern.
MIN_INCIDENTS = 5
LONG_MINUTES = 30
WINDOW_HOURS = 3

#: (match in the type label, item noun, action).
ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("glove", "gloves", "keep gloves stocked at the work front and check the type issued suits the task"),
    ("hard hat", "hard hats", "check hard hats at the manway entry"),
    ("hardhat", "hard hats", "check hard hats at the manway entry"),
    ("helmet", "hard hats", "check hard hats at the manway entry"),
    ("goggle", "goggles", "keep goggles or face shields at the entry point"),
    ("harness", "harnesses", "check harnesses and anchor points are in place before work at height starts"),
    ("vest", "vests", "issue high-visibility vests at the entry point"),
    ("mask", "masks", "check masks or respirators are available and fitted"),
)
DEFAULT_ACTION = ("the required PPE", "brief the crew on the PPE required in this area")

NOTHING_STOOD_OUT = (
    "No single hotspot stood out in this period. Keep the current PPE checks in place."
)


@dataclass(frozen=True)
class Recommendation:
    text: str
    #: Incidents the recommendation concerns; the ranking key.
    weight: int
    area: str | None = None


def action_for(type_label: str) -> tuple[str, str]:
    """(item noun, action) for a type label, e.g. 'Missing gloves'."""
    low = type_label.lower()
    for needle, item, action in ACTIONS:
        if needle in low:
            return item, action
    return DEFAULT_ACTION


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _area_incidents(r: ReportData) -> dict[str, list]:
    out: dict[str, list] = {}
    for i in r.incidents:
        out.setdefault(i.area, []).append(i)
    return out


def _r1_area_type(r: ReportData, areas: dict[str, list]) -> list[Recommendation]:
    out = []
    for area, n in r.by_area:
        if n / r.current.incidents < 0.2:
            continue
        kind, k = Counter(i.type_label for i in areas[area]).most_common(1)[0]
        if k < MIN_INCIDENTS or k / n < 0.5:
            continue
        _, action = action_for(kind)
        out.append(Recommendation(
            f"At {area}, {kind.lower()} accounts for {fmt_int(k)} incidents "
            f"({fmt_pct(k / n)} of the area's). {_cap(action)}.",
            k, area,
        ))
    return out


def _r2_time_window(r: ReportData, areas: dict[str, list]) -> list[Recommendation]:
    floor = 10 if r.preset == PRESET_DAILY else 20
    out = []
    for area, incs in areas.items():
        if len(incs) < floor:
            continue
        by_hour = Counter(i.started_at.hour for i in incs)
        start, best = max(
            ((h, sum(by_hour[(h + k) % 24] for k in range(WINDOW_HOURS))) for h in range(24)),
            key=lambda x: (x[1], -x[0]),
        )
        share = best / len(incs)
        if share < 0.4:
            continue
        out.append(Recommendation(
            f"Schedule supervisor rounds at {area} between {fmt_hhmm(start)} and "
            f"{fmt_hhmm(start + WINDOW_HOURS)}, when {fmt_pct(share)} of its incidents start.",
            best, area,
        ))
    return out


def _r3_shift(r: ReportData) -> list[Recommendation]:
    active = [s for s in r.shifts if s.hours > 0]
    if len(active) < 2 or r.current.incidents < 20:
        return []
    hi = max(active, key=lambda s: s.per_hour)
    lo = min(active, key=lambda s: s.per_hour)
    if lo.per_hour == 0 or hi.per_hour / lo.per_hour < 1.5:
        return []
    return [Recommendation(
        f"Review PPE supervision on {hi.name} ({hi.hours_label}): its incident rate is "
        f"{hi.per_hour / lo.per_hour:.1f}× that of {lo.name}.",
        hi.incidents,
    )]


def _r4_sustained(r: ReportData, areas: dict[str, list]) -> list[Recommendation]:
    out = []
    for area, incs in areas.items():
        long = [i for i in incs if i.duration_minutes >= LONG_MINUTES]
        if len(long) < 5:
            continue
        kind = Counter(i.type_label for i in long).most_common(1)[0][0]
        item, action = action_for(kind)
        out.append(Recommendation(
            f"At {area}, {fmt_int(len(long))} incidents lasted {LONG_MINUTES} minutes or more. "
            f"Long incidents suggest {item} are not to hand or not suited to the task: {action}.",
            len(long), area,
        ))
    return out


def _r5_camera(r: ReportData, areas: dict[str, list]) -> list[Recommendation]:
    out = []
    for area, incs in areas.items():
        if len(incs) / r.current.incidents < 0.1:
            continue
        cams = Counter(i.camera for i in incs)
        # An area seen by one camera has nothing to single out.
        if len(cams) < 2:
            continue
        cam, k = cams.most_common(1)[0]
        if k < MIN_INCIDENTS or k / len(incs) < 0.6:
            continue
        out.append(Recommendation(
            f"Most of {area}'s incidents ({fmt_pct(k / len(incs))}) are seen by {cam}: "
            f"focus PPE checks on the access point it covers.",
            k, area,
        ))
    return out


def _r6_rising(r: ReportData) -> list[Recommendation]:
    if not r.has_comparison:
        return []
    rolled = r.rollout_types
    out = []
    for area, n in r.by_area:
        if n < MIN_INCIDENTS or n / r.current.incidents < 0.1:
            continue
        cur = sum(v for (a, t), v in r.current.by_area_type.items() if a == area and t not in rolled)
        prev = sum(v for (a, t), v in r.prev.by_area_type.items() if a == area and t not in rolled)
        change = r.change(cur, prev)
        if change is None or change < 0.3:
            continue
        # What this concerns is the rise, not the area's whole count.
        excess = cur - r.per_day(prev, r.previous) * r.period.covered_days
        out.append(Recommendation(
            f"Find out what changed at {area}: incidents per day are up {fmt_pct(change)} on "
            f"{r.baseline_label}. A new crew, a new work front or changed access are the usual "
            f"causes.",
            max(round(excess), 1), area,
        ))
    return out


def build_recommendations(r: ReportData, limit: int = MAX_RECOMMENDATIONS) -> list[Recommendation]:
    if not r.current.incidents:
        return []
    areas = _area_incidents(r)
    found = (
        _r1_area_type(r, areas)
        + _r2_time_window(r, areas)
        + _r3_shift(r)
        + _r4_sustained(r, areas)
        + _r5_camera(r, areas)
        + _r6_rising(r)
    )
    picked: list[Recommendation] = []
    per: Counter = Counter()
    for rec in sorted(found, key=lambda x: -x.weight):
        if rec.area is not None and per[rec.area] >= PER_AREA:
            continue
        picked.append(rec)
        if rec.area is not None:
            per[rec.area] += 1
        if len(picked) == limit:
            break
    return picked or [Recommendation(NOTHING_STOOD_OUT, 0)]
