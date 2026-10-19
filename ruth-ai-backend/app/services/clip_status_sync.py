"""Background sync of clip (bookmark) status from VAS.

A clip is requested when a violation fires and VAS cuts it shortly after,
but Ruth only learned the result when someone opened that violation: the
detail endpoint was the only caller of sync_evidence_status. So the list
showed clips as "processing" for hours (162 at one count, up to 4 h old),
and the card's clip icon could not be trusted.

This loop polls VAS for clips still pending/processing, newest first, a
bounded batch per cycle, and records ready/failed. Clips older than the
max age are left alone: VAS has long since decided, and an unbounded scan
would grow with history. Every failure is logged and the loop carries on;
it never affects request handling.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.deps.services import get_vas_client_optional
from app.models import Evidence, EvidenceStatus, EvidenceType
from app.services.evidence_service import EvidenceService

logger = get_logger(__name__)


@dataclass
class SyncCounts:
    checked: int = 0
    ready: int = 0
    failed: int = 0
    errors: int = 0


def pending_clips_query(batch_size: int, max_age: timedelta, now: datetime):
    """Clips VAS may have finished: still pending/processing, recent first."""
    return (
        select(Evidence)
        .where(
            Evidence.evidence_type == EvidenceType.BOOKMARK,
            Evidence.status.in_([EvidenceStatus.PENDING, EvidenceStatus.PROCESSING]),
            Evidence.vas_bookmark_id.is_not(None),
            Evidence.requested_at >= now - max_age,
        )
        .order_by(Evidence.requested_at.desc())
        .limit(batch_size)
    )


class ClipStatusSync:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def run_once(self) -> SyncCounts:
        counts = SyncCounts()
        settings = get_settings()
        factory = get_session_factory()
        vas = get_vas_client_optional()
        if factory is None or vas is None:
            return counts

        async with factory() as db:
            stmt = pending_clips_query(
                settings.clip_sync_batch_size,
                timedelta(hours=settings.clip_sync_max_age_hours),
                datetime.now(timezone.utc),
            )
            clips = list((await db.execute(stmt)).scalars().all())
            service = EvidenceService(vas, db)
            for clip in clips:
                counts.checked += 1
                try:
                    await service.sync_evidence_status(clip)
                except Exception as e:  # noqa: BLE001 - one bad clip must not stop the rest
                    counts.errors += 1
                    logger.debug("Clip status sync failed", evidence_id=str(clip.id), error=str(e))
                    continue
                if clip.status == EvidenceStatus.READY:
                    counts.ready += 1
                elif clip.status == EvidenceStatus.FAILED:
                    counts.failed += 1
            await db.commit()

        if counts.ready or counts.failed or counts.errors:
            logger.info("Clip status sync", **counts.__dict__)
        return counts

    async def _loop(self) -> None:
        while True:
            interval = get_settings().clip_sync_interval_seconds
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - keep polling
                logger.warning("Clip status sync cycle failed", error=str(e))
            await asyncio.sleep(interval)

    def start(self) -> None:
        if get_settings().clip_sync_enabled and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="clip-status-sync")
            logger.info("Clip status sync started")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


clip_status_sync = ClipStatusSync()
