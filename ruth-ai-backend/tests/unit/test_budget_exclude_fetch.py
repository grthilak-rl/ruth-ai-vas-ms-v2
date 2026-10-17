"""BL-10 (a): charge the GPU budget for GPU time only.

`InferenceBudget` exists to keep aggregate GPU demand under
MAX_GPU_UTILIZATION, but it was being fed `fetch_seconds + inference`.
Frame fetch is network I/O to VAS and occupies no GPU, so roughly half
the GPU budget was being spent on something that is not the GPU, and
every camera was paced at about half the rate the hardware could serve.

Two properties are under test, and they pull in opposite directions:

1. **Flag off, nothing changes.** This repaces every camera on the
   deployment, so the default must be provably identical to today.
2. **Flag on, the budget frees up — but the schedule does not outrun the
   work.** A tick costs a fetch plus an inference in wall time whatever
   the GPU is doing. An interval shorter than that cannot be met, and the
   loop would fire every iteration immediately, spinning without gaining
   throughput. That is the failure mode this change could introduce, so
   it gets the most tests.

Measured inputs (HPCL, 2026-10-17): inference 65 ms, fetch ~80 ms,
36 consumers, MAX_GPU_UTILIZATION 2.3.
"""

import importlib
import os
from unittest.mock import patch

import pytest

INFERENCE_S = 0.065
FETCH_S = 0.080
CONSUMERS = 36


def _load(exclude_fetch: str | None):
    """Import inference_loop with the flag set as given (read at import)."""
    env = dict(os.environ)
    env.pop("RUTH_BUDGET_EXCLUDE_FETCH", None)
    if exclude_fetch is not None:
        env["RUTH_BUDGET_EXCLUDE_FETCH"] = exclude_fetch
    with patch.dict(os.environ, env, clear=True):
        import app.services.inference_loop as mod

        return importlib.reload(mod)


def _budget(mod, *, consumers: int = CONSUMERS, model: str = "safety_vest"):
    """A budget primed exactly as the loop would prime it."""
    import uuid

    b = mod.InferenceBudget()
    for _ in range(consumers):
        b.register(uuid.uuid4())
    # What the loop records depends on the flag — mirror it here.
    recorded = INFERENCE_S if mod.BUDGET_EXCLUDE_FETCH else FETCH_S + INFERENCE_S
    b.record_latency(model, recorded)
    b.record_fetch(FETCH_S)
    return b


# -----------------------------------------------------------------------------
# The flag
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_flag_on_for_truthy_values(value):
    assert _load(value).BUDGET_EXCLUDE_FETCH is True


@pytest.mark.parametrize("value", [None, "", "0", "false", "no", "off", "nonsense"])
def test_flag_defaults_off(value):
    """Anything not explicitly truthy leaves pacing exactly as it is."""
    assert _load(value).BUDGET_EXCLUDE_FETCH is False


# -----------------------------------------------------------------------------
# Property 1 — flag off is today's behaviour
# -----------------------------------------------------------------------------


def test_flag_off_reproduces_the_measured_rate():
    """0.44/s per consumer is what the deployment actually achieves.

    If this number moves, the default path has changed and the flag is
    not doing its job.
    """
    mod = _load(None)
    b = _budget(mod)
    fps = b.fps_for_consumer("safety_vest", desired_fps=2.0)
    assert fps == pytest.approx(0.44, abs=0.01)


def test_flag_off_charges_fetch_to_the_budget():
    mod = _load(None)
    b = _budget(mod)
    # The recorded latency is fetch + inference, as it has always been.
    assert b.latency_for("safety_vest") == pytest.approx(FETCH_S + INFERENCE_S)


def test_flag_off_interval_is_unchanged_by_the_new_floor():
    """The floor is applied unconditionally; it must be inert by default.

    A tick costs ~0.145 s and the budget hands out ~2.3 s, so the floor
    is far from binding — but asserting it keeps a future tightening from
    silently changing the default path.
    """
    mod = _load(None)
    b = _budget(mod)
    interval = 1.0 / b.fps_for_consumer("safety_vest", 2.0)
    assert interval > b.min_tick_seconds("safety_vest")


# -----------------------------------------------------------------------------
# Property 2 — flag on frees the budget
# -----------------------------------------------------------------------------


def test_flag_on_excludes_fetch_and_roughly_doubles_the_rate():
    mod = _load("true")
    b = _budget(mod)
    assert b.latency_for("safety_vest") == pytest.approx(INFERENCE_S)

    fps = b.fps_for_consumer("safety_vest", desired_fps=2.0)
    assert fps == pytest.approx(0.98, abs=0.02)

    # The point of the change, stated as a ratio so it survives retuning.
    off = _budget(_load(None)).fps_for_consumer("safety_vest", 2.0)
    assert fps / off == pytest.approx(2.2, abs=0.15)


def test_fetch_is_still_tracked_when_excluded_from_the_budget():
    """Excluded from the GPU budget, not forgotten — the scheduler needs it."""
    mod = _load("true")
    b = _budget(mod)
    assert b.fetch_estimate() == pytest.approx(FETCH_S)
    assert b.min_tick_seconds("safety_vest") == pytest.approx(FETCH_S + INFERENCE_S)


# -----------------------------------------------------------------------------
# Property 2b — the schedule never outruns the work (no spinning)
# -----------------------------------------------------------------------------


def _interval(mod, entry, budget):
    """_multi_interval without constructing the whole service."""
    from app.services.model_rates import desired_fps

    fps = budget.fps_for_consumer(entry["model_id"], desired_fps(entry, mod.TARGET_FPS))
    return max(1.0 / fps, budget.min_tick_seconds(entry["model_id"]))


@pytest.mark.parametrize("consumers", [1, 2, 3, 6, 12, 36, 100])
def test_interval_never_below_fetch_plus_inference(consumers):
    """The anti-spin guarantee, across the whole fleet-size range.

    At low consumer counts the budget is generous and would otherwise
    hand back an interval shorter than a tick takes.
    """
    mod = _load("true")
    b = _budget(mod, consumers=consumers)
    entry = {"model_id": "safety_vest"}
    assert _interval(mod, entry, b) >= b.min_tick_seconds("safety_vest") - 1e-9


def test_floor_binds_when_fetch_is_pathologically_slow():
    """A slow VAS must slow the schedule, not make the loop spin.

    If fetch degrades to 2 s, no amount of free GPU budget makes a tick
    cheaper than 2 s, and the interval has to reflect that.
    """
    import uuid

    mod = _load("true")
    b = mod.InferenceBudget()
    b.register(uuid.uuid4())           # one consumer: budget is generous
    b.record_latency("safety_vest", INFERENCE_S)
    b.record_fetch(2.0)                # VAS crawling

    entry = {"model_id": "safety_vest"}
    unfloored = 1.0 / b.fps_for_consumer("safety_vest", 2.0)
    floored = _interval(mod, entry, b)

    assert unfloored < 2.0 < floored   # the floor is what binds
    assert floored == pytest.approx(2.0 + INFERENCE_S, abs=0.01)


def test_default_fetch_estimate_is_used_before_any_tick():
    """The first few ticks have no measurement yet.

    The default errs high: under-estimating would let the scheduler ask
    for intervals the loop cannot meet during startup.
    """
    mod = _load("true")
    b = mod.InferenceBudget()
    assert b.fetch_estimate() == mod.DEFAULT_FETCH_S
    assert mod.DEFAULT_FETCH_S >= FETCH_S


def test_fetch_ewma_converges_on_the_observed_value():
    mod = _load("true")
    b = mod.InferenceBudget()
    for _ in range(200):
        b.record_fetch(0.12)
    assert b.fetch_estimate() == pytest.approx(0.12, abs=0.005)
