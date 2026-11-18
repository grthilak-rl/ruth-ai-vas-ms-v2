"""Unit tests for the parts of the project service that need no database:
the slug (URL and backup filename) and the pre-start backup preconditions.

The archive flow these tests used to cover is retired (projects are tags);
Start's rules are in tests/unit/test_project_lifecycle.py and the tagging
and scoping in tests/projects/.
"""

import pytest

from app.core.config import Settings
from app.services.project_service import (
    ProjectService,
    slugify,
)


# -----------------------------------------------------------------------------
# slugify
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Coke Drum Campaign 2026-Q4", "coke-drum-campaign-2026-q4"),
        ("  leading and trailing  ", "leading-and-trailing"),
        ("Multiple   spaces", "multiple-spaces"),
        ("Slashes/and:colons", "slashes-and-colons"),
        ("Trailing punctuation!!!", "trailing-punctuation"),
        ("under_scores", "under-scores"),
        ("MiXeD CaSe", "mixed-case"),
        # Non-ASCII is dropped, not transliterated to something surprising.
        ("Café Zone 3", "cafe-zone-3"),
        # A name with nothing usable still produces a filename.
        ("!!!", "project"),
        ("日本", "project"),
    ],
)
def test_slugify(name: str, expected: str) -> None:
    assert slugify(name) == expected


def test_slugify_never_yields_path_traversal() -> None:
    """The slug lands in a filename; it must not be able to escape the dir."""
    for hostile in ("../../etc/passwd", "..", "./.", "a/../../b"):
        slug = slugify(hostile)
        assert "/" not in slug
        assert ".." not in slug
        assert slug


def test_slugify_collisions_are_not_silently_resolved() -> None:
    """Two visually distinct names can slugify the same.

    Documented behaviour: the service reports ProjectNameInUseError rather
    than appending a suffix, because the right fix is a human renaming one
    of them.
    """
    assert slugify("Q4 2026") == slugify("Q4-2026") == "q4-2026"


# -----------------------------------------------------------------------------
# Backup preconditions
# -----------------------------------------------------------------------------


def test_backup_problem_reports_missing_directory(tmp_path) -> None:
    # pg_dump pinned to something that exists, so the directory is the only
    # remaining problem — _backup_problem reports the first one it finds.
    settings = Settings(
        project_backup_dir=str(tmp_path / "does-not-exist"),
        project_pg_dump_path="sh",
    )
    service = ProjectService(db=None, settings=settings)  # type: ignore[arg-type]
    problem = service._backup_problem()
    assert problem is not None
    assert "does not exist" in problem


def test_backup_problem_reports_unwritable_directory(tmp_path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    try:
        settings = Settings(
            project_backup_dir=str(locked), project_pg_dump_path="sh"
        )
        service = ProjectService(db=None, settings=settings)  # type: ignore[arg-type]
        problem = service._backup_problem()
        # Running as root defeats the permission bit; skip rather than
        # assert something false about the environment.
        if problem is None:
            pytest.skip("running as root; directory permissions not enforced")
        assert "not writable" in problem
    finally:
        locked.chmod(0o700)


def test_backup_problem_reports_missing_pg_dump(tmp_path) -> None:
    settings = Settings(
        project_backup_dir=str(tmp_path),
        project_pg_dump_path="definitely-not-a-real-binary-xyz",
    )
    service = ProjectService(db=None, settings=settings)  # type: ignore[arg-type]
    problem = service._backup_problem()
    assert problem is not None
    assert "not found on PATH" in problem


def test_backup_problem_none_when_usable(tmp_path) -> None:
    """A writable directory and a findable binary means no problem."""
    settings = Settings(
        project_backup_dir=str(tmp_path),
        # Any executable on PATH proves the lookup, without needing Postgres
        # client tools installed in the unit-test environment.
        project_pg_dump_path="sh",
    )
    service = ProjectService(db=None, settings=settings)  # type: ignore[arg-type]
    assert service._backup_problem() is None


# -----------------------------------------------------------------------------
# Keep the last N pre-start dumps; refuse a backup dir that is not a mount
# -----------------------------------------------------------------------------


def _dumps_service(tmp_path, keep=5):
    settings = Settings(project_backup_dir=str(tmp_path), project_pg_dump_path="sh", project_backup_keep=keep)
    return ProjectService(db=None, settings=settings)  # type: ignore[arg-type]


def _touch(path, age_s):
    import os
    import time

    path.write_bytes(b"x")
    t = time.time() - age_s
    os.utime(path, (t, t))
    return path


def test_prune_keeps_the_newest_five_project_dumps(tmp_path) -> None:
    dumps = [_touch(tmp_path / f"project-p{i}-2026.dump", age_s=1000 - i) for i in range(8)]
    newest = dumps[-1]
    others = [
        _touch(tmp_path / "pre-deploy-2026.dump", 5000),
        _touch(tmp_path / "ruth_ai_pre-deploy.dump", 5000),
        _touch(tmp_path / "project-notes.txt", 5000),
    ]
    removed = _dumps_service(tmp_path).prune_backups(keep=newest)
    assert sorted(p.name for p in removed) == sorted(p.name for p in dumps[:3])
    assert sorted(p.name for p in tmp_path.glob("project-*.dump")) == sorted(p.name for p in dumps[3:])
    assert all(p.exists() for p in others), "pruning touched a file it does not own"


def test_prune_never_deletes_the_dump_just_written(tmp_path) -> None:
    # Clock skew: the new dump looks oldest. It still survives.
    just_written = _touch(tmp_path / "project-new-2026.dump", age_s=99999)
    for i in range(5):
        _touch(tmp_path / f"project-p{i}.dump", age_s=10 + i)
    _dumps_service(tmp_path).prune_backups(keep=just_written)
    assert just_written.exists()


def test_prune_with_fewer_than_keep_deletes_nothing(tmp_path) -> None:
    for i in range(2):
        _touch(tmp_path / f"project-p{i}.dump", age_s=i)
    assert _dumps_service(tmp_path).prune_backups() == []


def test_backup_dir_must_be_a_mount_when_required(tmp_path, monkeypatch) -> None:
    import app.services.project_service as ps

    settings = Settings(project_backup_dir=str(tmp_path), project_pg_dump_path="sh",
                        project_backup_require_mount=True)
    service = ProjectService(db=None, settings=settings)  # type: ignore[arg-type]
    monkeypatch.setattr(ps.os.path, "ismount", lambda p: str(p) == "/")
    assert "not a mounted volume" in service.backup_problem()
    monkeypatch.setattr(ps.os.path, "ismount", lambda p: str(p) in ("/", str(tmp_path.resolve())))
    assert service.backup_problem() is None
