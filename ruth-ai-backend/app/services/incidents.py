"""Group repeated violations into incidents.

A busy camera raises the same violation every few seconds while one person
stands in view: the median gap between repeats was measured at 53 s and 75%
fall within 5 minutes. Listing each one buries everything else, so the
Violations page shows incidents instead.

An incident is a run of violations with the same camera and the same
specific type (type_detail, or the family when there is none) where each one
follows the previous within ``gap`` — and the run never spans more than
``max_span`` from its first violation, so a camera that fires all day is cut
into hour-sized incidents rather than one card.

Computed on the fly from the filtered violations, never stored: filters
change what an incident contains (viewing "Open" groups only the open ones),
and new repeats extend the newest incident as they arrive.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Protocol
from uuid import UUID

from app.services.violation_severity import worst_severity


class IncidentRow(Protocol):
    id: UUID
    device_id: UUID
    type: object
    type_detail: str | None
    timestamp: datetime
    status: object
    severity: str | None


@dataclass
class Incident:
    device_id: UUID
    type: str
    type_detail: str | None
    first_at: datetime
    last_at: datetime
    #: Oldest first.
    members: list = field(default_factory=list)

    @property
    def key(self) -> str:
        """Stable while the incident grows: camera, type, first violation."""
        return f"{self.device_id}:{self.type_detail or self.type}:{self.members[0].id}"

    @property
    def latest(self):
        return self.members[-1]

    @property
    def count(self) -> int:
        return len(self.members)

    def count_with_status(self, status_value: str) -> int:
        return sum(1 for m in self.members if _value(m.status) == status_value)

    def severity(self, resolve) -> str:
        """Worst member severity; ``resolve(row)`` fills NULLs."""
        return worst_severity(m.severity or resolve(m) for m in self.members)


def _value(v) -> str:
    return getattr(v, "value", v)


def group_incidents(
    rows: Iterable[IncidentRow],
    gap: timedelta,
    max_span: timedelta,
) -> list[Incident]:
    """Rows in any order -> incidents, most recently active first."""
    by_key: dict[tuple, list] = {}
    for row in rows:
        family = _value(row.type)
        by_key.setdefault((row.device_id, family, row.type_detail), []).append(row)

    incidents: list[Incident] = []
    for (device_id, family, detail), members in by_key.items():
        members.sort(key=lambda r: (r.timestamp, str(r.id)))
        current: Incident | None = None
        for row in members:
            if (
                current is None
                or row.timestamp - current.last_at > gap
                or row.timestamp - current.first_at > max_span
            ):
                current = Incident(device_id, family, detail, row.timestamp, row.timestamp)
                incidents.append(current)
            current.members.append(row)
            current.last_at = row.timestamp

    incidents.sort(key=lambda i: (i.last_at, i.key), reverse=True)
    return incidents
