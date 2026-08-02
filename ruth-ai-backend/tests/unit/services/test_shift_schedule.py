"""Unit tests for the shift schedule algorithm.

Covers the two things that are easy to get subtly wrong: shifts that cross
midnight, and schedules that look plausible but do not tile the day.

Pure functions over a fixed clock — no database, no fixtures.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services.shift_schedule import (
    MINUTES_PER_DAY,
    ShiftDefinition,
    ShiftSchedule,
    ShiftScheduleError,
    default_schedule,
    resolve_current_shift,
    validate_schedule,
)

IST = ZoneInfo("Asia/Kolkata")

DAY = ShiftDefinition(name="Day", start="07:00", end="19:00")
NIGHT = ShiftDefinition(name="Night", start="19:00", end="07:00")

TWO_SHIFT = ShiftSchedule(mode="shifts", timezone="Asia/Kolkata", shifts=[DAY, NIGHT])
THREE_SHIFT = ShiftSchedule(
    mode="shifts",
    timezone="Asia/Kolkata",
    shifts=[
        ShiftDefinition(name="A", start="06:00", end="14:00"),
        ShiftDefinition(name="B", start="14:00", end="22:00"),
        ShiftDefinition(name="C", start="22:00", end="06:00"),
    ],
)


def local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=IST)


class TestDuration:
    def test_ordinary_shift(self):
        assert DAY.duration_minutes == 720

    def test_shift_crossing_midnight(self):
        """19:00-07:00 is 12 hours forward, not a negative span."""
        assert NIGHT.duration_minutes == 720

    def test_end_equal_to_start_is_a_full_day(self):
        """`mod 1440` would collapse 07:00-07:00 to zero and uncover the day."""
        full = ShiftDefinition(name="Full", start="07:00", end="07:00")
        assert full.duration_minutes == MINUTES_PER_DAY


class TestValidation:
    def test_continuous_is_always_valid(self):
        assert validate_schedule(default_schedule()) is None

    def test_two_twelve_hour_shifts_accepted(self):
        assert validate_schedule(TWO_SHIFT) is None

    def test_three_eight_hour_shifts_accepted(self):
        assert validate_schedule(THREE_SHIFT) is None

    def test_plain_overlap_rejected(self):
        schedule = ShiftSchedule(
            mode="shifts",
            shifts=[DAY, ShiftDefinition(name="Late", start="18:00", end="07:00")],
        )
        with pytest.raises(ShiftScheduleError) as exc:
            validate_schedule(schedule)
        assert "Day / Late" in exc.value.conflicts

    def test_wrap_around_overlap_rejected(self):
        """The case a naive `start < end` comparison misses.

        Night runs 19:00 -> 07:00 and Early starts at 06:00, so they
        collide on the far side of midnight even though neither start is
        inside the other's start..end range read left-to-right.
        """
        schedule = ShiftSchedule(
            mode="shifts",
            shifts=[NIGHT, ShiftDefinition(name="Early", start="06:00", end="19:00")],
        )
        with pytest.raises(ShiftScheduleError) as exc:
            validate_schedule(schedule)
        assert exc.value.conflicts

    def test_gap_rejected(self):
        schedule = ShiftSchedule(
            mode="shifts",
            shifts=[ShiftDefinition(name="Day", start="08:00", end="18:00")],
        )
        with pytest.raises(ShiftScheduleError) as exc:
            validate_schedule(schedule)
        assert exc.value.conflicts == ["18:00-08:00"]

    def test_one_hour_gap_reported_precisely(self):
        schedule = ShiftSchedule(
            mode="shifts",
            shifts=[DAY, ShiftDefinition(name="Night", start="20:00", end="07:00")],
        )
        with pytest.raises(ShiftScheduleError) as exc:
            validate_schedule(schedule)
        assert exc.value.conflicts == ["19:00-20:00"]

    def test_empty_shift_list_rejected(self):
        with pytest.raises(ShiftScheduleError):
            validate_schedule(ShiftSchedule(mode="shifts", shifts=[]))

    def test_unknown_timezone_rejected(self):
        with pytest.raises(ValueError):
            ShiftSchedule(mode="continuous", timezone="Not/AZone")

    def test_default_timezone(self):
        assert default_schedule().timezone == "Asia/Kolkata"


class TestResolveCurrentShift:
    def test_after_midnight_is_yesterdays_night_shift(self):
        """At 02:00 you are in the night shift that started 19:00 yesterday."""
        window = resolve_current_shift(TWO_SHIFT, local(2026, 8, 2, 2))
        assert window.name == "Night"
        assert window.start.astimezone(IST) == local(2026, 8, 1, 19)
        assert window.end.astimezone(IST) == local(2026, 8, 2, 7)

    def test_window_start_is_inclusive(self):
        assert resolve_current_shift(TWO_SHIFT, local(2026, 8, 2, 7)).name == "Day"

    def test_window_end_is_exclusive(self):
        """19:00 belongs to Night only — half-open windows, no double count."""
        window = resolve_current_shift(TWO_SHIFT, local(2026, 8, 2, 19))
        assert window.name == "Night"
        assert window.start.astimezone(IST) == local(2026, 8, 2, 19)

    def test_last_minute_before_midnight(self):
        window = resolve_current_shift(TWO_SHIFT, local(2026, 8, 2, 23, 59))
        assert window.name == "Night"
        assert window.start.astimezone(IST) == local(2026, 8, 2, 19)

    def test_midnight_keeps_the_same_night_window(self):
        window = resolve_current_shift(TWO_SHIFT, local(2026, 8, 3, 0))
        assert window.name == "Night"
        assert window.start.astimezone(IST) == local(2026, 8, 2, 19)

    def test_utc_input_is_converted_to_site_local(self):
        """21:00Z is 02:30 IST the next day, i.e. the night shift."""
        window = resolve_current_shift(
            TWO_SHIFT, datetime(2026, 8, 1, 21, 0, tzinfo=timezone.utc)
        )
        assert window.name == "Night"
        assert window.start.astimezone(IST) == local(2026, 8, 1, 19)

    def test_continuous_is_the_local_calendar_day(self):
        window = resolve_current_shift(default_schedule(), local(2026, 8, 2, 13, 45))
        assert window.name == "Continuous"
        assert window.start.astimezone(IST) == local(2026, 8, 2, 0)
        assert window.end.astimezone(IST) == local(2026, 8, 3, 0)

    @pytest.mark.parametrize(
        "hour,expected_name,expected_start_day,expected_start_hour",
        [
            (6, "A", 2, 6),
            (13, "A", 2, 6),
            (14, "B", 2, 14),
            (22, "C", 2, 22),
            (3, "C", 1, 22),
        ],
    )
    def test_three_shift_boundaries(
        self, hour, expected_name, expected_start_day, expected_start_hour
    ):
        window = resolve_current_shift(THREE_SHIFT, local(2026, 8, 2, hour))
        assert window.name == expected_name
        assert window.start.astimezone(IST) == local(
            2026, 8, expected_start_day, expected_start_hour
        )

    def test_every_minute_of_the_day_resolves_exactly_once(self):
        """A valid schedule leaves no instant unclaimed and none double-claimed."""
        for minute in range(MINUTES_PER_DAY):
            instant = local(2026, 8, 2, minute // 60, minute % 60)
            window = resolve_current_shift(THREE_SHIFT, instant)
            assert window.start <= instant < window.end

    def test_uncovered_instant_raises(self):
        """Only reachable for a schedule stored before gaps were rejected."""
        schedule = ShiftSchedule.model_construct(
            mode="shifts",
            timezone="Asia/Kolkata",
            shifts=[ShiftDefinition(name="Day", start="08:00", end="18:00")],
        )
        with pytest.raises(ShiftScheduleError):
            resolve_current_shift(schedule, local(2026, 8, 2, 3))
