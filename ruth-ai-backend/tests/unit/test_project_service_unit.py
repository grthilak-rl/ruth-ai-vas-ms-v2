"""Unit tests for the parts of project archiving that need no database.

The archive itself is Postgres-specific (INSERT ... SELECT with enum casts,
advisory locks, temp tables) and is covered by tests/projects/, which needs a
throwaway Postgres. What is tested here is the logic that decides *whether*
to archive, and the naming that ends up in a filename — both of which are
pure and both of which can refuse the operation.
"""

import uuid

import pytest

from app.core.config import Settings
from app.services.project_service import (
    MAX_UNBATCHED_ROWS,
    ConfirmationMismatchError,
    LiveCamera,
    Preflight,
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
# Preflight blocker logic
# -----------------------------------------------------------------------------


def _camera(name: str = "CAM-1", state: str = "live") -> LiveCamera:
    return LiveCamera(
        device_id=uuid.uuid4(),
        camera_name=name,
        session_id=uuid.uuid4(),
        state=state,
    )


def test_preflight_can_proceed_when_no_blockers() -> None:
    pre = Preflight(current_project=None, row_counts={}, total_rows=0)
    assert pre.can_proceed is True


def test_preflight_blocked_by_any_blocker() -> None:
    pre = Preflight(
        current_project=None,
        row_counts={"violations": 1},
        total_rows=1,
        blockers=["inference_active"],
    )
    assert pre.can_proceed is False


def test_live_camera_as_dict_is_json_safe() -> None:
    """The API puts this straight into a 409 body, so no UUID objects."""
    payload = _camera().as_dict()
    assert set(payload) == {"device_id", "camera_name", "session_id", "state"}
    assert all(isinstance(v, str) for v in payload.values())


# -----------------------------------------------------------------------------
# Confirmation
# -----------------------------------------------------------------------------


async def test_start_rejects_mismatched_confirmation() -> None:
    """The typed confirmation is checked before anything touches the DB.

    A None session is deliberate: if this check ever stopped coming first,
    the test would fail with AttributeError instead of passing.
    """
    service = ProjectService(db=None, settings=Settings())  # type: ignore[arg-type]
    with pytest.raises(ConfirmationMismatchError):
        await service.start_new_project(
            name="Campaign A",
            confirm_name="Campaign B",
            started_by="admin",
            backup_path=None,
        )


async def test_start_confirmation_is_case_and_space_sensitive() -> None:
    service = ProjectService(db=None, settings=Settings())  # type: ignore[arg-type]
    for confirm in ("campaign a", "Campaign  A", "Campaign A "):
        with pytest.raises(ConfirmationMismatchError):
            await service.start_new_project(
                name="Campaign A",
                confirm_name=confirm,
                started_by="admin",
                backup_path=None,
            )


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
# Guard rails
# -----------------------------------------------------------------------------


def test_row_ceiling_is_far_above_observed_volume() -> None:
    """The ceiling is a tripwire for unexpected growth, not a daily obstacle.

    Measured 2026-10-16: 247,287 rows. If someone lowers this below the
    observed working set, every archive starts refusing.
    """
    assert MAX_UNBATCHED_ROWS > 1_000_000
