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


@pytest.mark.parametrize("second", ["active", "stopped", "ended"])
async def test_only_one_current_project(second):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    async def check(conn):
        await conn.execute(text("UPDATE projects SET state = 'archived'"))
        await _insert(conn, "stopped")
        with pytest.raises(IntegrityError):
            await _insert(conn, second)

    await _run(check)
