"""Route uploaded (model store) models to the store runtime.

Built-in models keep going to the unified runtime exactly as before: this
only changes which client serves an id the store runtime reports and that is
not a reserved built-in id. Used only when MODEL_STORE_RUNTIME_URL is set.
"""

import asyncio
import time
from typing import FrozenSet, Optional

from app.core.logging import get_logger
from app.integrations.vas import VASClient
from app.services.model_store.ids import RESERVED_MODEL_IDS

from .client import UnifiedRuntimeClient
from .router import RuntimeRouter

logger = get_logger(__name__)

#: How long the store runtime's model list is trusted before it is re-read.
STORE_IDS_REFRESH_SECONDS = 30.0


class StoreAwareRouter(RuntimeRouter):
    """RuntimeRouter that sends store model ids to a second runtime."""

    def __init__(
        self,
        vas_client: VASClient,
        unified_runtime_client: UnifiedRuntimeClient,
        store_runtime_client: UnifiedRuntimeClient,
        refresh_seconds: float = STORE_IDS_REFRESH_SECONDS,
    ):
        super().__init__(vas_client=vas_client, unified_runtime_client=unified_runtime_client)
        self.store_runtime_client = store_runtime_client
        self._refresh_seconds = refresh_seconds
        self._store_ids: FrozenSet[str] = frozenset()
        self._checked_at: Optional[float] = None
        self._lock = asyncio.Lock()

    async def store_model_ids(self) -> FrozenSet[str]:
        """Model ids the store runtime serves, refreshed every few seconds.

        A failed read keeps the last known set (the store runtime restarting
        for an Apply shouldn't send its models to the built-in runtime, which
        doesn't have them); before the first successful read it is empty.
        """
        now = time.monotonic()
        if self._checked_at is not None and now - self._checked_at < self._refresh_seconds:
            return self._store_ids
        async with self._lock:
            now = time.monotonic()
            if self._checked_at is not None and now - self._checked_at < self._refresh_seconds:
                return self._store_ids
            try:
                capabilities = await self.store_runtime_client.get_capabilities()
                ids = {
                    m["model_id"]
                    for m in capabilities.get("models", [])
                    if m.get("model_id") and m.get("state") != "invalid"
                }
                self._store_ids = frozenset(ids - RESERVED_MODEL_IDS)
            except Exception as exc:  # noqa: BLE001 - routing must not fail on a lookup
                logger.warning(
                    "Model store runtime unreachable; keeping last known model list",
                    error=str(exc),
                    known=sorted(self._store_ids),
                )
            self._checked_at = now
            return self._store_ids

    async def client_for(self, model_id: str) -> UnifiedRuntimeClient:
        if model_id in RESERVED_MODEL_IDS:
            return self.unified_runtime_client
        if model_id in await self.store_model_ids():
            return self.store_runtime_client
        return self.unified_runtime_client
