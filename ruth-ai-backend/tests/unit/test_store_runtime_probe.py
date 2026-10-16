"""The shared model store runtime probe.

The behaviour under test is the one that was missing when the store runtime
sat unreachable for twelve days: a failure has to become a *value* callers
can render, and the log has to fire once per state change rather than once
per request (which is why nobody read it).
"""

from datetime import datetime, timedelta, timezone

import pytest
from structlog.testing import capture_logs

from app.integrations.unified_runtime import client as runtime_client
from app.integrations.unified_runtime import config as runtime_config
from app.services.model_store import runtime_probe
from app.services.model_store.runtime_probe import (
    StoreRuntimeProbe,
    probe_store_runtime,
    reset_probe_state,
)

STORE_URL = "http://model-store-runtime:8000"

CAPS = {
    "runtime_id": "model-store-runtime",
    "models": [
        {"model_id": "hard_hat", "version": "1.0.0", "state": "ready", "health": "healthy"},
        {"model_id": "safety_vest", "version": "1.0.0", "state": "ready", "health": "healthy"},
        {"model_id": "gloves", "version": "1.0.0", "state": "failed", "health": "unhealthy"},
    ],
}

#: What a vanished DNS name actually raises through the client — the exact
#: failure that hid for twelve days.
DNS_FAILURE = "Failed to connect: [Errno -2] Name or service not known"


class FakeClient:
    def __init__(self, state):
        self.state = state

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_capabilities(self):
        self.state["calls"] += 1
        if self.state["fail"]:
            raise ConnectionError(DNS_FAILURE)
        return self.state["caps"]


@pytest.fixture
def store(monkeypatch):
    """Controls the fake store runtime and counts calls made to it."""
    state = {"calls": 0, "fail": False, "caps": CAPS, "url": STORE_URL}

    def factory(runtime_url=None, timeout=None):
        return FakeClient(state)

    monkeypatch.setattr(runtime_client, "UnifiedRuntimeClient", factory)

    def configure():
        cfg = runtime_config.UnifiedRuntimeConfig(
            MODEL_STORE_RUNTIME_URL=state["url"]
        )
        monkeypatch.setattr(
            runtime_config, "get_unified_runtime_config", lambda: cfg
        )

    state["configure"] = configure
    configure()
    reset_probe_state()
    yield state
    reset_probe_state()


# --------------------------------------------------------------------------
# States
# --------------------------------------------------------------------------


async def test_reachable_store_reports_counts(store):
    probe = await probe_store_runtime()

    assert probe.configured is True
    assert probe.reachable is True
    assert probe.error is None
    assert probe.total == 3
    assert probe.ready == 2  # gloves is "failed"
    assert probe.not_ready_ids == ("gloves",)
    assert probe.partially_ready is True
    assert probe.last_success_at == probe.checked_at
    assert probe.runtime_id == "model-store-runtime"


async def test_all_ready_store_is_not_partially_ready(store):
    store["caps"] = {"models": [dict(CAPS["models"][0])]}
    probe = await probe_store_runtime()

    assert (probe.ready, probe.total) == (1, 1)
    assert probe.partially_ready is False
    assert probe.not_ready_ids == ()


async def test_unreachable_store_carries_the_error_not_an_exception(store):
    store["fail"] = True
    probe = await probe_store_runtime()

    # The whole point: a failure is a value, never a raise.
    assert probe.configured is True
    assert probe.reachable is False
    assert DNS_FAILURE in probe.error
    assert probe.total == 0 and probe.ready == 0
    assert probe.models == ()


async def test_unconfigured_store_is_not_a_failure(store, monkeypatch):
    store["url"] = ""
    store["configure"]()
    reset_probe_state()

    probe = await probe_store_runtime()

    assert probe.configured is False
    assert probe.reachable is False
    assert probe.error is None
    # And it never called out: there is nothing to call.
    assert store["calls"] == 0


async def test_last_success_at_survives_a_later_failure(store):
    first = await probe_store_runtime()
    assert first.reachable is True

    store["fail"] = True
    later = await probe_store_runtime(force=True)

    assert later.reachable is False
    # The card needs to say how long it has been down.
    assert later.last_success_at == first.checked_at


def test_model_lookup_returns_the_reported_entry():
    probe = StoreRuntimeProbe(
        configured=True,
        reachable=True,
        checked_at=datetime.now(timezone.utc),
        models=tuple(CAPS["models"]),
    )
    assert probe.model("gloves")["state"] == "failed"
    assert probe.model("absent") is None
    assert probe.model_ids == ("hard_hat", "safety_vest", "gloves")


# --------------------------------------------------------------------------
# Caching
# --------------------------------------------------------------------------


async def test_repeat_calls_within_ttl_hit_the_runtime_once(store):
    for _ in range(5):
        await probe_store_runtime()
    # A dashboard load asks health, models/status and the admin list at
    # once; that must cost one HTTP call, not one per consumer.
    assert store["calls"] == 1


async def test_force_bypasses_the_cache(store):
    await probe_store_runtime()
    await probe_store_runtime(force=True)
    assert store["calls"] == 2


async def test_expired_cache_refreshes(store, monkeypatch):
    await probe_store_runtime()
    assert store["calls"] == 1

    # Age the cache past its TTL rather than sleeping.
    stamp, probe = runtime_probe._cache
    monkeypatch.setattr(
        runtime_probe, "_cache", (stamp - runtime_probe.PROBE_TTL_SECONDS - 1, probe)
    )

    await probe_store_runtime()
    assert store["calls"] == 2


async def test_concurrent_cold_callers_share_one_call(store):
    import asyncio

    await asyncio.gather(*(probe_store_runtime() for _ in range(4)))
    # Without the lock each coroutine would find an empty cache and probe.
    assert store["calls"] == 1


# --------------------------------------------------------------------------
# Transition logging — one line per state change, not per request
# --------------------------------------------------------------------------


def _probe_logs(entries, level):
    """Probe log lines at ``level``.

    structlog renders through its own processor chain straight to stdout, so
    pytest's caplog never sees these records; capture_logs taps the chain
    itself.
    """
    return [
        e
        for e in entries
        if e.get("log_level") == level
        and "Model store runtime" in e.get("event", "")
    ]


async def test_repeated_failures_log_one_warning_not_one_per_call(store):
    store["fail"] = True
    with capture_logs() as entries:
        for _ in range(4):
            await probe_store_runtime(force=True)

    warnings = _probe_logs(entries, "warning")
    # Four failed probes, one warning. The old code logged on every request,
    # which is precisely why the twelve-day outage went unread.
    assert len(warnings) == 1
    assert "became unreachable" in warnings[0]["event"]
    assert warnings[0]["error"]


async def test_steady_reachable_state_logs_nothing(store):
    with capture_logs() as entries:
        for _ in range(3):
            await probe_store_runtime(force=True)

    assert _probe_logs(entries, "warning") == []
    assert _probe_logs(entries, "info") == []


async def test_recovery_logs_once_after_a_failure(store):
    with capture_logs() as entries:
        await probe_store_runtime(force=True)  # healthy baseline
        store["fail"] = True
        await probe_store_runtime(force=True)  # -> unreachable
        store["fail"] = False
        await probe_store_runtime(force=True)  # -> recovered
        await probe_store_runtime(force=True)  # steady: silent

    assert len(_probe_logs(entries, "warning")) == 1
    recoveries = _probe_logs(entries, "info")
    assert len(recoveries) == 1
    assert "recovered" in recoveries[0]["event"]


async def test_first_probe_failing_still_warns(store):
    """A store already broken at startup is exactly the case that hid."""
    store["fail"] = True
    with capture_logs() as entries:
        await probe_store_runtime()

    warnings = _probe_logs(entries, "warning")
    assert len(warnings) == 1
    # No prior state to compare against, and we still speak up.
    assert warnings[0]["was_reachable"] is None


async def test_unconfigured_store_never_logs(store):
    store["url"] = ""
    store["configure"]()
    reset_probe_state()

    with capture_logs() as entries:
        for _ in range(3):
            await probe_store_runtime(force=True)

    # The feature being off is not an event.
    assert _probe_logs(entries, "warning") == []
    assert _probe_logs(entries, "info") == []


async def test_downtime_duration_is_reported_on_recovery(store, monkeypatch):
    await probe_store_runtime(force=True)
    store["fail"] = True
    await probe_store_runtime(force=True)

    # Pretend the last success was a while back so the recovery line has a
    # duration worth printing.
    monkeypatch.setattr(
        runtime_probe,
        "_last_success_at",
        datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    store["fail"] = False
    with capture_logs() as entries:
        await probe_store_runtime(force=True)

    recovery = _probe_logs(entries, "info")[0]
    assert recovery["unreachable_for_seconds"] >= 300
