"""One shared reachability probe for the model store runtime.

Three surfaces need the same fact — is the store runtime reachable, and what
does it report? — and each used to ask independently:

* ``GET /api/v1/health`` (the "Model store runtime" card),
* ``GET /api/v1/models/status`` (the camera picker's model list),
* ``GET /api/v1/admin/models`` (Model Management's Runtime column).

Asking separately would mean three HTTP calls per dashboard load, and would
make "log once per state change" impossible: with no shared state there is
nothing to compare the current result against. So they all come through
here.

Why this module exists at all: the store runtime sat unreachable for twelve
days without anyone noticing. Its DNS name stopped resolving when the
compose network was recreated without its profile active, and every consumer
degraded *quietly* — the model list simply returned the built-ins, which is
indistinguishable from "no store configured". The probe turns that state
into a value every caller can render, and logs the transition once instead
of emitting a warning on every request that nobody reads.

Nothing here raises: a failure is a field on the returned probe, never an
exception. Callers render it; they do not handle it.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from app.core.logging import get_logger

logger = get_logger(__name__)

#: How long a probe result is reused. A dashboard load hits health,
#: models/status and (on the admin page) the model list at once; one TTL
#: window collapses those into a single call to the store runtime.
PROBE_TTL_SECONDS = 10.0

#: A hung store runtime must never hold up the model list. Deliberately
#: shorter than the frontend's request timeout.
PROBE_TIMEOUT_SECONDS = 5.0

#: The only state in which the store runtime can actually serve a model.
READY_STATE = "ready"


@dataclass(frozen=True)
class StoreRuntimeProbe:
    """What the store runtime looked like at ``checked_at``.

    ``configured`` False means MODEL_STORE_RUNTIME_URL is unset — the
    feature is off, which is NOT a fault and must never render as one.
    """

    configured: bool
    reachable: bool
    checked_at: datetime
    runtime_url: str = ""
    runtime_id: str = ""
    error: Optional[str] = None
    #: Last time /capabilities answered, for THIS backend process. Not
    #: persisted: it resets on restart, so the UI says "since backend start"
    #: rather than implying it survived one.
    last_success_at: Optional[datetime] = None
    #: Raw /capabilities entries, as reported. Empty when unreachable.
    models: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return len(self.models)

    @property
    def ready(self) -> int:
        return sum(1 for m in self.models if m.get("state") == READY_STATE)

    @property
    def not_ready_ids(self) -> Tuple[str, ...]:
        return tuple(
            str(m.get("model_id"))
            for m in self.models
            if m.get("model_id") and m.get("state") != READY_STATE
        )

    @property
    def model_ids(self) -> Tuple[str, ...]:
        return tuple(str(m.get("model_id")) for m in self.models if m.get("model_id"))

    def model(self, model_id: str) -> Optional[Dict[str, Any]]:
        """The reported entry for ``model_id``, or None if it isn't loaded."""
        for entry in self.models:
            if entry.get("model_id") == model_id:
                return entry
        return None

    @property
    def partially_ready(self) -> bool:
        """Reachable, but not everything it holds is usable."""
        return self.reachable and self.total > 0 and self.ready < self.total


# --------------------------------------------------------------------------
# Module state
# --------------------------------------------------------------------------

_cache: Optional[Tuple[float, StoreRuntimeProbe]] = None
_last_success_at: Optional[datetime] = None
#: None until the first probe: the first result is a baseline, not a change.
#: A first probe that FAILS is still worth a warning — a store already broken
#: at startup is exactly the case that went unnoticed before.
_last_reachable: Optional[bool] = None
#: Serializes concurrent probes so a cold cache costs one call, not three.
_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    # Created lazily: a Lock built at import time binds to whichever event
    # loop is current then, which breaks across test loops.
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def reset_probe_state() -> None:
    """Drop the cache and transition history. For tests."""
    global _cache, _last_success_at, _last_reachable, _lock
    _cache = None
    _last_success_at = None
    _last_reachable = None
    _lock = None


def _note_transition(
    probe: StoreRuntimeProbe,
    *,
    previous_success_at: Optional[datetime] = None,
) -> None:
    """Log only when reachability flips. Steady state is silent.

    ``previous_success_at`` is the last success from *before* this probe. On
    recovery ``probe.last_success_at`` is already "now", so the downtime has
    to be measured against the earlier value or it always reads as zero.
    """
    global _last_reachable
    previous = _last_reachable
    _last_reachable = probe.reachable

    if previous == probe.reachable:
        return

    if not probe.reachable:
        # Covers True -> False and a first probe that already fails.
        logger.warning(
            "Model store runtime became unreachable",
            url=probe.runtime_url,
            error=probe.error,
            last_success_at=(
                probe.last_success_at.isoformat() if probe.last_success_at else None
            ),
            was_reachable=previous,
        )
        return

    if previous is False:
        unreachable_for = None
        if previous_success_at is not None:
            unreachable_for = round(
                (probe.checked_at - previous_success_at).total_seconds(), 1
            )
        logger.info(
            "Model store runtime recovered",
            url=probe.runtime_url,
            models_ready=probe.ready,
            models_total=probe.total,
            unreachable_for_seconds=unreachable_for,
        )


async def _run_probe() -> StoreRuntimeProbe:
    """Call /capabilities once and build a probe from the outcome."""
    global _last_success_at

    # Imported here: the client and config modules import from this
    # package's siblings, so a module-level import would cycle.
    from app.integrations.unified_runtime.client import UnifiedRuntimeClient
    from app.integrations.unified_runtime.config import get_unified_runtime_config

    config = get_unified_runtime_config()
    url = config.model_store_runtime_url
    now = datetime.now(timezone.utc)

    if not url:
        # Feature off. No call, and no transition tracking — an unconfigured
        # store must never be mistaken for a broken one.
        return StoreRuntimeProbe(
            configured=False,
            reachable=False,
            checked_at=now,
            runtime_id=config.model_store_runtime_id,
        )

    try:
        async with UnifiedRuntimeClient(
            runtime_url=url, timeout=PROBE_TIMEOUT_SECONDS
        ) as client:
            capabilities = await client.get_capabilities()
    except Exception as exc:  # noqa: BLE001 - every failure is a probe field
        probe = StoreRuntimeProbe(
            configured=True,
            reachable=False,
            checked_at=now,
            runtime_url=url,
            runtime_id=config.model_store_runtime_id,
            error=str(exc) or exc.__class__.__name__,
            last_success_at=_last_success_at,
        )
        _note_transition(probe)
        return probe

    # Captured before it is overwritten: the recovery log reports how long
    # the store was down, which is now minus the PREVIOUS success.
    previous_success_at = _last_success_at
    _last_success_at = now
    probe = StoreRuntimeProbe(
        configured=True,
        reachable=True,
        checked_at=now,
        runtime_url=url,
        runtime_id=str(capabilities.get("runtime_id") or config.model_store_runtime_id),
        last_success_at=now,
        models=tuple(m for m in capabilities.get("models", []) if isinstance(m, dict)),
    )
    _note_transition(probe, previous_success_at=previous_success_at)
    return probe


async def probe_store_runtime(*, force: bool = False) -> StoreRuntimeProbe:
    """Current store runtime state, cached for ``PROBE_TTL_SECONDS``.

    Args:
        force: Skip the cache and probe now.

    Returns:
        A probe. Never raises.
    """
    global _cache

    if not force and _cache is not None:
        if time.monotonic() - _cache[0] < PROBE_TTL_SECONDS:
            return _cache[1]

    async with _get_lock():
        # Re-check inside the lock: a concurrent caller may have refreshed
        # while we waited, which is the point of serializing here.
        if not force and _cache is not None:
            if time.monotonic() - _cache[0] < PROBE_TTL_SECONDS:
                return _cache[1]

        probe = await _run_probe()
        _cache = (time.monotonic(), probe)
        return probe
