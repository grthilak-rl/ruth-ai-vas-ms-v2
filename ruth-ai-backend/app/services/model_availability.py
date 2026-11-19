"""Is a model installed? The one check every path that takes a model ID uses.

Installed means either:

- an installed model-store manifest (``enabled_store_models()``, the same
  membership test routing uses), or
- a model on the unified runtime, asked only while ``UNIFIED_RUNTIME_IN_USE``
  is true. With the built-ins retired the runtime is not asked at all.

A model that is not installed is refused with a code the API returns as 422:

- ``model_retired``: a retired built-in, with the model that replaced it
- ``model_not_installed``: anything else

The unified runtime's list is cached for ``CACHE_TTL_SECONDS`` so a burst of
requests does not ask it N times. If it is in use and unreachable, a model
that is not in the store cannot be decided: ``UnifiedRuntimeError`` (503).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Iterable

from app.core.logging import get_logger
from app.integrations.unified_runtime.client import (
    UnifiedRuntimeClient,
    UnifiedRuntimeError,
)
from app.integrations.unified_runtime.config import get_unified_runtime_config
from app.services.model_store.enabled import enabled_store_models

logger = get_logger(__name__)

CACHE_TTL_SECONDS = 30.0

#: Retired built-in models and what replaced them (None: nothing did).
RETIRED_MODELS: dict[str, str | None] = {
    "fall_detection": "fall_pose",
    "ppe_detection": "the store PPE models (hard_hat, gloves, goggles, harness, safety_vest)",
    "geo_fencing": "geofence",
    "tank_overflow_monitoring": None,
    "chane_tank_monitor": None,
    "chane_tank_overflow": None,
}


class ModelNotAvailableError(Exception):
    """The model is not installed (``code``: model_retired / model_not_installed)."""

    def __init__(self, model_id: str, code: str, message: str, replacement: str | None = None):
        super().__init__(message)
        self.model_id = model_id
        self.code = code
        self.message = message
        self.replacement = replacement

    def detail(self) -> dict[str, Any]:
        out: dict[str, Any] = {"error": self.code, "message": self.message, "model_id": self.model_id}
        if self.replacement:
            out["replacement"] = self.replacement
        return out


def not_installed_error(model_id: str) -> ModelNotAvailableError:
    """Why ``model_id`` is refused, given that it is not installed."""
    if model_id in RETIRED_MODELS:
        replacement = RETIRED_MODELS[model_id]
        if replacement:
            message = f"{model_id} is retired; use {replacement}"
        else:
            message = f"{model_id} is retired and has no replacement"
        return ModelNotAvailableError(model_id, "model_retired", message, replacement)
    return ModelNotAvailableError(model_id, "model_not_installed", f"{model_id} is not installed")


_cache_lock = asyncio.Lock()
_cache: dict[str, Any] = {"models": None, "expires_at": 0.0}


async def _refresh_catalog() -> list[dict[str, Any]]:
    """The unified runtime's /capabilities models. Raises UnifiedRuntimeError."""
    async with UnifiedRuntimeClient() as client:
        capabilities = await client.get_capabilities()
    return capabilities.get("models", []) or []


async def _unified_model_ids() -> set[str]:
    """Model IDs on the unified runtime (cached). Raises UnifiedRuntimeError."""
    now = time.monotonic()
    async with _cache_lock:
        if _cache["models"] is None or _cache["expires_at"] <= now:
            _cache["models"] = await _refresh_catalog()
            _cache["expires_at"] = now + CACHE_TTL_SECONDS
            logger.debug("Refreshed unified runtime model list", model_count=len(_cache["models"]))
        return {m.get("model_id") for m in _cache["models"]}


def _store_model_ids() -> set[str]:
    try:
        return set(enabled_store_models())
    except Exception:  # noqa: BLE001 - an unreadable store installs nothing
        return set()


async def assert_model_available(model_id: str) -> None:
    """Raise ``ModelNotAvailableError`` unless ``model_id`` is installed.

    Raises ``UnifiedRuntimeError`` only when the unified runtime is in use,
    the model is not in the store, and the runtime cannot be reached.
    """
    if model_id in _store_model_ids():
        return
    if get_unified_runtime_config().unified_runtime_in_use and model_id in await _unified_model_ids():
        return
    raise not_installed_error(model_id)


async def unavailable_models(model_ids: Iterable[str]) -> dict[str, ModelNotAvailableError]:
    """The models of ``model_ids`` that are known not to be installed.

    Never raises: if the unified runtime is in use but unreachable, models
    outside the store are undecided and left out (a failing one still shows
    up as failing; this only avoids calling a runtime blip "not installed").
    """
    ids = set(model_ids)
    store = _store_model_ids()
    pending = ids - store
    if not pending:
        return {}
    if get_unified_runtime_config().unified_runtime_in_use:
        try:
            pending -= await _unified_model_ids()
        except UnifiedRuntimeError:
            return {}
    return {m: not_installed_error(m) for m in sorted(pending)}
