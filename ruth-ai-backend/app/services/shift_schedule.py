"""Shift schedule domain logic.

Pure computation over the site-global shift schedule: validation of a
proposed schedule and resolution of "which shift is `now` in".

Deliberately free of database, Redis and logging imports so the algorithm
can be exercised on its own. The persistence and HTTP layers live in
`app.services.shift_service` and `app.api.v1.shifts`.

Concepts
--------
A schedule is either CONTINUOUS (one 24h window aligned to the local
calendar day) or a list of named shifts with wall-clock start/end times in
a site-local IANA timezone.

Times are handled as *minutes since local midnight* on a 1440-minute
circle, which makes a shift that crosses midnight (19:00-07:00) an
ordinary arc rather than a special case.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

MINUTES_PER_DAY = 1440

#: Used when no schedule row exists yet. The site has not configured
#: shifts, which is a valid "continuous monitoring" posture rather than an
#: error, so the current window is simply the local calendar day.
DEFAULT_TIMEZONE = "Asia/Kolkata"

CONTINUOUS_SHIFT_NAME = "Continuous"


class ShiftScheduleError(ValueError):
    """A proposed schedule is not usable.

    Carries the offending shift names so the API layer can hand the
    operator something more actionable than "invalid".
    """

    def __init__(self, message: str, conflicts: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.conflicts = conflicts or []


def parse_hhmm(value: str) -> int:
    """Convert a "HH:MM" wall-clock string to minutes since midnight."""
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"Expected HH:MM, got {value!r}")
    hours, minutes = int(parts[0]), int(parts[1])
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError(f"Not a valid time of day: {value!r}")
    return hours * 60 + minutes


def format_hhmm(minutes: int) -> str:
    """Inverse of `parse_hhmm`, normalised onto the 1440-minute circle."""
    minutes %= MINUTES_PER_DAY
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


class ShiftDefinition(BaseModel):
    """One named shift in the schedule."""

    name: str = Field(..., min_length=1, max_length=64)
    start: str = Field(..., description='Local wall-clock start, "HH:MM"')
    end: str = Field(..., description='Local wall-clock end, "HH:MM"')

    @field_validator("start", "end")
    @classmethod
    def _validate_time(cls, v: str) -> str:
        parse_hhmm(v)  # raises on malformed input
        return v

    @property
    def start_minute(self) -> int:
        return parse_hhmm(self.start)

    @property
    def duration_minutes(self) -> int:
        """Length of the shift, walking forward around the clock.

        A shift whose end equals its start (07:00-07:00) is a full 24h
        shift, not a zero-length one — `mod 1440` would otherwise collapse
        it to nothing and leave the day uncovered.
        """
        span = (parse_hhmm(self.end) - self.start_minute) % MINUTES_PER_DAY
        return span or MINUTES_PER_DAY


class ShiftSchedule(BaseModel):
    """The site-global shift schedule.

    Stored as the `shift_schedule` value in `app_settings`.
    """

    mode: str = Field("continuous", pattern="^(continuous|shifts)$")
    timezone: str = Field(default=DEFAULT_TIMEZONE)
    shifts: list[ShiftDefinition] = Field(default_factory=list)

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown IANA timezone: {v!r}") from exc
        return v

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def default_schedule() -> ShiftSchedule:
    """The schedule used when nothing has been configured."""
    return ShiftSchedule(mode="continuous", timezone=DEFAULT_TIMEZONE, shifts=[])


def validate_schedule(schedule: ShiftSchedule) -> None:
    """Reject a schedule that overlaps or leaves the day uncovered.

    Both faults are found by painting every shift's arc onto a
    1440-minute circular array. Walking the arc forward from its start
    means a midnight-crossing shift wraps naturally, so 19:00-07:00 and
    06:00-08:00 are caught as the overlap they are — a plain
    `start < end` comparison would miss it.

    Raises:
        ShiftScheduleError: on an overlap, a gap, or an empty shift list.
    """
    if schedule.mode == "continuous":
        return  # A single 24h window can neither overlap nor leave a gap.

    if not schedule.shifts:
        raise ShiftScheduleError("Shift mode requires at least one shift.")

    owner: list[str | None] = [None] * MINUTES_PER_DAY
    conflicts: list[str] = []

    for shift in schedule.shifts:
        start = shift.start_minute
        for step in range(shift.duration_minutes):
            slot = (start + step) % MINUTES_PER_DAY
            existing = owner[slot]
            if existing is not None:
                pair = sorted({existing, shift.name})
                if pair not in [sorted(set(c.split(" / "))) for c in conflicts]:
                    conflicts.append(" / ".join(pair))
                continue
            owner[slot] = shift.name

    if conflicts:
        raise ShiftScheduleError(
            "Shifts overlap: " + "; ".join(conflicts),
            conflicts=conflicts,
        )

    uncovered = [i for i, name in enumerate(owner) if name is None]
    if uncovered:
        raise ShiftScheduleError(
            "Shifts must cover the full 24 hours. Uncovered: "
            + ", ".join(_describe_gaps(uncovered)),
            conflicts=_describe_gaps(uncovered),
        )


def _describe_gaps(uncovered: list[int]) -> list[str]:
    """Collapse uncovered minutes into readable "HH:MM-HH:MM" ranges."""
    gaps: list[str] = []
    run_start = uncovered[0]
    previous = uncovered[0]

    for minute in uncovered[1:]:
        if minute != previous + 1:
            gaps.append(f"{format_hhmm(run_start)}-{format_hhmm(previous + 1)}")
            run_start = minute
        previous = minute
    gaps.append(f"{format_hhmm(run_start)}-{format_hhmm(previous + 1)}")

    # A gap spanning midnight shows up as a run at the end of the day and
    # another at the start; join them so the operator sees one range.
    if len(gaps) > 1 and uncovered[0] == 0 and uncovered[-1] == MINUTES_PER_DAY - 1:
        first, last = gaps[0], gaps[-1]
        gaps = gaps[1:-1] + [f"{last.split('-')[0]}-{first.split('-')[1]}"]

    return gaps


class ShiftWindow(BaseModel):
    """The concrete time window of the shift that contains some instant."""

    name: str
    #: Absolute UTC bounds. Half-open: [start, end), so a violation at the
    #: rollover instant belongs to exactly one shift.
    start: datetime
    end: datetime
    mode: str
    timezone: str


def resolve_current_shift(schedule: ShiftSchedule, now: datetime) -> ShiftWindow:
    """Find the shift window containing `now`.

    The site has no DST, so wall-clock minute arithmetic on the local day
    is exact and the result can be converted straight back to UTC.

    Algorithm (minutes on a 1440 circle):
        offset = (now_minute - shift_start) mod 1440
        the shift contains `now` when offset < duration

    At 02:00 against a 19:00-07:00 shift: duration is 720 and offset is
    (120 - 1140) mod 1440 = 420, which is under 720 — so `now` is in the
    night shift that began at 19:00 *yesterday*, and subtracting the
    offset lands on that start instant.

    Args:
        schedule: The validated site schedule.
        now: Any timezone-aware instant.

    Returns:
        The containing window, with UTC bounds.

    Raises:
        ShiftScheduleError: if no shift contains `now`. Validation rejects
            gaps, so this only fires on a schedule written before that
            rule existed.
    """
    tz = schedule.tzinfo
    local_now = now.astimezone(tz)

    if schedule.mode == "continuous":
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_end = local_start + timedelta(days=1)
        return ShiftWindow(
            name=CONTINUOUS_SHIFT_NAME,
            start=local_start,
            end=local_end,
            mode=schedule.mode,
            timezone=schedule.timezone,
        )

    now_minute = local_now.hour * 60 + local_now.minute
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)

    for shift in schedule.shifts:
        offset = (now_minute - shift.start_minute) % MINUTES_PER_DAY
        if offset < shift.duration_minutes:
            # `now_minute` truncates to the minute, so rebuild the start
            # from local midnight rather than from `local_now`.
            local_start = local_midnight + timedelta(minutes=now_minute - offset)
            return ShiftWindow(
                name=shift.name,
                start=local_start,
                end=local_start + timedelta(minutes=shift.duration_minutes),
                mode=schedule.mode,
                timezone=schedule.timezone,
            )

    raise ShiftScheduleError(
        f"No shift covers {local_now.isoformat()}. The stored schedule "
        "leaves part of the day uncovered."
    )
