"""Running a bulk evidence export: resolve, build, sweep.

Split from ``violation_export`` so the archive writer stays pure and
blocking (easy to test, safe in a worker thread) while everything that
touches the database or VAS lives here.

The filtered query is passed in by the API layer rather than rebuilt here.
That is deliberate: ``_apply_filters`` on the Violations endpoints is the
single definition of what the page's filters mean, and an export that
quietly disagreed with the list the operator was looking at would be worse
than no export. Passing the statement also keeps the service from importing
the API module, which would be a cycle.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.device import Device
from app.models.enums import EvidenceStatus, EvidenceType
from app.models.evidence import Evidence
from app.models.violation_export import (
    EXPORT_BUILDING,
    EXPORT_EXPIRED,
    EXPORT_FAILED,
    EXPORT_READY,
    ViolationExport,
)
from app.services.false_positive_export import (
    EVIDENCE_INFERRED_FRAME,
    EVIDENCE_SCENE_SNAPSHOT,
    ExportItem,
)
from app.services.incidents import group_incidents
from app.services.violation_export import (
    CHUNK,
    ExportOptions,
    Plan,
    PlannedItem,
    finalize,
    open_archive,
    pick_one_per_incident,
    write_chunk,
)
from app.services.violation_labels import ViolationLabeler

logger = get_logger(__name__)


def _camera_fields(device: Device | None) -> dict:
    """The violations API's own helper, so sidecars agree with the UI exactly.

    Imported inside the function: the API module imports this service, so a
    module-level import would be a cycle. Reused rather than reimplemented
    because the mapping is not obvious — area is ``manway`` and the side is
    ``in_out`` — and two copies would drift.
    """
    from app.api.v1.violations import camera_fields

    return camera_fields(device)


async def resolve_plan(
    db: AsyncSession, base_stmt, options: ExportOptions
) -> Plan:
    """Turn the filtered query plus options into the exact list to export."""
    violations = list((await db.execute(base_stmt)).scalars())
    matched = len(violations)
    if not violations:
        return Plan(items=[], matched=0, no_frame=0)

    ids = [v.id for v in violations]
    frames = dict(
        (
            await db.execute(
                select(Evidence.violation_id, Evidence.file_path).where(
                    Evidence.violation_id.in_(ids),
                    Evidence.evidence_type == EvidenceType.FRAME,
                    Evidence.status == EvidenceStatus.READY,
                )
            )
        ).all()
    )
    snapshots = dict(
        (
            await db.execute(
                select(Evidence.violation_id, Evidence.vas_snapshot_id).where(
                    Evidence.violation_id.in_(ids),
                    Evidence.evidence_type == EvidenceType.SNAPSHOT,
                    Evidence.vas_snapshot_id.isnot(None),
                )
            )
        ).all()
    )
    devices = {
        d.id: d
        for d in (
            await db.execute(
                select(Device).where(Device.id.in_({v.device_id for v in violations}))
            )
        ).scalars()
    }

    labeler = ViolationLabeler.current()
    frame_root = Path(get_settings().evidence_frame_dir).resolve()
    plans: list[PlannedItem] = []
    for v in violations:
        cam = _camera_fields(devices.get(v.device_id))
        family = getattr(v.type, "value", v.type)

        frame_path = None
        rel = frames.get(v.id)
        if rel:
            candidate = (frame_root / rel).resolve()
            # A file_path from the database still must not escape the root.
            if candidate.is_relative_to(frame_root) and candidate.is_file():
                frame_path = candidate

        plans.append(
            PlannedItem(
                item=ExportItem(
                    violation_id=v.id,
                    model_id=v.model_id,
                    model_version=v.model_version,
                    type=family,
                    type_detail=v.type_detail,
                    severity=labeler.severity(v),
                    confidence=v.confidence,
                    timestamp=v.timestamp,
                    camera_name=v.camera_name,
                    camera_display_name=cam["camera_display_name"],
                    camera_area=cam["camera_area"],
                    camera_in_out=cam["camera_in_out"],
                    bounding_boxes=v.bounding_boxes,
                    frame_file=rel,
                    group_key=f"{v.device_id}:{v.type_detail or family}",
                    status=getattr(v.status, "value", v.status),
                ),
                frame_path=frame_path,
                snapshot_id=snapshots.get(v.id),
                status=getattr(v.status, "value", v.status),
                reviewed_by=v.reviewed_by,
                reviewed_at=v.reviewed_at,
                dismiss_reason=getattr(v.dismiss_reason, "value", v.dismiss_reason),
                # Same label the analytics CSV puts in this column.
                type_label=labeler.family_label(v.type),
            )
        )

    # Incident grouping, when the operator picked incidents or asked for one
    # image per incident. Regrouped from the same filters with the same gap
    # and span as the page, so the keys match what they clicked.
    if options.incident_ids or options.scope == "one_per_incident":
        incidents = group_incidents(
            violations,
            gap=timedelta(minutes=get_settings().incident_gap_minutes),
            max_span=timedelta(minutes=get_settings().incident_max_span_minutes),
        )
        key_of: dict[uuid.UUID, str] = {}
        for incident in incidents:
            for member in incident.members:
                key_of[member.id] = incident.key

        if options.incident_ids:
            wanted = set(options.incident_ids)
            known = {i.key for i in incidents}
            missing = sorted(wanted - known)
            if missing:
                # Grouping depends on the filters; if they drifted between the
                # page and the request, say so rather than exporting a
                # different set than was selected.
                raise ValueError(
                    f"{len(missing)} selected incident(s) do not match the "
                    f"filters supplied; reload the list and try again"
                )
            plans = [p for p in plans if key_of.get(p.item.violation_id) in wanted]

        if options.scope == "one_per_incident":
            plans = pick_one_per_incident(
                plans, lambda p: key_of.get(p.item.violation_id)
            )

    plans.sort(key=lambda p: (p.item.timestamp, str(p.item.violation_id)))
    no_frame = sum(1 for p in plans if not p.has_frame)
    return Plan(items=plans, matched=matched, no_frame=no_frame)


async def _fetch_snapshots(plans: list[PlannedItem]) -> dict[uuid.UUID, bytes]:
    """Pull scene snapshots from VAS, a few at a time.

    Each is a ~810KB full-resolution image and VAS serves every camera's
    frame fetch from one event loop (BL-12), so concurrency is capped and a
    failure costs one image rather than the export.
    """
    from app.deps.services import get_vas_client_optional

    targets = [p for p in plans if not p.has_frame and p.snapshot_id]
    if not targets:
        return {}

    # The app's shared client, as the other background services use. Opening
    # a private one would mean a second authentication and its own token to
    # refresh, for no gain.
    client = get_vas_client_optional()
    if client is None:
        logger.warning(
            "Snapshot fallback requested but VAS is not connected; "
            "those violations will be reported as having no frame",
            wanted=len(targets),
        )
        return {}

    out: dict[uuid.UUID, bytes] = {}
    semaphore = asyncio.Semaphore(get_settings().violation_export_snapshot_concurrency)

    async def one(plan: PlannedItem) -> None:
        async with semaphore:
            try:
                chunks = []
                async with client.download_snapshot_image(plan.snapshot_id) as resp:
                    async for part in resp.aiter_bytes():
                        chunks.append(part)
                out[plan.item.violation_id] = b"".join(chunks)
            except Exception as e:  # noqa: BLE001 - one image, not the job
                logger.warning(
                    "Export could not fetch snapshot",
                    violation_id=str(plan.item.violation_id),
                    error=str(e),
                )

    await asyncio.gather(*(one(p) for p in targets))
    return out


async def _touch(
    db: AsyncSession, export_id: uuid.UUID, **values
) -> None:
    values["updated_at"] = datetime.now(timezone.utc)
    await db.execute(
        update(ViolationExport).where(ViolationExport.id == export_id).values(**values)
    )
    await db.commit()


async def run_job(
    export_id: uuid.UUID, base_stmt, options: ExportOptions, session_factory
) -> None:
    """Build the archive for an already-created row. Owns its own session."""
    out_dir = Path(get_settings().violation_export_dir)
    final_path = out_dir / f"{export_id}.zip"
    tmp_path = out_dir / f".{export_id}.partial.zip"

    try:
        async with session_factory() as db:
            plan = await resolve_plan(db, base_stmt, options)
            await _touch(db, export_id, total=plan.total)

            snapshot_bytes: dict[uuid.UUID, bytes] = {}
            if options.include_snapshots:
                snapshot_bytes = await _fetch_snapshots(plan.items)

            csv_rows: list[list] = []
            counts = {"images": 0, "no_frame": 0, "skipped": 0}
            archive = await run_in_threadpool(open_archive, tmp_path)
            try:
                for start in range(0, plan.total, CHUNK):
                    batch = plan.items[start : start + CHUNK]
                    prepared = []
                    for p in batch:
                        if p.has_frame:
                            # write_chunk reads the file itself, in its thread.
                            prepared.append((p, None, EVIDENCE_INFERRED_FRAME))
                        else:
                            # None bytes here means no image at all, and
                            # write_chunk counts it as no_frame; the source
                            # label is only used when there is an image.
                            prepared.append(
                                (
                                    p,
                                    snapshot_bytes.get(p.item.violation_id),
                                    EVIDENCE_SCENE_SNAPSHOT,
                                )
                            )
                    part = await run_in_threadpool(
                        write_chunk,
                        archive,
                        prepared,
                        annotated=options.annotated,
                        csv_rows=csv_rows,
                    )
                    for k in counts:
                        counts[k] += part[k]
                    await _touch(
                        db,
                        export_id,
                        done=min(start + len(batch), plan.total),
                        images=counts["images"],
                        no_frame=counts["no_frame"],
                        skipped=counts["skipped"],
                    )

                manifest = {
                    "export_id": str(export_id),
                    "built_at": datetime.now(timezone.utc).isoformat(),
                    "request": options.as_dict(),
                    "violations_matching_filters": plan.matched,
                    "violations_in_export": plan.total,
                    "images_written": counts["images"],
                    "without_inferred_frame": counts["no_frame"],
                    "unreadable": counts["skipped"],
                    "notes": [
                        "images/ holds the exact frame each model inferred, "
                        "unannotated.",
                        "boxes are in the pixel space of that frame; a sidecar "
                        "with boxes_apply_to_image=false means the image is a "
                        "later scene snapshot and the boxes do not line up.",
                        "annotated/ contains inferred frames only.",
                    ],
                }
                await run_in_threadpool(finalize, archive, csv_rows, manifest)
            finally:
                await run_in_threadpool(archive.close)

            size = await run_in_threadpool(lambda: tmp_path.stat().st_size)
            await run_in_threadpool(tmp_path.replace, final_path)
            await _touch(
                db,
                export_id,
                status=EXPORT_READY,
                file_path=str(final_path),
                size_bytes=size,
                expires_at=datetime.now(timezone.utc)
                + timedelta(hours=get_settings().violation_export_ttl_hours),
            )
            logger.info(
                "Violation export ready",
                export_id=str(export_id),
                violations=plan.total,
                images=counts["images"],
                no_frame=counts["no_frame"],
                size_mb=round(size / 2**20, 1),
            )
    except Exception as e:  # noqa: BLE001 - a failed job must say so
        logger.error("Violation export failed", export_id=str(export_id), error=str(e))
        try:
            await run_in_threadpool(tmp_path.unlink, True)
        except Exception:
            pass
        try:
            async with session_factory() as db:
                await _touch(db, export_id, status=EXPORT_FAILED, error=str(e)[:2000])
        except Exception:
            logger.error("Could not mark export failed", export_id=str(export_id))


async def sweep_expired(session_factory, *, now: datetime | None = None) -> dict:
    """Delete archives past their TTL and fail jobs a restart abandoned."""
    now = now or datetime.now(timezone.utc)
    removed = abandoned = 0
    async with session_factory() as db:
        rows = list(
            (
                await db.execute(
                    select(ViolationExport).where(
                        ViolationExport.status.in_([EXPORT_READY, EXPORT_BUILDING])
                    )
                )
            ).scalars()
        )
        for row in rows:
            if row.status == EXPORT_READY and row.expires_at and row.expires_at <= now:
                if row.file_path:
                    try:
                        await run_in_threadpool(Path(row.file_path).unlink, True)
                    except Exception as e:  # noqa: BLE001
                        logger.warning(
                            "Could not delete expired export",
                            export_id=str(row.id),
                            error=str(e),
                        )
                row.status = EXPORT_EXPIRED
                row.file_path = None
                row.updated_at = now
                removed += 1
            elif row.status == EXPORT_BUILDING and (
                now - row.updated_at
            ) > timedelta(hours=1):
                # Nothing has touched it for an hour: the process that owned
                # it is gone. Better a failure the operator can see than a
                # spinner that never resolves.
                row.status = EXPORT_FAILED
                row.error = "build did not finish (backend restarted)"
                row.updated_at = now
                abandoned += 1
        if removed or abandoned:
            await db.commit()
    if removed or abandoned:
        logger.info("Swept violation exports", removed=removed, abandoned=abandoned)
    return {"removed": removed, "abandoned": abandoned}


class ExportSweeper:
    """Hourly: delete archives past their TTL, fail jobs a restart abandoned.

    Same shape as ClipStatusSync so there is one way background loops look
    in this codebase. Hourly rather than minutely because the TTL is in
    hours and the work is a handful of unlinks.
    """

    INTERVAL_SECONDS = 3600

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def run_once(self) -> dict:
        from app.core.database import get_session_factory

        factory = get_session_factory()
        if factory is None:
            return {"removed": 0, "abandoned": 0}
        return await sweep_expired(factory)

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - keep sweeping
                logger.warning("Export sweep failed", error=str(e))
            await asyncio.sleep(self.INTERVAL_SECONDS)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="export-sweeper")
            logger.info(
                "Violation export sweeper started",
                ttl_hours=get_settings().violation_export_ttl_hours,
            )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


export_sweeper = ExportSweeper()
