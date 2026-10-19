"""Violation API endpoints.

From API Contract - Violation APIs:
- GET    /violations
- GET    /violations/{id}
- POST   /violations/{id}/snapshot
- GET    /violations/{id}/video

These endpoints delegate to ViolationService and EvidenceService.
No business logic is implemented here.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.logging import get_logger
from app.deps import DBSession, EvidenceServiceDep, VASClientDep, ViolationServiceDep
from app.models import (
    Device,
    Evidence,
    EvidenceStatus,
    EvidenceType,
    StreamSession,
    Violation,
    ViolationStatus,
)
from app.schemas import (
    ErrorResponse,
    ViolationBulkRequest,
    ViolationBulkResponse,
    IncidentListResponse,
    IncidentResponse,
    SnapshotCreateRequest,
    SnapshotResponse,
    VideoEvidenceResponse,
    ViolationDetailResponse,
    ViolationEvidenceSummary,
    ViolationListResponse,
    ViolationResponse,
    ViolationStatusUpdateRequest,
    ViolationTypeDetailOption,
    ViolationTypeOption,
    ViolationTypesResponse,
)
from app.models.enums import ViolationType
from app.services.false_positive_export import (
    ExportItem,
    export_false_positives,
    is_false_alarm,
)
from app.services.frame_thumbnails import render_thumbnail
from app.services.incidents import group_incidents
from app.services.violation_labels import ViolationLabeler
from app.services.violation_severity import SEVERITY_LEVELS
from app.models.dismiss_reasons import DismissReason
from app.schemas.violation import (
    BulkSkipped,
    IncidentSummary,
    LabellingExport,
    SeverityCounts,
)
from app.services import (
    EvidenceVASError,
    NoActiveStreamError,
    ViolationNotFoundError,
    ViolationStateError,
    ViolationTerminalStateError,
)

router = APIRouter(tags=["Violations"])
logger = get_logger(__name__)

#: ``type_detail`` filter value selecting violations with no specific type.
NO_TYPE_DETAIL = "none"


def camera_fields(device: Device | None) -> dict:
    """Display name, area and side of the violation's camera, when known."""
    if device is None:
        return {"camera_display_name": None, "camera_area": None, "camera_in_out": None}
    return {
        "camera_display_name": (device.display_name or "").strip() or None,
        "camera_area": (device.manway or "").strip() or None,
        "camera_in_out": (device.in_out or "").strip() or None,
    }


async def export_dismissed_false_alarms(
    db,
    violations: list[Violation],
    reason: DismissReason | str | None,
    note: str | None,
    dismissed_by: str | None,
) -> LabellingExport | None:
    """Copy dismissed false alarms' inferred frames to the labelling set.

    Never raises: a failed copy is logged and counted, and the dismissal
    stands. Returns None when the reason is not a false alarm.
    """
    if not violations or not is_false_alarm(reason):
        return None
    settings = get_settings()
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
    devices = {
        d.id: d
        for d in (
            await db.execute(select(Device).where(Device.id.in_({v.device_id for v in violations})))
        ).scalars()
    }
    labeler = ViolationLabeler.current()
    items = []
    for v in violations:
        cam = camera_fields(devices.get(v.device_id))
        items.append(
            ExportItem(
                violation_id=v.id,
                model_id=v.model_id,
                model_version=v.model_version,
                type=getattr(v.type, "value", v.type),
                type_detail=v.type_detail,
                severity=labeler.severity(v),
                confidence=v.confidence,
                timestamp=v.timestamp,
                camera_name=v.camera_name,
                camera_display_name=cam["camera_display_name"],
                camera_area=cam["camera_area"],
                camera_in_out=cam["camera_in_out"],
                bounding_boxes=v.bounding_boxes,
                frame_file=frames.get(v.id),
                group_key=f"{v.device_id}:{v.type_detail or getattr(v.type, 'value', v.type)}",
            )
        )
    try:
        result = await run_in_threadpool(
            export_false_positives,
            items,
            reason,
            note,
            frame_root=Path(settings.evidence_frame_dir),
            labelling_root=Path(settings.labelling_root),
            dismissed_by=dismissed_by,
        )
    except Exception as e:  # noqa: BLE001 - the dismissal must stand regardless
        logger.error("False-positive export crashed", error=str(e), count=len(items))
        return LabellingExport(failed=len(items))
    return LabellingExport(**result.as_dict())


def apply_violation_filters(
    stmt,
    *,
    statuses: list[ViolationStatus] | None = None,
    camera_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    violation_type: ViolationType | None = None,
    type_detail: str | None = None,
    severities: list[str] | None = None,
    area: str | None = None,
):
    """The Violations page filters, shared by the list and incidents.

    Enums are parsed by FastAPI, so an unknown status or family is a 422
    rather than a database error from casting it.
    """
    if statuses:
        stmt = stmt.where(Violation.status.in_(statuses))
    if camera_id is not None:
        stmt = stmt.where(Violation.device_id == camera_id)
    if since is not None:
        stmt = stmt.where(Violation.timestamp >= since)
    if until is not None:
        stmt = stmt.where(Violation.timestamp <= until)
    if violation_type is not None:
        stmt = stmt.where(Violation.type == violation_type)
    if type_detail is not None:
        if type_detail.strip().lower() == NO_TYPE_DETAIL:
            stmt = stmt.where(Violation.type_detail.is_(None))
        else:
            stmt = stmt.where(Violation.type_detail == type_detail.strip().lower())
    if severities:
        levels = [s.strip().lower() for s in severities if s.strip().lower() in SEVERITY_LEVELS]
        if not levels:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "invalid_severity", "message": f"severity must be one of {SEVERITY_LEVELS}"},
            )
        stmt = stmt.where(Violation.severity.in_(levels))
    if area:
        stmt = stmt.where(
            Violation.device_id.in_(select(Device.id).where(Device.manway == area.strip()))
        )
    return stmt


def build_evidence_summary(evidence_list: list[Evidence]) -> ViolationEvidenceSummary | None:
    """Build evidence summary from evidence records.

    Args:
        evidence_list: List of Evidence model instances

    Returns:
        ViolationEvidenceSummary with snapshot/bookmark info, or None if no evidence
    """
    if not evidence_list:
        return None

    snapshot_evidence = None
    bookmark_evidence = None
    frame_evidence = None

    for e in evidence_list:
        if e.evidence_type == EvidenceType.SNAPSHOT and snapshot_evidence is None:
            snapshot_evidence = e
        elif e.evidence_type == EvidenceType.BOOKMARK and bookmark_evidence is None:
            bookmark_evidence = e
        elif e.evidence_type == EvidenceType.FRAME and frame_evidence is None:
            frame_evidence = e

    # If no evidence at all, return None
    if snapshot_evidence is None and bookmark_evidence is None and frame_evidence is None:
        return None

    frame_ready = bool(
        frame_evidence
        and frame_evidence.file_path
        and frame_evidence.status == EvidenceStatus.READY
    )
    return ViolationEvidenceSummary(
        frame_url=(
            f"/api/v1/violations/{frame_evidence.violation_id}/frame/image"
            if frame_evidence and frame_evidence.file_path
            else None
        ),
        frame_thumb_url=(
            f"/api/v1/violations/{frame_evidence.violation_id}/frame/thumb"
            if frame_ready
            else None
        ),
        # null, not "pending": nothing is coming if no frame was saved.
        frame_status=frame_evidence.status.value if frame_evidence else None,
        snapshot_id=snapshot_evidence.vas_snapshot_id if snapshot_evidence else None,
        snapshot_url=snapshot_evidence.snapshot_url if snapshot_evidence else None,
        snapshot_status=snapshot_evidence.status.value if snapshot_evidence else "pending",
        bookmark_id=bookmark_evidence.vas_bookmark_id if bookmark_evidence else None,
        bookmark_url=bookmark_evidence.bookmark_url if bookmark_evidence else None,
        # null when no clip was requested, so the UI can tell "none" from
        # "being prepared" instead of spinning forever.
        bookmark_status=bookmark_evidence.status.value if bookmark_evidence else None,
        bookmark_duration_seconds=(
            bookmark_evidence.bookmark_duration_seconds if bookmark_evidence else None
        ),
    )


@router.get(
    "/violations",
    response_model=ViolationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List violations",
    description="Returns violations with optional filtering.",
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def list_violations(
    db: DBSession,
    violation_status: list[ViolationStatus] | None = Query(
        None, alias="status", description="Filter by status (repeatable)"
    ),
    camera_id: UUID | None = Query(None, description="Filter by camera ID"),
    device_id: UUID | None = Query(
        None,
        deprecated=True,
        description="Deprecated alias for camera_id. Use camera_id.",
    ),
    since: datetime | None = Query(None, description="Violations after this timestamp"),
    until: datetime | None = Query(None, description="Violations before this timestamp"),
    violation_type: ViolationType | None = Query(
        None, alias="type", description="Filter by family (e.g. ppe_violation)"
    ),
    type_detail: str | None = Query(
        None,
        max_length=64,
        description=(
            "Filter by specific type (e.g. missing_gloves); "
            f"'{NO_TYPE_DETAIL}' selects violations with no specific type"
        ),
    ),
    severity: list[str] | None = Query(
        None, description="Filter by severity (repeatable): critical, high, medium, low"
    ),
    area: str | None = Query(None, max_length=64, description="Filter by camera area (manway)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> ViolationListResponse:
    """List all violations with optional filtering.

    The camera filter is named `camera_id` per API Contract §1.3. This
    endpoint previously only accepted `device_id`, so the frontend's
    `camera_id` was silently dropped and every caller got all cameras
    back. `device_id` stays accepted as a deprecated alias so existing
    callers keep working; `camera_id` wins when both are supplied.

    Args:
        db: Database session
        violation_status: Filter by status
        camera_id: Filter by camera UUID (the device's id)
        device_id: Deprecated alias for camera_id
        since: Only violations after this timestamp
        until: Only violations before this timestamp
        limit: Maximum results to return
        offset: Pagination offset

    Returns:
        List of violations with total count
    """
    camera_filter = camera_id if camera_id is not None else device_id
    # Build query with eager loading of evidence
    stmt = (
        select(Violation)
        .options(selectinload(Violation.evidence), selectinload(Violation.device))
        .order_by(Violation.timestamp.desc())
    )
    stmt = apply_violation_filters(
        stmt,
        statuses=violation_status,
        camera_id=camera_filter,
        since=since,
        until=until,
        violation_type=violation_type,
        type_detail=type_detail,
        severities=severity,
        area=area,
    )

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    # Apply pagination
    stmt = stmt.offset(offset).limit(limit)

    result = await db.execute(stmt)
    violations = list(result.scalars().all())

    logger.info(
        "Listing violations",
        total=total,
        returned=len(violations),
        status=[s.value for s in violation_status] if violation_status else None,
        camera_id=str(camera_filter) if camera_filter else None,
        type=violation_type.value if violation_type else None,
        type_detail=type_detail,
    )

    labeler = ViolationLabeler.current()
    return ViolationListResponse(
        items=[
            ViolationResponse(
                id=v.id,
                **labeler.type_fields(v),
                **camera_fields(v.device),
                status=v.status.value,
                camera_id=v.device_id,
                camera_name=v.camera_name,
                confidence=v.confidence,
                timestamp=v.timestamp,
                model_id=v.model_id,
                model_version=v.model_version,
                bounding_boxes=v.bounding_boxes,
                reviewed_by=v.reviewed_by,
                reviewed_at=v.reviewed_at,
                resolution_notes=v.resolution_notes,
                dismiss_reason=v.dismiss_reason,
                evidence=build_evidence_summary(list(v.evidence)),
                created_at=v.created_at,
                updated_at=v.updated_at,
            )
            for v in violations
        ],
        total=total,
    )


@router.get(
    "/violations/types",
    response_model=ViolationTypesResponse,
    status_code=status.HTTP_200_OK,
    summary="List violation types",
    description="Families and the specific types seen under each, with labels and counts.",
    responses={
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def list_violation_types(db: DBSession) -> ViolationTypesResponse:
    """Options for the type filter: only types that actually occur.

    Registered before /violations/{violation_id}, which would otherwise try
    to parse "types" as a UUID and answer 422.
    """
    stmt = (
        select(Violation.type, Violation.type_detail, func.count(Violation.id).label("count"))
        .group_by(Violation.type, Violation.type_detail)
    )
    rows = (await db.execute(stmt)).all()
    return ViolationTypesResponse(items=build_type_options(rows, ViolationLabeler.current()))


def build_type_options(rows, labeler: ViolationLabeler) -> list[ViolationTypeOption]:
    """Group (type, type_detail, count) rows into families, largest first.

    A family whose violations all lack a specific type gets no details: its
    single option is the family itself. A family mixing both lists the rows
    with none as their own option, labelled with the family alone, so every
    violation is reachable from the filter.
    """
    families: dict[str, ViolationTypeOption] = {}
    for row in rows:
        family = row.type.value if isinstance(row.type, ViolationType) else str(row.type)
        option = families.setdefault(
            family,
            ViolationTypeOption(type=family, label=labeler.family_label(family), count=0),
        )
        option.count += row.count
        option.details.append(
            ViolationTypeDetailOption(
                type_detail=row.type_detail,
                label=labeler.detail_label(row.type_detail) or labeler.family_label(family),
                count=row.count,
            )
        )

    for option in families.values():
        if all(d.type_detail is None for d in option.details):
            option.details = []
        else:
            option.details.sort(key=lambda d: (-d.count, d.label))
    return sorted(families.values(), key=lambda o: (-o.count, o.label))


async def summarize_incidents(db, rows, incidents, labeler: ViolationLabeler) -> IncidentSummary:
    """Totals across every incident matching the filters, not just the page."""
    by_severity = {level: 0 for level in SEVERITY_LEVELS}
    open_violations = 0
    per_device: dict = {}
    for row in rows:
        by_severity[labeler.severity(row)] += 1
        if getattr(row.status, "value", row.status) == ViolationStatus.OPEN.value:
            open_violations += 1
        per_device[row.device_id] = per_device.get(row.device_id, 0) + 1

    incident_severity = {level: 0 for level in SEVERITY_LEVELS}
    for incident in incidents:
        incident_severity[incident.severity(labeler.severity)] += 1

    per_area: dict[str, int] = {}
    if per_device:
        manways = await db.execute(
            select(Device.id, Device.manway).where(Device.id.in_(list(per_device)))
        )
        for device_id, manway in manways.all():
            area = (manway or "").strip()
            if area:
                per_area[area] = per_area.get(area, 0) + per_device[device_id]
    top_area = max(per_area, key=lambda a: (per_area[a], a)) if per_area else None

    return IncidentSummary(
        open_violations=open_violations,
        violations_by_severity=SeverityCounts(**by_severity),
        incidents_by_severity=SeverityCounts(**incident_severity),
        cameras=len(per_device),
        top_area=top_area,
        top_area_violations=per_area.get(top_area, 0) if top_area else 0,
    )


@router.post(
    "/violations/bulk",
    response_model=ViolationBulkResponse,
    status_code=status.HTTP_200_OK,
    summary="Change many violations at once",
    description=(
        "Mark reviewed, or dismiss with a reason, up to 1000 violations in one "
        "transaction. Each is validated like PATCH /violations/{id}; ones that "
        "cannot make the transition are skipped and listed, not failed. "
        "False-alarm dismissals export their inferred frames for labelling."
    ),
    responses={422: {"model": ErrorResponse, "description": "Invalid request"}},
)
async def bulk_update_violations(
    request: ViolationBulkRequest,
    violation_service: ViolationServiceDep,
    db: DBSession,
) -> ViolationBulkResponse:
    new_status = ViolationStatus.REVIEWED if request.action == "review" else ViolationStatus.DISMISSED
    reason = request.dismiss_reason.value if request.dismiss_reason and request.action == "dismiss" else None
    ids = list(dict.fromkeys(request.ids))  # de-duplicate, keep order

    rows = await db.execute(select(Violation).where(Violation.id.in_(ids)))
    by_id = {v.id: v for v in rows.scalars().all()}

    updated: list[Violation] = []
    skipped: list[BulkSkipped] = []
    for vid in ids:
        violation = by_id.get(vid)
        if violation is None:
            skipped.append(BulkSkipped(id=vid, reason="not_found"))
            continue
        try:
            violation_service.apply_transition(
                violation,
                new_status,
                reviewed_by=request.reviewed_by,
                resolution_notes=request.note,
                dismiss_reason=reason,
            )
        except ViolationTerminalStateError:
            skipped.append(BulkSkipped(id=vid, reason="terminal_state", status=violation.status.value))
            continue
        except ViolationStateError:
            skipped.append(BulkSkipped(id=vid, reason="invalid_transition", status=violation.status.value))
            continue
        updated.append(violation)

    # Commit before exporting: a labelling copy must never exist for a
    # violation whose dismissal did not stick.
    await db.commit()
    logger.info(
        "Bulk violation update",
        action=request.action,
        reason=reason,
        requested=len(ids),
        updated=len(updated),
        skipped=len(skipped),
    )

    labelling = None
    if new_status == ViolationStatus.DISMISSED:
        labelling = await export_dismissed_false_alarms(
            db, updated, request.dismiss_reason, request.note, request.reviewed_by
        )

    return ViolationBulkResponse(
        updated=[v.id for v in updated],
        skipped=skipped,
        labelling=labelling,
    )


@router.get(
    "/violations/incidents",
    response_model=IncidentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List violation incidents",
    description=(
        "Violations grouped into incidents: same camera and specific type, each "
        "within INCIDENT_GAP_MINUTES of the previous, spanning at most "
        "INCIDENT_MAX_SPAN_MINUTES. Same filters as GET /violations."
    ),
    responses={500: {"model": ErrorResponse, "description": "Internal server error"}},
)
async def list_incidents(
    db: DBSession,
    violation_status: list[ViolationStatus] | None = Query(
        None, alias="status", description="Filter by status (repeatable)"
    ),
    camera_id: UUID | None = Query(None, description="Filter by camera ID"),
    since: datetime | None = Query(None, description="Violations after this timestamp"),
    until: datetime | None = Query(None, description="Violations before this timestamp"),
    violation_type: ViolationType | None = Query(None, alias="type", description="Filter by family"),
    type_detail: str | None = Query(None, max_length=64, description="Filter by specific type"),
    severity: list[str] | None = Query(None, description="Filter by severity (repeatable)"),
    area: str | None = Query(None, max_length=64, description="Filter by camera area (manway)"),
    limit: int = Query(20, ge=1, le=200, description="Incidents per page"),
    offset: int = Query(0, ge=0, description="Pagination offset (incidents)"),
) -> IncidentListResponse:
    """Group the filtered violations, then page the incidents.

    Grouping needs every matching row, but only the light columns; full rows
    (evidence, device) are loaded for the page's representatives alone.
    Registered before /violations/{violation_id} for the same reason as
    /violations/types.
    """
    settings = get_settings()
    light = select(
        Violation.id,
        Violation.device_id,
        Violation.type,
        Violation.type_detail,
        Violation.timestamp,
        Violation.status,
        Violation.severity,
        Violation.model_id,
    )
    light = apply_violation_filters(
        light,
        statuses=violation_status,
        camera_id=camera_id,
        since=since,
        until=until,
        violation_type=violation_type,
        type_detail=type_detail,
        severities=severity,
        area=area,
    )
    rows = (await db.execute(light)).all()
    incidents = group_incidents(
        rows,
        gap=timedelta(minutes=settings.incident_gap_minutes),
        max_span=timedelta(minutes=settings.incident_max_span_minutes),
    )
    page = incidents[offset : offset + limit]

    labeler = ViolationLabeler.current()
    reps: dict = {}
    clipped: set = set()
    if page:
        rep_ids = [i.latest.id for i in page]
        rep_rows = await db.execute(
            select(Violation)
            .where(Violation.id.in_(rep_ids))
            .options(selectinload(Violation.evidence), selectinload(Violation.device))
        )
        reps = {v.id: v for v in rep_rows.scalars().all()}
        member_ids = [m.id for i in page for m in i.members]
        clip_rows = await db.execute(
            select(Evidence.violation_id).where(
                Evidence.violation_id.in_(member_ids),
                Evidence.evidence_type == EvidenceType.BOOKMARK,
                Evidence.status == EvidenceStatus.READY,
            )
        )
        clipped = set(clip_rows.scalars().all())

    items: list[IncidentResponse] = []
    for incident in page:
        rep_v = reps.get(incident.latest.id)
        if rep_v is None:  # deleted between the two queries
            continue
        newest_first = list(reversed(incident.members))
        cam = camera_fields(rep_v.device)
        items.append(
            IncidentResponse(
                incident_id=incident.key,
                camera_id=incident.device_id,
                camera_name=rep_v.camera_name,
                **cam,
                type=incident.type,
                type_detail=incident.type_detail,
                type_label=labeler.family_label(incident.type),
                detail_label=labeler.detail_label(incident.type_detail, rep_v.model_id),
                severity=incident.severity(labeler.severity),
                count=incident.count,
                open_count=incident.count_with_status(ViolationStatus.OPEN.value),
                first_at=incident.first_at,
                last_at=incident.last_at,
                has_clip=any(m.id in clipped for m in incident.members),
                violation_ids=[m.id for m in newest_first],
                open_violation_ids=[
                    m.id for m in newest_first
                    if getattr(m.status, "value", m.status) == ViolationStatus.OPEN.value
                ],
                representative=ViolationResponse(
                    id=rep_v.id,
                    **labeler.type_fields(rep_v),
                    **cam,
                    status=rep_v.status.value,
                    camera_id=rep_v.device_id,
                    camera_name=rep_v.camera_name,
                    confidence=rep_v.confidence,
                    timestamp=rep_v.timestamp,
                    model_id=rep_v.model_id,
                    model_version=rep_v.model_version,
                    bounding_boxes=rep_v.bounding_boxes,
                    reviewed_by=rep_v.reviewed_by,
                    reviewed_at=rep_v.reviewed_at,
                    resolution_notes=rep_v.resolution_notes,
                    dismiss_reason=rep_v.dismiss_reason,
                    evidence=build_evidence_summary(list(rep_v.evidence)),
                    created_at=rep_v.created_at,
                    updated_at=rep_v.updated_at,
                ),
            )
        )

    return IncidentListResponse(
        items=items,
        total=len(incidents),
        violations_total=len(rows),
        gap_minutes=settings.incident_gap_minutes,
        max_span_minutes=settings.incident_max_span_minutes,
        summary=await summarize_incidents(db, rows, incidents, labeler),
    )


@router.get(
    "/violations/{violation_id}",
    response_model=ViolationDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get violation details",
    description="Returns a single violation with associated evidence.",
    responses={
        404: {"model": ErrorResponse, "description": "Violation not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_violation(
    violation_id: UUID,
    violation_service: ViolationServiceDep,
    evidence_service: EvidenceServiceDep,
    db: DBSession,
) -> ViolationDetailResponse:
    """Get violation by ID with evidence.

    Args:
        violation_id: Violation UUID
        violation_service: Injected ViolationService
        db: Database session

    Returns:
        Violation details with evidence

    Raises:
        HTTPException: 404 if violation not found
    """
    try:
        violation = await violation_service.get_violation_by_id(violation_id)
    except ViolationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "violation_not_found",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    # Get evidence for violation
    evidence_stmt = (
        select(Evidence)
        .where(Evidence.violation_id == violation_id)
        .order_by(Evidence.requested_at.desc())
    )
    evidence_result = await db.execute(evidence_stmt)
    evidence_list = list(evidence_result.scalars().all())

    # Sync evidence status from VAS for any that are still processing
    for evidence in evidence_list:
        if evidence.status.value == "processing":
            try:
                await evidence_service.sync_evidence_status(evidence)
            except Exception as e:
                logger.warning(
                    "Failed to sync evidence status from VAS",
                    evidence_id=str(evidence.id),
                    error=str(e),
                )

    # Count events for violation
    event_count = await violation_service.count_events_for_violation(violation_id)

    logger.info("Retrieved violation", violation_id=str(violation_id))

    return ViolationDetailResponse(
        id=violation.id,
        **ViolationLabeler.current().type_fields(violation),
        **camera_fields(await db.get(Device, violation.device_id)),
        status=violation.status.value,
        camera_id=violation.device_id,
        camera_name=violation.camera_name,
        confidence=violation.confidence,
        timestamp=violation.timestamp,
        model_id=violation.model_id,
        model_version=violation.model_version,
        bounding_boxes=violation.bounding_boxes,
        reviewed_by=violation.reviewed_by,
        reviewed_at=violation.reviewed_at,
        resolution_notes=violation.resolution_notes,
        dismiss_reason=violation.dismiss_reason,
        evidence=build_evidence_summary(evidence_list),
        event_count=event_count,
        created_at=violation.created_at,
        updated_at=violation.updated_at,
    )


@router.patch(
    "/violations/{violation_id}",
    response_model=ViolationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update violation status",
    description="Update violation status (mark reviewed, dismiss, or resolve).",
    responses={
        200: {"model": ViolationResponse, "description": "Violation updated"},
        400: {"model": ErrorResponse, "description": "Invalid status transition"},
        404: {"model": ErrorResponse, "description": "Violation not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def update_violation_status(
    violation_id: UUID,
    request: ViolationStatusUpdateRequest,
    violation_service: ViolationServiceDep,
    db: DBSession,
) -> ViolationResponse:
    """Update violation status.

    Valid status transitions:
    - open -> reviewed, dismissed
    - reviewed -> dismissed, resolved
    - dismissed -> open (reopen)
    - resolved -> (terminal state, no transitions allowed)

    Args:
        violation_id: Violation UUID
        request: Status update request with new status
        violation_service: Injected ViolationService

    Returns:
        Updated violation

    Raises:
        HTTPException: 404 if violation not found, 400 if invalid transition
    """
    from app.models import ViolationStatus

    # Map status string to enum
    try:
        new_status = ViolationStatus(request.status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_status",
                "message": f"Invalid status: {request.status}. Valid values: open, reviewed, dismissed, resolved",
                "details": {"provided_status": request.status},
            },
        )

    try:
        violation = await violation_service.transition_status(
            violation_id,
            new_status,
            reviewed_by=request.reviewed_by,
            resolution_notes=request.resolution_notes,
            dismiss_reason=(
                request.dismiss_reason.value
                if request.dismiss_reason and new_status == ViolationStatus.DISMISSED
                else None
            ),
        )
    except ViolationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "violation_not_found",
                "message": str(e),
                "details": e.details,
            },
        ) from e
    except ViolationTerminalStateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "terminal_state",
                "message": str(e),
                "details": e.details,
            },
        ) from e
    except ViolationStateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_transition",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    logger.info(
        "Updated violation status",
        violation_id=str(violation_id),
        new_status=new_status.value,
    )

    # Export only after the dismissal is committed: a labelling copy must
    # never exist for a violation that is not actually dismissed.
    if new_status == ViolationStatus.DISMISSED and is_false_alarm(request.dismiss_reason):
        await db.commit()
        await export_dismissed_false_alarms(
            db, [violation], request.dismiss_reason, request.resolution_notes, request.reviewed_by
        )

    return ViolationResponse(
        id=violation.id,
        **ViolationLabeler.current().type_fields(violation),
        **camera_fields(await db.get(Device, violation.device_id)),
        status=violation.status.value,
        camera_id=violation.device_id,
        camera_name=violation.camera_name,
        confidence=violation.confidence,
        timestamp=violation.timestamp,
        model_id=violation.model_id,
        model_version=violation.model_version,
        bounding_boxes=violation.bounding_boxes,
        reviewed_by=violation.reviewed_by,
        reviewed_at=violation.reviewed_at,
        resolution_notes=violation.resolution_notes,
        dismiss_reason=violation.dismiss_reason,
        evidence=None,  # Not needed for status update response
        created_at=violation.created_at,
        updated_at=violation.updated_at,
    )


#: A clip covers [violation - CLIP_BEFORE, violation + CLIP_AFTER].
CLIP_BEFORE_SECONDS = 5
CLIP_AFTER_SECONDS = 5
#: Margin required before another violation's clip is treated as covering
#: this one. Without it a violation 4.99 s away would "reuse" a clip in
#: which it sits on the very last frame.
CLIP_REUSE_MARGIN_SECONDS = 1


async def _stream_id_for(db: DBSession, violation: Violation) -> str | None:
    """The VAS stream a violation's camera is currently streaming on."""
    result = await db.execute(
        select(StreamSession.vas_stream_id)
        .where(
            StreamSession.device_id == violation.device_id,
            StreamSession.vas_stream_id.isnot(None),
        )
        .order_by(StreamSession.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


@router.get(
    "/violations/{violation_id}/clip/availability",
    summary="Can a clip still be cut for this violation?",
    description=(
        "Proxies the VAS coverage check, which scans the same segments the "
        "extractor would use. Not a fixed retention window: recordings are "
        "pruned by disk and by when each camera started, which differ per "
        "camera."
    ),
    responses={404: {"model": ErrorResponse, "description": "Violation not found"}},
)
async def get_clip_availability(
    violation_id: UUID,
    db: DBSession,
    vas_client: VASClientDep,
) -> dict:
    violation = await db.get(Violation, violation_id)
    if violation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Violation not found"
        )
    stream_id = await _stream_id_for(db, violation)
    if not stream_id:
        return {
            "available": False,
            "reason": "this camera has no VAS stream on record",
            "oldest_recording": None,
        }
    try:
        coverage = await vas_client.get_stream_coverage(
            stream_id,
            violation.timestamp,
            CLIP_BEFORE_SECONDS,
            CLIP_AFTER_SECONDS,
        )
    except Exception as e:
        # Unknown is not the same as unavailable: a VAS blip must not make
        # the button permanently claim the footage is gone.
        logger.warning("Clip availability check failed", violation_id=str(violation_id), error=str(e))
        return {"available": False, "reason": "could not reach the recording service", "oldest_recording": None}
    return {
        "available": bool(coverage.get("available")),
        "reason": coverage.get("reason"),
        "oldest_recording": coverage.get("oldest_recording"),
        "newest_recording": coverage.get("newest_recording"),
    }


@router.post(
    "/violations/{violation_id}/clip",
    summary="Request a video clip for this violation",
    status_code=status.HTTP_202_ACCEPTED,
    description=(
        "Idempotent. Returns the existing clip if this violation already has "
        "one, reuses a clip from a nearby violation on the same camera if it "
        "covers this moment, and only then asks VAS to cut a new one."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Violation not found"},
        409: {"model": ErrorResponse, "description": "Recording no longer available"},
    },
)
async def request_violation_clip(
    violation_id: UUID,
    db: DBSession,
    vas_client: VASClientDep,
) -> dict:
    from app.integrations.vas.models import BookmarkCreateRequest

    violation = await db.get(Violation, violation_id)
    if violation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Violation not found"
        )

    # 1. This violation already has a clip, in any state. Returning the
    #    pending one is what makes a double-click harmless.
    existing = (
        await db.execute(
            select(Evidence).where(
                Evidence.violation_id == violation_id,
                Evidence.evidence_type == EvidenceType.BOOKMARK,
            )
        )
    ).scalars().first()
    if existing is not None and existing.status != EvidenceStatus.FAILED:
        return {"status": existing.status.value, "reused": "own", "bookmark_id": existing.vas_bookmark_id}

    # 2. A clip cut for another violation on the same camera, close enough in
    #    time that this moment is inside it. This is the auto-clip cooldown
    #    case: the violation was skipped precisely because a clip had just
    #    been cut, and that clip very likely contains it.
    window = CLIP_BEFORE_SECONDS - CLIP_REUSE_MARGIN_SECONDS
    neighbour = (
        await db.execute(
            select(Evidence)
            .join(Violation, Violation.id == Evidence.violation_id)
            .where(
                Evidence.evidence_type == EvidenceType.BOOKMARK,
                Evidence.status.in_([EvidenceStatus.READY, EvidenceStatus.PROCESSING]),
                Evidence.vas_bookmark_id.isnot(None),
                Violation.device_id == violation.device_id,
                Violation.timestamp
                >= violation.timestamp - timedelta(seconds=window),
                Violation.timestamp
                <= violation.timestamp + timedelta(seconds=window),
            )
            .order_by(Evidence.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if neighbour is not None:
        now = datetime.now(timezone.utc)
        db.add(
            Evidence(
                violation_id=violation_id,
                evidence_type=EvidenceType.BOOKMARK,
                status=neighbour.status,
                vas_bookmark_id=neighbour.vas_bookmark_id,
                bookmark_duration_seconds=neighbour.bookmark_duration_seconds,
                requested_at=now,
                ready_at=neighbour.ready_at,
            )
        )
        await db.commit()
        logger.info(
            "Linked an existing clip to a violation",
            violation_id=str(violation_id), vas_bookmark_id=neighbour.vas_bookmark_id,
        )
        return {"status": neighbour.status.value, "reused": "neighbour", "bookmark_id": neighbour.vas_bookmark_id}

    # 3. Cut a new one — but only if the footage is actually there.
    stream_id = await _stream_id_for(db, violation)
    if not stream_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This camera has no VAS stream on record",
        )
    coverage = await vas_client.get_stream_coverage(
        stream_id, violation.timestamp, CLIP_BEFORE_SECONDS, CLIP_AFTER_SECONDS
    )
    if not coverage.get("available"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=coverage.get("reason") or "Recording no longer available",
        )

    now = datetime.now(timezone.utc)
    evidence = existing or Evidence(
        violation_id=violation_id,
        evidence_type=EvidenceType.BOOKMARK,
        requested_at=now,
    )
    evidence.status = EvidenceStatus.PENDING
    evidence.error_message = None
    evidence.requested_at = now
    evidence.bookmark_duration_seconds = CLIP_BEFORE_SECONDS + CLIP_AFTER_SECONDS
    db.add(evidence)
    await db.commit()
    await db.refresh(evidence)

    try:
        bookmark = await vas_client.create_bookmark(
            stream_id,
            BookmarkCreateRequest(
                # historical, not live: live ignores the timestamps entirely
                # and cuts the most recent segments, which for an old
                # violation would be footage of right now.
                source="historical",
                label=f"Violation: {violation.type.value}",
                event_type=violation.type.value,
                confidence=violation.confidence,
                before_seconds=CLIP_BEFORE_SECONDS,
                after_seconds=CLIP_AFTER_SECONDS,
                center_timestamp=violation.timestamp,
                created_by="ruth-ai-operator-request",
                metadata={"violation_id": str(violation_id), "requested": "manual"},
            ),
        )
    except Exception as e:
        evidence.status = EvidenceStatus.FAILED
        evidence.error_message = str(e)[:1000]
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not request the clip from the recording service",
        ) from e

    evidence.vas_bookmark_id = bookmark.id
    evidence.status = EvidenceStatus.PROCESSING
    await db.commit()
    logger.info(
        "Operator requested a violation clip",
        violation_id=str(violation_id), vas_bookmark_id=bookmark.id,
    )
    return {"status": "processing", "reused": None, "bookmark_id": bookmark.id}


@router.get(
    "/violations/{violation_id}/frame/image",
    summary="Get the inferred frame",
    description=(
        "The exact JPEG the model was given when the violation fired. Unlike "
        "the snapshot, which VAS captures afterwards, this is the image the "
        "bounding boxes were computed on, so an overlay lines up."
    ),
    responses={
        200: {"description": "Image binary data", "content": {"image/jpeg": {}}},
        404: {"model": ErrorResponse, "description": "No frame saved for this violation"},
    },
)
async def get_inferred_frame(
    violation_id: UUID,
    db: DBSession,
) -> FileResponse:
    """Serve the saved inferred frame from disk."""
    settings = get_settings()
    result = await db.execute(
        select(Evidence).where(
            Evidence.violation_id == violation_id,
            Evidence.evidence_type == EvidenceType.FRAME,
        )
    )
    evidence = result.scalars().first()
    if evidence is None or not evidence.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No inferred frame saved for this violation",
        )

    root = Path(settings.evidence_frame_dir).resolve()
    path = (root / evidence.file_path).resolve()
    # The stored path is ours, but resolve and re-check anyway: a path that
    # escapes the evidence root must never be served.
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inferred frame is recorded but missing on disk",
        )
    return FileResponse(path, media_type="image/jpeg")


@router.get(
    "/violations/{violation_id}/frame/thumb",
    summary="Card thumbnail of the inferred frame",
    description=(
        "The inferred frame cropped around the detection (4:3, 320x240) with "
        "the boxes drawn. Generated on first request and cached on disk."
    ),
    responses={
        200: {"description": "JPEG thumbnail", "content": {"image/jpeg": {}}},
        404: {"model": ErrorResponse, "description": "No frame saved for this violation"},
    },
)
async def get_frame_thumbnail(
    violation_id: UUID,
    db: DBSession,
) -> FileResponse:
    settings = get_settings()
    cached = Path(settings.evidence_thumb_dir) / f"{violation_id}.jpg"
    headers = {"Cache-Control": "private, max-age=86400"}
    if cached.is_file():
        return FileResponse(cached, media_type="image/jpeg", headers=headers)

    row = (
        await db.execute(
            select(Evidence.file_path, Violation.bounding_boxes)
            .join(Violation, Violation.id == Evidence.violation_id)
            .where(
                Evidence.violation_id == violation_id,
                Evidence.evidence_type == EvidenceType.FRAME,
                Evidence.status == EvidenceStatus.READY,
            )
        )
    ).first()
    if row is None or not row.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No inferred frame saved for this violation",
        )
    root = Path(settings.evidence_frame_dir).resolve()
    frame = (root / row.file_path).resolve()
    if not frame.is_relative_to(root) or not frame.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inferred frame is recorded but missing on disk",
        )
    try:
        # Pillow work off the event loop.
        await run_in_threadpool(render_thumbnail, frame, row.bounding_boxes, cached)
    except OSError as e:
        logger.warning("Thumbnail render failed", violation_id=str(violation_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thumbnail could not be made from the inferred frame",
        ) from e
    return FileResponse(cached, media_type="image/jpeg", headers=headers)


@router.get(
    "/violations/{violation_id}/snapshot/image",
    summary="Get snapshot image",
    description="Proxy the snapshot image from VAS.",
    responses={
        200: {"description": "Image binary data", "content": {"image/jpeg": {}}},
        404: {"model": ErrorResponse, "description": "Snapshot not found or not ready"},
        502: {"model": ErrorResponse, "description": "VAS error"},
    },
)
async def get_snapshot_image(
    violation_id: UUID,
    evidence_service: EvidenceServiceDep,
    vas_client: VASClientDep,
) -> StreamingResponse:
    """Get the snapshot image for a violation.

    This endpoint proxies the image from VAS to the client.
    The snapshot must be in 'ready' status.

    Args:
        violation_id: Violation UUID
        evidence_service: Injected EvidenceService
        vas_client: Injected VAS client

    Returns:
        Streaming image response

    Raises:
        HTTPException: 404 if snapshot not found or not ready
    """
    # Get snapshot evidence for violation
    evidence_list = await evidence_service.get_evidence_for_violation(
        violation_id,
        evidence_type=EvidenceType.SNAPSHOT,
    )

    if not evidence_list:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "snapshot_not_found",
                "message": "No snapshot evidence found for this violation",
            },
        )

    evidence = evidence_list[0]  # Get most recent

    # Sync status from VAS if still processing
    if evidence.status.value == "processing":
        try:
            await evidence_service.sync_evidence_status(evidence)
        except Exception as e:
            logger.warning(
                "Failed to sync evidence status",
                evidence_id=str(evidence.id),
                error=str(e),
            )

    # Check if ready
    if evidence.status.value != "ready":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "snapshot_not_ready",
                "message": f"Snapshot is not ready (status: {evidence.status.value})",
                "status": evidence.status.value,
            },
        )

    if not evidence.vas_snapshot_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "snapshot_missing_vas_id",
                "message": "Snapshot has no VAS ID",
            },
        )

    logger.info(
        "Proxying VAS snapshot image",
        violation_id=str(violation_id),
        evidence_id=str(evidence.id),
        vas_snapshot_id=evidence.vas_snapshot_id,
    )

    # Stream the image from VAS
    try:
        async def stream_image():
            async with vas_client.download_snapshot_image(evidence.vas_snapshot_id) as response:
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    yield chunk

        return StreamingResponse(
            stream_image(),
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=31536000",  # Cache for 1 year (immutable)
            },
        )
    except Exception as e:
        logger.error(
            "Failed to download snapshot from VAS",
            evidence_id=str(evidence.id),
            vas_snapshot_id=evidence.vas_snapshot_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "vas_error",
                "message": f"Failed to download snapshot from VAS: {e}",
            },
        ) from e


@router.post(
    "/violations/{violation_id}/snapshot",
    response_model=SnapshotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create snapshot",
    description="Capture a snapshot for the violation. Idempotent - returns existing snapshot if already captured.",
    responses={
        201: {"model": SnapshotResponse, "description": "Snapshot created or returned"},
        404: {"model": ErrorResponse, "description": "Violation not found"},
        502: {"model": ErrorResponse, "description": "VAS error"},
        503: {"model": ErrorResponse, "description": "No active stream"},
    },
)
async def create_snapshot(
    violation_id: UUID,
    violation_service: ViolationServiceDep,
    evidence_service: EvidenceServiceDep,
    request: SnapshotCreateRequest | None = None,
) -> SnapshotResponse:
    """Create a snapshot for a violation.

    This endpoint is idempotent. If a snapshot already exists for the violation,
    it returns the existing snapshot information.

    Args:
        violation_id: Violation UUID
        violation_service: Injected ViolationService
        evidence_service: Injected EvidenceService
        request: Optional snapshot configuration

    Returns:
        Snapshot evidence information

    Raises:
        HTTPException: 404 if violation not found, 502 on VAS failure
    """
    # Get violation
    try:
        violation = await violation_service.get_violation_by_id(violation_id)
    except ViolationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "violation_not_found",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    # Create snapshot (idempotent - allow_existing=True)
    try:
        evidence = await evidence_service.create_snapshot(
            violation,
            allow_existing=True,
        )
    except NoActiveStreamError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "no_active_stream",
                "message": "No active stream available for snapshot capture",
                "details": e.details,
            },
        ) from e
    except EvidenceVASError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "vas_error",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    logger.info(
        "Created/retrieved snapshot",
        violation_id=str(violation_id),
        evidence_id=str(evidence.id),
        status=evidence.status.value,
    )

    return SnapshotResponse(
        evidence_id=evidence.id,
        violation_id=evidence.violation_id,
        status=evidence.status.value,
        vas_snapshot_id=evidence.vas_snapshot_id,
        requested_at=evidence.requested_at,
    )


@router.get(
    "/violations/{violation_id}/video",
    response_model=VideoEvidenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get video evidence",
    description="Get or create video evidence (bookmark) for a violation.",
    responses={
        200: {"model": VideoEvidenceResponse, "description": "Video evidence status"},
        404: {"model": ErrorResponse, "description": "Violation not found"},
        502: {"model": ErrorResponse, "description": "VAS error"},
        503: {"model": ErrorResponse, "description": "No active stream"},
    },
)
async def get_video_evidence(
    violation_id: UUID,
    violation_service: ViolationServiceDep,
    evidence_service: EvidenceServiceDep,
) -> VideoEvidenceResponse:
    """Get or create video evidence for a violation.

    Creates a bookmark (video clip) if one doesn't exist.
    Returns the current status of the video evidence.

    Args:
        violation_id: Violation UUID
        violation_service: Injected ViolationService
        evidence_service: Injected EvidenceService

    Returns:
        Video evidence information

    Raises:
        HTTPException: 404 if violation not found, 502 on VAS failure
    """
    # Get violation
    try:
        violation = await violation_service.get_violation_by_id(violation_id)
    except ViolationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "violation_not_found",
                "message": str(e),
                "details": e.details,
            },
        ) from e

    # Try to get existing bookmark evidence
    existing_evidence = await evidence_service.get_evidence_for_violation(
        violation_id,
        evidence_type=EvidenceType.BOOKMARK,
    )

    evidence = None
    if existing_evidence:
        evidence = existing_evidence[0]  # Get most recent
    else:
        # Create bookmark (idempotent)
        try:
            evidence = await evidence_service.create_bookmark(
                violation,
                before_seconds=5,
                after_seconds=10,
                allow_existing=True,
            )
        except NoActiveStreamError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "no_active_stream",
                    "message": "No active stream available for video capture",
                    "details": e.details,
                },
            ) from e
        except EvidenceVASError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "vas_error",
                    "message": str(e),
                    "details": e.details,
                },
            ) from e

    logger.info(
        "Retrieved/created video evidence",
        violation_id=str(violation_id),
        evidence_id=str(evidence.id),
        status=evidence.status.value,
    )

    # Get video URL from VAS if ready
    video_url = None
    if evidence.status.value == "ready" and evidence.vas_bookmark_id:
        try:
            from app.deps import get_vas_client
            vas_client = get_vas_client()
            bookmark = await vas_client.get_bookmark(evidence.vas_bookmark_id)
            video_url = bookmark.video_url
        except Exception as e:
            logger.warning(
                "Failed to get bookmark video URL",
                evidence_id=str(evidence.id),
                error=str(e),
            )

    return VideoEvidenceResponse(
        evidence_id=evidence.id,
        violation_id=evidence.violation_id,
        status=evidence.status.value,
        vas_bookmark_id=evidence.vas_bookmark_id,
        duration_seconds=evidence.bookmark_duration_seconds,
        video_url=video_url,
        requested_at=evidence.requested_at,
        ready_at=evidence.ready_at,
    )
