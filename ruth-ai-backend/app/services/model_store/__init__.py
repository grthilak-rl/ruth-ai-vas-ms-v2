"""Model store (Model Management): uploaded models, files and chunked uploads.

Self-contained: used only by app/api/v1/admin/model_store.py.
"""

import asyncio
import contextlib
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, status
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.logging import get_logger
from app.services.model_store.storage import ModelStore, StoreUnavailableError

logger = get_logger(__name__)

CLEANUP_INTERVAL_SECONDS = 30 * 60
CLEANUP_FIRST_RUN_SECONDS = 60


class ModelStoreSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    #: Store root inside the backend container (host: /mnt/storage/ruth-models).
    model_store_root: str = "/store"


@lru_cache
def _configured_store() -> ModelStore:
    return ModelStore(Path(ModelStoreSettings().model_store_root))


def get_model_store() -> ModelStore:
    """The store, with its layout in place, or 503 if it is not mounted/writable.

    Checked per request (cheap): a missing or read-only mount answers 503 on
    the model-store routes only, and never breaks startup or any other route.
    """
    store = _configured_store()
    try:
        store.ensure_layout()
    except StoreUnavailableError as exc:
        logger.warning("Model store unavailable", reason=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "model_store_unavailable", "message": "model store not available"},
        )
    return store


async def run_cleanup_once() -> None:
    """One stale-staging pass, if the store and the database are available."""
    from app.core.database import get_db_session
    from app.services.model_store.service import cleanup_stale_staging

    store = _configured_store()
    try:
        await asyncio.to_thread(store.ensure_layout)
    except StoreUnavailableError:
        return
    try:
        async for db in get_db_session():
            await cleanup_stale_staging(db, store)
    except RuntimeError:
        # Database not initialised (e.g. startup still in progress).
        return


async def _cleanup_loop() -> None:
    await asyncio.sleep(CLEANUP_FIRST_RUN_SECONDS)
    while True:
        try:
            await run_cleanup_once()
        except Exception as exc:  # noqa: BLE001 - never let the loop die
            logger.error("Model store staging cleanup failed", error=str(exc))
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


@contextlib.asynccontextmanager
async def model_store_lifespan(_app):
    """Router lifespan: runs the stale-staging cleanup in the background.

    Merged into the app lifespan by include_router, nested inside it, so the
    database is initialised before the first pass and the task is cancelled
    before the database closes.
    """
    task = asyncio.create_task(_cleanup_loop(), name="model-store-staging-cleanup")
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


__all__ = ["ModelStore", "get_model_store", "model_store_lifespan", "run_cleanup_once"]
