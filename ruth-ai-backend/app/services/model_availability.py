"""Model availability check with short-TTL cache.

The bookmark-analyses submit path needs to fail fast if the operator
asks for a model that isn't registered with the unified runtime. We
call the runtime's /capabilities endpoint, but cache the result for
``CACHE_TTL_SECONDS`` so a burst of concurrent submits doesn't hit
the runtime N times.

Failure modes are distinguished so the API layer can return the right
status code:
- ``UnifiedRuntimeError`` from the underlying client → 503
- Model not present in the (cached or fresh) catalog → 400
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.core.logging import get_logger
from app.integrations.unified_runtime.client import (
    UnifiedRuntimeClient,
    UnifiedRuntimeError,
)

logger = get_logger(__name__)

CACHE_TTL_SECONDS = 30.0


class ModelNotAvailableError(Exception):
    """Model is not registered or not healthy on the runtime."""


_cache_lock = asyncio.Lock()
_cache: dict[str, Any] = {"models": None, "expires_at": 0.0}


async def _refresh_catalog() -> list[dict[str, Any]]:
    """Fetch /capabilities and return the models list. Raises
    UnifiedRuntimeError on transport failure."""
    async with UnifiedRuntimeClient() as client:
        capabilities = await client.get_capabilities()
    return capabilities.get("models", []) or []


async def _get_catalog() -> list[dict[str, Any]]:
    """Return the cached models list, refreshing on miss/expiry."""
    now = time.monotonic()
    async with _cache_lock:
        if _cache["models"] is not None and _cache["expires_at"] > now:
            return _cache["models"]
        try:
            models = await _refresh_catalog()
        except UnifiedRuntimeError:
            # Leave stale entry alone so subsequent calls within the
            # same lock window also see the same outcome.
            raise
        _cache["models"] = models
        _cache["expires_at"] = now + CACHE_TTL_SECONDS
        logger.debug(
            "Refreshed model availability cache",
            model_count=len(models),
            ttl_seconds=CACHE_TTL_SECONDS,
        )
        return models


async def assert_model_available(model_id: str) -> dict[str, Any]:
    """Raise ``ModelNotAvailableError`` if ``model_id`` isn't on the
    runtime, or ``UnifiedRuntimeError`` if the runtime is unreachable.

    Returns the matching model dict from /capabilities on success.
    """
    catalog = await _get_catalog()
    for m in catalog:
        if m.get("model_id") == model_id:
            return m
    raise ModelNotAvailableError(
        f"Model {model_id!r} is not registered with the unified runtime. "
        f"Available models: {[m.get('model_id') for m in catalog]}"
    )
