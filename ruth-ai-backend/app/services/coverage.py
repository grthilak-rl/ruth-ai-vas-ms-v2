"""Which cameras a project had in a period, and how long they were monitored.

- **Members during a period**: cameras whose project membership
  (``project_cameras`` joined_at .. left_at) overlaps the period. A camera
  removed mid-project still counts for the time it was in; one added later
  counts from when it joined. This is the camera total and the per-camera
  list on Analytics.
- **Monitored camera-hours**: the time cameras actually ran inference for the
  project in the period, from stream sessions (merged per camera so
  overlapping sessions are not counted twice; an open session counts up to
  now only while it is live). Rates are per monitored camera-hour (Analytics:
  violations per monitored camera-hour; reports: incidents per monitored
  camera-hour; the labels always say which): a
  stopped project, a disabled camera or a camera with no models contributes
  no hours and so does not dilute the rate.

Plain SQL with an explicit project id: neither table is auto-scoped
(project_scope.SCOPED_MODELS), and this must give the same answer in a
request session and a background job.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_MEMBERS_SQL = text("""
    SELECT DISTINCT device_id
      FROM project_cameras
     WHERE project_id = :project_id
       AND joined_at < :end
       AND (left_at IS NULL OR left_at > :start)
""")

_HAS_MEMBERSHIP_SQL = text("SELECT EXISTS (SELECT 1 FROM project_cameras WHERE project_id = :project_id)")

#: Session end for coverage: when it stopped; if still open, now while live,
#: else nothing (a session stuck in starting/error was never monitoring).
_SESSION_END = "COALESCE(stopped_at, CASE WHEN state = 'live' THEN now() ELSE started_at END)"

_HOURS_SQL = text(f"""
    SELECT device_id, EXTRACT(EPOCH FROM SUM(upper(r) - lower(r))) / 3600.0 AS hours
      FROM (
            SELECT device_id,
                   unnest(range_agg(tstzrange(GREATEST(started_at, :start),
                                              LEAST({_SESSION_END}, :end)))) AS r
              FROM stream_sessions
             WHERE project_id = :project_id
               AND started_at IS NOT NULL
               AND started_at < :end
               AND {_SESSION_END} > :start
             GROUP BY device_id
           ) merged
     GROUP BY device_id
""")


async def member_device_ids(
    db: AsyncSession, project_id: uuid.UUID, start: datetime, end: datetime
) -> set[uuid.UUID]:
    """Cameras that were members of the project at any point in [start, end)."""
    rows = await db.execute(_MEMBERS_SQL, {"project_id": project_id, "start": start, "end": end})
    return {r[0] for r in rows}


async def has_membership(db: AsyncSession, project_id: uuid.UUID) -> bool:
    """Has this project any membership recorded (False: e.g. a fresh install)?"""
    return bool((await db.execute(_HAS_MEMBERSHIP_SQL, {"project_id": project_id})).scalar())


async def monitored_hours(
    db: AsyncSession, project_id: uuid.UUID, start: datetime, end: datetime
) -> dict[uuid.UUID, float]:
    """Monitored hours per camera for the project in [start, end)."""
    rows = await db.execute(_HOURS_SQL, {"project_id": project_id, "start": start, "end": end})
    return {r[0]: float(r[1] or 0.0) for r in rows}


def per_camera_hour(count: int, hours: float) -> float | None:
    """`count` per monitored camera-hour, or None when nothing was monitored."""
    return count / hours if hours > 0 else None
