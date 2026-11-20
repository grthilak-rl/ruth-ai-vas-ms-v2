"""Model notes and the recommended model per violation type.

Notes are dated observations about a model ("HPCL: fires on scaffold
planks"), written by an admin or imported from the evaluation record. They
hang off the model's row, which outlives install, uninstall and Delete, so a
note is never orphaned and never moves to another model (model IDs are never
reused).

A recommendation names, for one violation type such as ``missing_harness``,
the model operators should prefer, and the note that says why. Only an
installed model that raises that type can be recommended. Uninstalling it
keeps the recommendation but makes it inactive (nothing is promoted in its
place); reinstalling the same model makes it active again.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable

from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.model_store import ModelNote, ModelRecommendation, ModelStoreModel
from app.models.project import Project
from app.services.model_store.enabled import StoreModelInfo, enabled_store_models
from app.services.model_store.service import ModelStoreError, get_model
from app.services.violation_labels import BUILTIN_DETAIL_LABELS, FAMILY_LABELS, title_case

logger = get_logger(__name__)

MAX_NOTE_LENGTH = 2000
MAX_SOURCE_LENGTH = 500
#: Author of notes seeded from the evaluation record rather than typed in.
IMPORTED_AUTHOR = "imported"


def violation_type_label(violation_type: str) -> str:
    """"missing_hardhat" -> "Missing hard hat": the shared vocabulary, not one model's."""
    vt = violation_type.strip().lower()
    return BUILTIN_DETAIL_LABELS.get(vt) or FAMILY_LABELS.get(vt) or title_case(vt)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# Notes
# =============================================================================


def _clean_body(body: str) -> str:
    text = (body or "").strip()
    if not text:
        raise ModelStoreError(422, "invalid_note", "A note needs some text")
    if len(text) > MAX_NOTE_LENGTH:
        raise ModelStoreError(
            422, "invalid_note", f"A note can be at most {MAX_NOTE_LENGTH} characters"
        )
    return text


def _clean_source(source: str | None) -> str | None:
    text = (source or "").strip()
    if len(text) > MAX_SOURCE_LENGTH:
        raise ModelStoreError(
            422, "invalid_note", f"The source can be at most {MAX_SOURCE_LENGTH} characters"
        )
    return text or None


async def _check_project(db: AsyncSession, project_id: uuid.UUID | None) -> None:
    if project_id is not None and await db.get(Project, project_id) is None:
        raise ModelStoreError(422, "invalid_note", "That project does not exist")


async def list_notes(db: AsyncSession, model_pk: uuid.UUID) -> list[ModelNote]:
    """A model's notes, newest observation first. Deleted notes are left out."""
    await get_model(db, model_pk)
    stmt = (
        select(ModelNote)
        .where(ModelNote.model_pk == model_pk, ModelNote.deleted_at.is_(None))
        .order_by(ModelNote.observed_on.desc(), ModelNote.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_note(db: AsyncSession, note_id: uuid.UUID) -> ModelNote:
    note = await db.get(ModelNote, note_id)
    if note is None or note.deleted_at is not None:
        raise ModelStoreError(404, "note_not_found", "note not found")
    return note


async def create_note(
    db: AsyncSession,
    model_pk: uuid.UUID,
    *,
    body: str,
    observed_on: date,
    project_id: uuid.UUID | None,
    source: str | None,
    internal: bool,
    actor: str,
) -> ModelNote:
    await get_model(db, model_pk)
    await _check_project(db, project_id)
    note = ModelNote(
        model_pk=model_pk,
        observed_on=observed_on,
        body=_clean_body(body),
        project_id=project_id,
        source=_clean_source(source),
        internal=bool(internal),
        created_by=actor,
    )
    db.add(note)
    await db.flush()
    logger.info("Model note added", model_pk=str(model_pk), note_id=str(note.id), actor=actor)
    return note


_UNSET = object()


async def update_note(
    db: AsyncSession,
    note_id: uuid.UUID,
    *,
    actor: str,
    body: str | None = None,
    observed_on: date | None = None,
    project_id=_UNSET,
    source=_UNSET,
    internal: bool | None = None,
) -> ModelNote:
    note = await get_note(db, note_id)
    if body is not None:
        note.body = _clean_body(body)
    if observed_on is not None:
        note.observed_on = observed_on
    if project_id is not _UNSET:
        await _check_project(db, project_id)
        note.project_id = project_id
    if source is not _UNSET:
        note.source = _clean_source(source)
    if internal is not None:
        note.internal = bool(internal)
    note.edited_by = actor
    note.updated_at = _now()
    await db.flush()
    logger.info("Model note edited", note_id=str(note_id), actor=actor)
    return note


async def delete_note(db: AsyncSession, note_id: uuid.UUID, actor: str) -> None:
    """Soft-delete. Refused while the note is an active recommendation's reason."""
    note = await get_note(db, note_id)
    in_use = (
        await db.execute(
            select(ModelRecommendation.violation_type).where(
                ModelRecommendation.note_id == note_id,
                ModelRecommendation.cleared_at.is_(None),
            )
        )
    ).scalars().all()
    if in_use:
        types = ", ".join(violation_type_label(t) for t in in_use)
        raise ModelStoreError(
            409,
            "note_in_use",
            f"This note is the reason for the recommendation for {types}. "
            "Change or clear that recommendation first.",
        )
    note.deleted_at = _now()
    note.deleted_by = actor
    await db.flush()
    logger.info("Model note deleted", note_id=str(note_id), actor=actor)


async def project_names(db: AsyncSession, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (await db.execute(select(Project.id, Project.name).where(Project.id.in_(wanted)))).all()
    return {pid: name for pid, name in rows}


@dataclass(frozen=True)
class LatestNote:
    body: str
    observed_on: date
    project_name: str | None


async def latest_public_notes(db: AsyncSession, model_ids: Iterable[str]) -> dict[str, LatestNote]:
    """The newest non-internal note per model_id (what the picker shows)."""
    ids = list(model_ids)
    if not ids:
        return {}
    ranked = (
        select(
            ModelStoreModel.model_id.label("model_id"),
            ModelNote.body,
            ModelNote.observed_on,
            ModelNote.project_id,
            func.row_number()
            .over(
                partition_by=ModelNote.model_pk,
                order_by=(ModelNote.observed_on.desc(), ModelNote.created_at.desc()),
            )
            .label("rank"),
        )
        .join(ModelStoreModel, ModelStoreModel.id == ModelNote.model_pk)
        .where(
            ModelStoreModel.model_id.in_(ids),
            ModelNote.deleted_at.is_(None),
            ModelNote.internal.is_(False),
        )
        .subquery()
    )
    rows = (await db.execute(select(ranked).where(ranked.c.rank == 1))).all()
    names = await project_names(db, (r.project_id for r in rows))
    return {
        r.model_id: LatestNote(r.body, r.observed_on, names.get(r.project_id)) for r in rows
    }


# =============================================================================
# Recommendations
# =============================================================================


@dataclass(frozen=True)
class Recommendation:
    violation_type: str
    label: str
    model_pk: uuid.UUID
    model_id: str
    display_name: str
    #: False once the model is uninstalled: kept, but not shown as recommended
    active: bool
    note: ModelNote
    set_by: str
    set_at: datetime


def _installed() -> dict[str, StoreModelInfo]:
    try:
        return enabled_store_models()
    except Exception:  # noqa: BLE001 - unreadable store: nothing is installed
        return {}


async def list_recommendations(db: AsyncSession) -> list[Recommendation]:
    """Every recommendation in force (not cleared), by violation type."""
    rows = (
        await db.execute(
            select(ModelRecommendation, ModelStoreModel, ModelNote)
            .join(ModelStoreModel, ModelStoreModel.id == ModelRecommendation.model_pk)
            .join(ModelNote, ModelNote.id == ModelRecommendation.note_id)
            .where(ModelRecommendation.cleared_at.is_(None))
            .order_by(ModelRecommendation.violation_type)
        )
    ).all()
    installed = _installed()
    out = []
    for rec, model, note in rows:
        info = installed.get(model.model_id)
        out.append(
            Recommendation(
                violation_type=rec.violation_type,
                label=violation_type_label(rec.violation_type),
                model_pk=model.id,
                model_id=model.model_id,
                display_name=info.display_name if info else model.display_name,
                active=info is not None and rec.violation_type in info.violation_types,
                note=note,
                set_by=rec.set_by,
                set_at=rec.set_at,
            )
        )
    return out


async def active_recommendations(db: AsyncSession) -> dict[str, list[str]]:
    """model_id -> the violation types it is the active recommendation for."""
    out: dict[str, list[str]] = {}
    for rec in await list_recommendations(db):
        if rec.active:
            out.setdefault(rec.model_id, []).append(rec.violation_type)
    return out


async def set_recommendation(
    db: AsyncSession,
    violation_type: str,
    *,
    model_pk: uuid.UUID,
    note_id: uuid.UUID,
    actor: str,
) -> None:
    """Make ``model_pk`` the recommended model for ``violation_type``.

    It must be installed and raise that type; the reason must be one of its
    own notes. A previous recommendation for the type is cleared (kept as
    history).
    """
    vt = violation_type.strip().lower()
    model = await get_model(db, model_pk)
    info = _installed().get(model.model_id)
    if info is None:
        raise ModelStoreError(
            409, "model_not_installed", f"'{model.model_id}' is not installed, so it cannot be recommended"
        )
    if vt not in info.violation_types:
        raises = ", ".join(info.violation_types) or "nothing"
        raise ModelStoreError(
            422,
            "violation_type_not_raised",
            f"'{model.model_id}' does not raise {vt} (it raises {raises})",
        )
    note = await get_note(db, note_id)
    if note.model_pk != model.id:
        raise ModelStoreError(422, "note_not_for_model", "The reason must be one of this model's notes")

    now = _now()
    await db.execute(
        update(ModelRecommendation)
        .where(and_(ModelRecommendation.violation_type == vt, ModelRecommendation.cleared_at.is_(None)))
        .values(cleared_at=now, cleared_by=actor)
    )
    db.add(
        ModelRecommendation(
            violation_type=vt, model_pk=model.id, note_id=note.id, set_by=actor, set_at=now
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        # Another admin set one in between; theirs stands.
        raise ModelStoreError(409, "recommendation_changed", "The recommendation changed meanwhile; reload and retry")
    logger.info("Model recommended", violation_type=vt, model_id=model.model_id, actor=actor)


async def clear_recommendation(db: AsyncSession, violation_type: str, actor: str) -> None:
    vt = violation_type.strip().lower()
    result = await db.execute(
        update(ModelRecommendation)
        .where(and_(ModelRecommendation.violation_type == vt, ModelRecommendation.cleared_at.is_(None)))
        .values(cleared_at=_now(), cleared_by=actor)
    )
    if result.rowcount == 0:
        raise ModelStoreError(404, "recommendation_not_found", f"No model is recommended for {vt}")
    await db.flush()
    logger.info("Model recommendation cleared", violation_type=vt, actor=actor)
