"""Fixtures for DB-backed model store tests.

Needs a throwaway Postgres (partial unique indexes, advisory locks and
SELECT ... FOR UPDATE are Postgres features), given as:

    MODEL_STORE_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db

Only the three model_store_* tables are created there; the tests are skipped
when the variable is unset. Limits are shrunk so files are a few KB.
"""

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.admin_auth import get_admin_auth_config, issue_admin_token
from app.deps.db import get_db
from app.main import create_application
from app.models.model_store import ModelStoreFile, ModelStoreModel, ModelStoreUpload
from app.services.model_store import get_model_store, service
from app.services.model_store.storage import ModelStore
from tests.unit.test_admin_auth import USERNAME, make_config

DATABASE_URL = os.environ.get("MODEL_STORE_TEST_DATABASE_URL")
TABLES = [ModelStoreModel.__table__, ModelStoreFile.__table__, ModelStoreUpload.__table__]

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="MODEL_STORE_TEST_DATABASE_URL not set"
)

TEST_CHUNK = 1024


@pytest.fixture
async def session_factory():
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: ModelStoreModel.metadata.create_all(c, tables=TABLES))
        await conn.execute(
            text("TRUNCATE model_store_uploads, model_store_files, model_store_models CASCADE")
        )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def store(tmp_path) -> ModelStore:
    model_store = ModelStore(tmp_path / "ruth-models")
    model_store.root.mkdir()
    model_store.ensure_layout()
    return model_store


@pytest.fixture(autouse=True)
def small_limits(monkeypatch):
    monkeypatch.setattr(service, "CHUNK_SIZE", TEST_CHUNK)
    monkeypatch.setattr(service, "MAX_FILE_BYTES", 64 * TEST_CHUNK)
    monkeypatch.setattr(service, "STAGING_QUOTA_BYTES", 16 * TEST_CHUNK)
    monkeypatch.setattr(service, "DISK_HEADROOM_BYTES", 0)


@pytest.fixture
def app(session_factory, store):
    application = create_application()
    config = make_config()

    async def db_override() -> AsyncGenerator:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[get_admin_auth_config] = lambda: config
    application.dependency_overrides[get_db] = db_override
    application.dependency_overrides[get_model_store] = lambda: store
    application.state.test_token = issue_admin_token(config)[0]
    return application


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    headers = {"Authorization": f"Bearer {app.state.test_token}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    ) as c:
        yield c


@pytest.fixture
def admin_username() -> str:
    return USERNAME
