"""A violation's location (area / side / display name) — stored, not joined.

A camera is often reinstalled at another manway. Violations must stay with
the manway where the camera WAS, so each violation stores its location when
it is written, taken from VAS's placement history (VAS owns it; the generic
VAS term is "location", Ruth shows it as Manway/area):

* :func:`stamp_location` — call when creating a violation.
* :func:`camera_fields`, :func:`area_of`, :func:`area_filter` — every reader
  (violations list/detail, incident cards, area filter, reports, exports)
  goes through these, so stored values are used everywhere and the live
  device is consulted only for rows not stamped yet (``location_stamped_at``
  NULL: created before this feature and not backfilled).

Stamping never blocks or fails a violation: VAS is asked with a short
timeout, answers are cached per camera for the placement's window (bounded
by CACHE_TTL so a Move camera made elsewhere is picked up quickly), and if
VAS is unreachable Ruth's mirrored device row is used (``location_source =
'mirror'``) — the camera's current location, which is the right answer for
a violation happening now.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select

from app.core.logging import get_logger
from app.models import Device, Violation

logger = get_logger(__name__)

#: Seconds a cached placement is trusted before VAS is asked again.
CACHE_TTL = 60.0
#: VAS lookup budget on the violation write path.
VAS_TIMEOUT = 2.0


@dataclass(frozen=True)
class Stamp:
    area: str | None
    in_out: str | None
    display_name: str | None
    source: str  # vas | mirror | backfill


@dataclass
class _Cached:
    fetched: float
    valid_from: datetime | None
    valid_to: datetime | None
    stamp: Stamp


_cache: dict[str, _Cached] = {}


def invalidate(vas_device_id: str | None = None) -> None:
    """Forget cached placements (one camera, or all). Call after a move."""
    if vas_device_id is None:
        _cache.clear()
    else:
        _cache.pop(str(vas_device_id), None)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _clean(v: Any) -> str | None:
    v = (str(v) if v is not None else "").strip()
    return v or None


def stamp_from_vas(answer: dict, device_name: str, source: str = "vas") -> Stamp:
    """Build a Stamp from VAS's GET /devices/{id}/placement answer."""
    p = answer.get("placement") or {}
    return Stamp(
        area=_clean(p.get("location")),
        in_out=_clean(p.get("in_out")),
        display_name=_clean(answer.get("display_name")) or device_name,
        source=source,
    )


def stamp_from_mirror(device: Device) -> Stamp:
    return Stamp(
        area=_clean(device.manway),
        in_out=_clean(device.in_out),
        display_name=_clean(device.display_name) or device.name,
        source="mirror",
    )


async def resolve(device: Device, at: datetime) -> Stamp:
    """Where ``device`` was at ``at``: VAS placement, else Ruth's mirror."""
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    key = str(device.vas_device_id)
    hit = _cache.get(key)
    if (
        hit is not None
        and time.monotonic() - hit.fetched < CACHE_TTL
        and (hit.valid_from is None or hit.valid_from <= at)
        and (hit.valid_to is None or at < hit.valid_to)
        and hit.valid_from is not None  # an "unplaced" answer has no window
    ):
        return hit.stamp

    from app.deps.services import get_vas_client_optional

    client = get_vas_client_optional()
    if client is not None:
        try:
            answer = await client.get_placement_at(
                key, at, timeout=VAS_TIMEOUT, retries=0
            )
            stamp = stamp_from_vas(answer, device.name)
            p = answer.get("placement") or {}
            _cache[key] = _Cached(
                time.monotonic(), _parse(p.get("valid_from")), _parse(p.get("valid_to")), stamp
            )
            return stamp
        except Exception as e:  # never fail a violation over this
            logger.warning(
                "VAS placement lookup failed; using Ruth's device copy",
                vas_device_id=key,
                error=str(e),
            )
    return stamp_from_mirror(device)


def apply(violation: Violation, stamp: Stamp, when: datetime | None = None) -> None:
    violation.area = stamp.area
    violation.in_out = stamp.in_out
    violation.camera_display_name = stamp.display_name
    violation.location_source = stamp.source
    violation.location_stamped_at = when or datetime.now(timezone.utc)


async def stamp_location(violation: Violation, device: Device | None, at: datetime) -> None:
    """Store where the camera was at ``at`` on ``violation``. Never raises."""
    if device is None:
        return
    try:
        apply(violation, await resolve(device, at))
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not stamp violation location", error=str(e))


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------


def is_stamped(row: Any) -> bool:
    return getattr(row, "location_stamped_at", None) is not None


def camera_fields(device: Device | None, violation: Any = None) -> dict:
    """Display name, area and side for a violation.

    Stored values when the violation is stamped; otherwise (old, not yet
    backfilled rows, or callers without a violation) the device's current
    values.
    """
    if violation is not None and is_stamped(violation):
        return {
            "camera_display_name": _clean(violation.camera_display_name),
            "camera_area": _clean(violation.area),
            "camera_in_out": _clean(violation.in_out),
        }
    if device is None:
        return {"camera_display_name": None, "camera_area": None, "camera_in_out": None}
    return {
        "camera_display_name": _clean(device.display_name),
        "camera_area": _clean(device.manway),
        "camera_in_out": _clean(device.in_out),
    }


def area_of(row: Any, device: Device | None) -> str | None:
    """The violation's area: stored, else (unstamped) the device's manway."""
    if is_stamped(row):
        return _clean(row.area)
    return _clean(device.manway) if device is not None else None


def area_filter(area: str):
    """SQL condition: violation was in ``area`` (stored; live for unstamped)."""
    area = area.strip()
    return or_(
        and_(Violation.location_stamped_at.isnot(None), Violation.area == area),
        and_(
            Violation.location_stamped_at.is_(None),
            Violation.device_id.in_(select(Device.id).where(Device.manway == area)),
        ),
    )


# ---------------------------------------------------------------------------
# Backfill (scripts/backfill_violation_locations.py)
# ---------------------------------------------------------------------------


def windows_from_placements(placements: list[dict]) -> list[tuple[datetime, datetime | None, Stamp]]:
    """VAS placement history -> [(valid_from, valid_to, Stamp)], oldest first."""
    out = []
    for p in placements:
        out.append(
            (
                _parse(p["valid_from"]),
                _parse(p.get("valid_to")),
                Stamp(
                    area=_clean(p.get("location")),
                    in_out=_clean(p.get("in_out")),
                    display_name=_clean(p.get("display_name")),
                    source="backfill",
                ),
            )
        )
    out.sort(key=lambda w: w[0])
    return out


def unverified(placements: list[dict]) -> bool:
    """True if any row is a seed (start time assumed, not confirmed)."""
    return any(not p.get("verified", p.get("source") != "seed") for p in placements)
