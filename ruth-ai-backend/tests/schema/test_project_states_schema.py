"""The migrated database accepts every project state (and only one current).

The lifecycle unit tests use fake sessions, which is why the first live Stop
met ck_projects_state instead of a test. This runs against a real Postgres
that `alembic upgrade head` has migrated, given in SCHEMA_TEST_DATABASE_URL
(an asyncpg URL to a throwaway database). Skipped without it. Everything
happens inside one transaction that is rolled back.
"""

import os
import uuid

import pytest

URL = os.environ.get("SCHEMA_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="SCHEMA_TEST_DATABASE_URL not set")


async def _run(check):
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(URL)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                await check(conn)
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()


async def _insert(conn, state):
    from sqlalchemy import text

    await conn.execute(
        text(
            "INSERT INTO projects (id, name, slug, state, started_at, started_by, created_at, updated_at) "
            "VALUES (:id, :name, :slug, :state, now(), 'schema-test', now(), now())"
        ),
        {"id": uuid.uuid4(), "name": f"t-{state}", "slug": f"t-{state}-{uuid.uuid4().hex[:8]}", "state": state},
    )


async def test_every_state_is_accepted():
    from sqlalchemy import text

    from app.models.project import PROJECT_STATES

    async def check(conn):
        # Free the one-current slot so each current state can be tried in turn.
        await conn.execute(text("UPDATE projects SET state = 'archived'"))
        for state in PROJECT_STATES:
            nested = await conn.begin_nested()
            await _insert(conn, state)
            await nested.rollback()

    await _run(check)


async def test_unknown_state_is_rejected():
    from sqlalchemy.exc import IntegrityError

    async def check(conn):
        with pytest.raises(IntegrityError):
            await _insert(conn, "paused")

    await _run(check)


@pytest.mark.parametrize("second", ["active", "stopping", "stopped", "resuming"])
async def test_only_one_current_project(second):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    async def check(conn):
        await conn.execute(text("UPDATE projects SET state = 'archived'"))
        await _insert(conn, "stopped")
        with pytest.raises(IntegrityError):
            await _insert(conn, second)

    await _run(check)


async def test_ended_projects_are_past_not_current():
    """projects_as_tags: an ended project frees the slot, so the next can start."""
    from sqlalchemy import text

    async def check(conn):
        await conn.execute(text("UPDATE projects SET state = 'ended'"))
        await _insert(conn, "ended")
        await _insert(conn, "ended")
        await _insert(conn, "active")  # the next project, after End

    await _run(check)


async def test_tagged_tables_default_to_the_current_project():
    """The column default is ruth_current_project_id(), on every tagged table.

    project_cameras and project_jobs also have a project_id, but as an
    explicit reference to one project (membership, the project a job acts
    on), not a tag defaulting to the current project, so they are excluded.
    """
    from sqlalchemy import text

    from app.models.project_tag import TAGGED_TABLES

    async def check(conn):
        rows = (
            await conn.execute(
                text(
                    "SELECT table_name, is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name = 'project_id' "
                    "AND table_name NOT LIKE '%\\_archive' "
                    "AND table_name NOT IN ('project_cameras', 'project_jobs')"
                )
            )
        ).all()
        found = {t: (n, d) for t, n, d in rows}
        assert set(found) == set(TAGGED_TABLES)
        for table, (nullable, default) in found.items():
            assert nullable == "NO", table
            assert default == "ruth_current_project_id()", (table, default)

    await _run(check)



async def test_a_migrated_database_always_has_a_project():
    """projects_as_tags creates one on a fresh install, so new rows can be tagged."""
    from sqlalchemy import text

    async def check(conn):
        assert (await conn.execute(text("SELECT count(*) FROM projects"))).scalar() >= 1
        assert (await conn.execute(text("SELECT ruth_current_project_id()"))).scalar() is not None

    await _run(check)
