"""Seed model notes and the first recommendations (2026-11-20).

The notes are the evaluation record so far: the HPCL handovers for the AI
engineer (/mnt/storage/ruth-models/eval/), the manifests' trial notes, and
live violation counts. Saved as author "imported", dated as observed, with
the source shown. Reviewed and approved before saving.

Re-runnable: a note already imported for the model (same text) is skipped,
and a violation type that already has a recommendation is left alone, so an
admin's later choice is never overwritten.

    python -m app.services.model_store.seed_notes            # plan only
    python -m app.services.model_store.seed_notes --apply    # write
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_store import ModelNote, ModelRecommendation, ModelStoreModel
from app.models.project import Project
from app.services.model_store import notes as notes_service
from app.services.model_store.service import ModelStoreError

EVAL = "/mnt/storage/ruth-models/eval"
HPCL = "HPCL"
POST_HPCL = "Post HPCL Dev"


@dataclass(frozen=True)
class SeedNote:
    model_id: str
    observed_on: date
    project: str | None
    body: str
    source: str
    #: violation type this note is the recommendation reason for, if any
    recommend_for: str | None = None


SEEDS: tuple[SeedNote, ...] = (
    SeedNote(
        "gloves", date(2026, 10, 17), HPCL,
        "Close to inert: no violations in 19 h live; on 32 frames, 22 had no box at all and the "
        "best \"no-gloves\" score was 0.286. Bare hands are visible in those frames, so the "
        "weights are at fault, not the settings. Needs retraining. It took a third of the "
        "inference budget. No violations recorded since.",
        f"{EVAL}/2026-10-17/README.md; database",
    ),
    SeedNote(
        "gloves_2", date(2026, 10, 19), HPCL,
        "Offline on 32 frames: best \"no-gloves\" score 0.727, 8 boxes ≥0.5, 1 ≥0.7 (old gloves: "
        "0.286). RT-DETR: about 214 boxes per frame at the low diagnostic threshold, so its box "
        "counts aren't comparable with YOLO models.",
        f"{EVAL}/2026-10-19/gloves2-compare.json; manifest",
    ),
    SeedNote(
        "gloves_2", date(2026, 11, 17), HPCL,
        "By far the noisiest model: 27,914 violations on 13 cameras, median confidence 0.74. One "
        "dismissal note: a scaffold plank boxed as a bare hand. Since: 3,385 on 3 cameras.",
        "database",
    ),
    SeedNote(
        "goggles", date(2026, 10, 18), HPCL,
        "Doesn't transfer to HPCL images: best score 0.276, and that was the compliant class; no "
        "\"no-goggles\" box at any confidence. Validation mAP50 0.898 did not predict this (\"the "
        "metric trap\"). Installed anyway at the operator's decision. 1 violation ever.",
        f"{EVAL}/2026-10-18/README.md; database",
    ),
    SeedNote(
        "no_goggles", date(2026, 10, 19), HPCL,
        "Single-class retrain at 640. Best score 0.533 on the 18 Oct frames and 0.182 on 19 Oct; "
        "0.182 on the confirmed bare-face frame. No violations recorded.",
        f"{EVAL}/2026-10-19/goggles2-compare.json; manifest",
    ),
    SeedNote(
        "goggles_2", date(2026, 10, 20), HPCL,
        "Mid-training checkpoint (epoch 4 of 50). Never reached 0.5 offline; 0.103 on the "
        "bare-face frame. Live: 123 violations on 4 cameras, 20 Oct–4 Nov.",
        "manifest; database",
    ),
    SeedNote(
        "goggles_3", date(2026, 10, 24), HPCL,
        "Finished export of the goggles_2 run: validation mAP50 0.772. Offline best 0.522, and "
        "0.386 on the bare-face frame, the best of the goggles models. Live: 1,781 violations on "
        "9 cameras; 8 since.",
        "manifest; database",
        recommend_for="missing_goggles",
    ),
    SeedNote(
        "hard_hat", date(2026, 10, 17), HPCL,
        "Inconclusive: 0 fires on 32 frames of mostly helmeted workers. \"No-hardhat\" peaked at "
        "0.166; \"hardhat\" reached 0.756. Built on the weakest backbone (yolov8n). Needs a "
        "labelled set with bare heads. Live: 1,247 violations on 12 cameras, median 0.77.",
        f"{EVAL}/2026-10-17/README.md; database",
        recommend_for="missing_hardhat",
    ),
    SeedNote(
        "safety_vest", date(2026, 10, 17), HPCL,
        "The model that behaved: fired on 7 of 32 frames (best 0.779), consistent with its live "
        "count at the time. The only one trained on a \"combined v2\" dataset. Live: 1,053 "
        "violations on 10 cameras; none after 19 Oct.",
        f"{EVAL}/2026-10-17/README.md; database",
        recommend_for="missing_vest",
    ),
    SeedNote(
        "harness", date(2026, 10, 18), HPCL,
        "Meant for confined-space cameras. Weak validation scores (mAP50 0.625, recall 0.504), "
        "and those cameras are often infrared. No violations recorded.",
        "manifest; database",
    ),
    SeedNote(
        "harness_2", date(2026, 10, 24), HPCL,
        "Mid-training checkpoint (epoch 12). Offline on 906 frames from camera 75130: scored ≥0.7 "
        "on 25 frames from a fixed box on an empty vessel's edge, so it raises false critical "
        "alerts. Live: 2,333 violations on 6 cameras, 24 Oct–4 Nov.",
        "manifest; database",
    ),
    SeedNote(
        "harness_3", date(2026, 11, 20), POST_HPCL,
        "Installed today, not yet judged: validation mAP50 0.895. On 38 PPE frames (not "
        "confined-space): 1 violation at 0.7, best \"no harness\" 0.754.",
        "manifest; today's probe",
    ),
    SeedNote(
        "fall_pose", date(2026, 11, 19), HPCL,
        "Over-fires on small or distant people and person-shaped objects (BL-1). Person "
        "threshold raised to 0.45. 36 HPCL false-fire frames, including wall-mounted CCTV cameras "
        "taken for people. Live since: 367 on 2 cameras.",
        "manifest; docs/eval/2026-11-19-fall-pose-flagged-frames.md; BACKLOG BL-1",
    ),
    SeedNote(
        "geofence", date(2026, 11, 19), POST_HPCL,
        "Same weights as the retired built-in; the zone point is now the feet. Walk-in test: 28 "
        "frames, 2 correct intrusions. Live: 39 on 1 camera.",
        "manifest; GEOFENCE_MIGRATION.md; 19 Nov walk-in",
    ),
)


async def seed(db: AsyncSession, apply: bool) -> list[str]:
    """Add the seed notes and recommendations; return what was (or would be) done."""
    report: list[str] = []
    models = {
        m.model_id: m
        for m in (
            await db.execute(select(ModelStoreModel).where(ModelStoreModel.state != "deleted"))
        ).scalars()
    }
    projects = {p.name: p.id for p in (await db.execute(select(Project))).scalars()}

    reasons: dict[str, ModelNote] = {}
    for s in SEEDS:
        model = models.get(s.model_id)
        if model is None:
            report.append(f"skip  {s.model_id}: no such model")
            continue
        if s.project and s.project not in projects:
            report.append(f"skip  {s.model_id}: no project named {s.project!r}")
            continue
        existing = (
            await db.execute(
                select(ModelNote).where(
                    ModelNote.model_pk == model.id,
                    ModelNote.created_by == notes_service.IMPORTED_AUTHOR,
                    ModelNote.body == s.body,
                    ModelNote.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            report.append(f"have  {s.model_id} {s.observed_on}")
            note = existing
        elif apply:
            note = await notes_service.create_note(
                db,
                model.id,
                body=s.body,
                observed_on=s.observed_on,
                project_id=projects.get(s.project) if s.project else None,
                source=s.source,
                internal=False,
                actor=notes_service.IMPORTED_AUTHOR,
            )
            report.append(f"add   {s.model_id} {s.observed_on}")
        else:
            note = None
            report.append(f"would add {s.model_id} {s.observed_on}")
        if s.recommend_for:
            reasons[s.recommend_for] = note

    for s in SEEDS:
        if not s.recommend_for:
            continue
        active = (
            await db.execute(
                select(ModelRecommendation).where(
                    ModelRecommendation.violation_type == s.recommend_for,
                    ModelRecommendation.cleared_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if active is not None:
            report.append(f"have  recommendation for {s.recommend_for} (left as is)")
            continue
        note = reasons.get(s.recommend_for)
        if not apply or note is None:
            report.append(f"would recommend {s.model_id} for {s.recommend_for}")
            continue
        try:
            await notes_service.set_recommendation(
                db,
                s.recommend_for,
                model_pk=models[s.model_id].id,
                note_id=note.id,
                actor=notes_service.IMPORTED_AUTHOR,
            )
            report.append(f"recommend {s.model_id} for {s.recommend_for}")
        except ModelStoreError as exc:
            report.append(f"FAIL  recommend {s.model_id} for {s.recommend_for}: {exc.message}")
    return report


async def _main(apply: bool) -> int:
    from app.core.database import close_database, get_session_factory, init_database

    await init_database()
    try:
        async with get_session_factory()() as db:
            report = await seed(db, apply)
            if apply:
                await db.commit()
            else:
                await db.rollback()
    finally:
        await close_database()
    print("\n".join(report))
    print("applied" if apply else "plan only: nothing written (use --apply)")
    return 1 if any(line.startswith("FAIL") for line in report) else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the notes and recommendations")
    raise SystemExit(asyncio.run(_main(parser.parse_args().apply)))
