"""Capturing VAS media paths into evidence_archive.

Ruth stores no media paths — Evidence holds a VAS id and media is served by
proxying to VAS. VAS deletes the file and its row together at retention,
after which the id is dangling and nothing records where the file was. The
archive is the last moment that fact is knowable, so it is captured then.

`vas_paths_resolved` has to distinguish three outcomes, and all three are
exercised here:

    VAS answered with a path   -> path stored, resolved = true
    VAS has no such id         -> path NULL,   resolved = false
    VAS unreachable / no client -> path NULL,  resolved = false

The second and third look identical in the data, which is why the archive
also logs the counts: "VAS says it is gone" and "we could not ask" are
different operational situations.
"""

import os

import pytest
from sqlalchemy import select, text

from app.core.config import Settings
from app.integrations.vas import VASError
from app.models import EvidenceArchive
from app.services.project_service import ProjectService

pytestmark = pytest.mark.skipif(
    not os.environ.get("PROJECT_TEST_DATABASE_URL"),
    reason="PROJECT_TEST_DATABASE_URL not set",
)


class FakeVAS:
    """Minimal stand-in for the two bulk-path methods.

    `known` maps snapshot id -> file_path. Anything absent is reported
    missing, exactly as the real endpoint does (a missing key, not an error).
    """

    def __init__(self, known: dict[str, str], *, raise_on_call: bool = False) -> None:
        self.known = known
        self.raise_on_call = raise_on_call
        self.snapshot_calls: list[list[str]] = []

    async def get_snapshot_paths(self, ids):
        self.snapshot_calls.append(list(ids))
        if self.raise_on_call:
            raise VASError("VAS unreachable")
        return {
            sid: {"file_path": self.known[sid], "file_size": 4096}
            for sid in ids
            if sid in self.known
        }

    async def get_bookmark_paths(self, _ids):
        # The seeder creates snapshot evidence only; this exists so the
        # service's second lookup has something to call.
        if self.raise_on_call:
            raise VASError("VAS unreachable")
        return {}


def _service(db, backup_dir, vas) -> ProjectService:
    return ProjectService(
        db,
        vas_client=vas,
        settings=Settings(
            project_backup_dir=str(backup_dir), project_pg_dump_path="sh"
        ),
    )


async def _archived(db) -> dict[str, tuple[str | None, bool]]:
    """vas_snapshot_id -> (captured path, resolved flag)."""
    rows = (
        await db.execute(
            select(
                EvidenceArchive.vas_snapshot_id,
                EvidenceArchive.vas_file_path,
                EvidenceArchive.vas_paths_resolved,
            )
        )
    ).all()
    return {sid: (path, resolved) for sid, path, resolved in rows}


async def test_known_paths_are_captured(db, seeder, backup_dir) -> None:
    """The seeder makes evidence with ids snap-1, snap-2 (and one with none)."""
    await seeder.seed(violations=3)
    vas = FakeVAS({"snap-1": "/snapshots/CAM/2026-10-16/a.jpg"})

    await _service(db, backup_dir, vas).start_new_project(
        name="Paths", confirm_name="Paths", started_by="tester", backup_path=None
    )
    await db.commit()

    archived = await _archived(db)
    # Resolved: VAS knew this one.
    assert archived["snap-1"] == ("/snapshots/CAM/2026-10-16/a.jpg", True)
    # VAS did not know snap-2 — reaped by retention.
    assert archived["snap-2"] == (None, False)
    # And the evidence row that never had a VAS id at all.
    assert archived[None] == (None, False)


async def test_file_size_is_captured(db, seeder, backup_dir) -> None:
    await seeder.seed(violations=2)
    vas = FakeVAS({"snap-1": "/snapshots/CAM/x.jpg"})

    await _service(db, backup_dir, vas).start_new_project(
        name="Sizes", confirm_name="Sizes", started_by="tester", backup_path=None
    )
    await db.commit()

    size = (
        await db.execute(
            text(
                "SELECT vas_file_size FROM evidence_archive "
                "WHERE vas_snapshot_id = 'snap-1'"
            )
        )
    ).scalar()
    assert size == 4096


async def test_vas_failure_does_not_block_the_archive(db, seeder, backup_dir) -> None:
    """VAS being down must never stop a project from being archived.

    The paths are a nice-to-have; the archive is the operation. Everything
    lands with resolved = false, which is a truthful record of "we could not
    find out".
    """
    await seeder.seed(violations=3)
    vas = FakeVAS({}, raise_on_call=True)

    result = await _service(db, backup_dir, vas).start_new_project(
        name="VAS Down",
        confirm_name="VAS Down",
        started_by="tester",
        backup_path=None,
    )
    await db.commit()

    assert result.counts["violations"] == 3
    assert result.vas_paths_resolved == 0
    archived = await _archived(db)
    assert all(resolved is False for _, resolved in archived.values())
    assert all(path is None for path, _ in archived.values())


async def test_no_vas_client_is_tolerated(db, seeder, backup_dir) -> None:
    """The CLI constructs the service without a VAS client."""
    await seeder.seed(violations=2)

    result = await _service(db, backup_dir, None).start_new_project(
        name="No Client",
        confirm_name="No Client",
        started_by="cli",
        backup_path=None,
    )
    await db.commit()

    assert result.vas_paths_resolved == 0
    assert result.counts["violations"] == 2


async def test_only_evidence_with_media_ids_is_looked_up(db, seeder, backup_dir) -> None:
    """Don't ask VAS about rows that have no id — 117k pointless ids."""
    await seeder.seed(violations=3)
    vas = FakeVAS({})

    await _service(db, backup_dir, vas).start_new_project(
        name="Lookup Scope",
        confirm_name="Lookup Scope",
        started_by="tester",
        backup_path=None,
    )
    await db.commit()

    # Seeder makes 3 evidence rows; index 0 has no snapshot id.
    assert len(vas.snapshot_calls) == 1
    assert sorted(vas.snapshot_calls[0]) == ["snap-1", "snap-2"]


async def test_resolved_counts_are_reported(db, seeder, backup_dir) -> None:
    """The result carries both numbers so the UI can be honest about them."""
    await seeder.seed(violations=3)
    vas = FakeVAS({"snap-1": "/snapshots/a.jpg"})

    result = await _service(db, backup_dir, vas).start_new_project(
        name="Counted", confirm_name="Counted", started_by="tester", backup_path=None
    )
    await db.commit()

    # 2 evidence rows carry an id; VAS knew 1 of them.
    assert result.vas_paths_resolved == 1
    assert result.vas_paths_missing == 1
