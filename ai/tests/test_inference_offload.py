"""RUTH_RUNTIME_OFFLOAD_INFERENCE: the flag, and the promise that it is off.

See docs/BACKLOG.md BL-5. The fix for the runtime serialising all inference
is to await `sandbox_manager.execute` on a worker thread instead of calling
it inline on the event loop. That is a change to a path shared by the
built-in runtime (5 models, every deployment) and the model-store runtime,
so it ships behind a flag that is enabled per service.

The load-bearing test here is the *negative* one: with the flag off, the
built-in path must be byte-identical to what shipped — same call, same
arguments, same result, and demonstrably NOT routed through a thread. A
flag that quietly changes the default would defeat the point of having it.

The module reads the environment once at import, so each test reloads it
under a patched environment rather than trying to mutate a constant.
"""

import asyncio
import importlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def _load_module(offload: str | None):
    """Import ai.server.routes.inference with the flag set as given."""
    env = dict(os.environ)
    env.pop("RUTH_RUNTIME_OFFLOAD_INFERENCE", None)
    if offload is not None:
        env["RUTH_RUNTIME_OFFLOAD_INFERENCE"] = offload
    with patch.dict(os.environ, env, clear=True):
        import ai.server.routes.inference as mod

        return importlib.reload(mod)


# -----------------------------------------------------------------------------
# The flag itself
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "On"])
def test_flag_enables_on_truthy_values(value):
    assert _load_module(value).OFFLOAD_INFERENCE is True


@pytest.mark.parametrize("value", [None, "", "0", "false", "no", "off", "maybe"])
def test_flag_defaults_off_and_stays_off(value):
    """Anything that is not explicitly truthy leaves the original path.

    Including nonsense like "maybe": an unparseable value must not be read
    as consent to change a shared runtime path.
    """
    assert _load_module(value).OFFLOAD_INFERENCE is False


def test_unset_is_off():
    """The deployed default. The built-in runtime sets nothing."""
    assert _load_module(None).OFFLOAD_INFERENCE is False


# -----------------------------------------------------------------------------
# Behaviour: off == unchanged
# -----------------------------------------------------------------------------


class _Result:
    success = True
    output = {"detections": [], "marker": "sentinel"}
    error = None


def _wire(mod, model_id="fall_detection"):
    """Minimal registry/sandbox doubles so submit_inference reaches execute.

    The route matches on `version.model_id` and gates on
    `version.state.is_available()`, so both have to be real enough.
    """
    version = MagicMock()
    version.model_id = model_id
    version.version = "1.0.0"
    version.state.is_available.return_value = True

    registry = MagicMock()
    registry.get_all_versions.return_value = [version]
    registry.get_version.return_value = version

    sandbox = MagicMock()
    sandbox.execute.return_value = _Result()

    return registry, sandbox


def _request(mod):
    """A minimal valid request: the frame must clear MIN_FRAME_WIDTH/HEIGHT."""
    import base64
    import io
    from datetime import datetime, timezone

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (255, 255, 255)).save(buf, format="JPEG")
    return mod.InferenceRequest(
        model_id="fall_detection",
        stream_id="11111111-1111-1111-1111-111111111111",
        frame_base64=base64.b64encode(buf.getvalue()).decode(),
        frame_format="jpeg",
        timestamp=datetime.now(timezone.utc),
    )


def _call(mod, monkeypatch, *, expect_thread: bool):
    registry, sandbox = _wire(mod)
    monkeypatch.setattr(mod, "get_registry", lambda: registry)
    monkeypatch.setattr(mod, "get_sandbox_manager", lambda: sandbox)
    monkeypatch.setattr(mod, "get_pipeline", lambda: MagicMock(), raising=False)

    used_thread = {"yes": False}
    real_to_thread = asyncio.to_thread

    async def spy_to_thread(fn, /, *a, **kw):
        used_thread["yes"] = True
        return await real_to_thread(fn, *a, **kw)

    monkeypatch.setattr(mod.asyncio, "to_thread", spy_to_thread)

    try:
        asyncio.run(mod.submit_inference(_request(mod)))
    except Exception as exc:  # noqa: BLE001
        # Response assembly may need more of the app than is wired here.
        # Tolerated, but only AFTER execute: a failure before it means the
        # test is not exercising the branch at all, and the call_count
        # assertions below catch that rather than passing vacuously.
        if sandbox.execute.call_count == 0:
            raise AssertionError(
                f"submit_inference failed before reaching execute: {exc!r}"
            ) from exc

    assert used_thread["yes"] is expect_thread, (
        f"expected to_thread used={expect_thread}, got {used_thread['yes']}"
    )
    return sandbox


def test_flag_off_calls_execute_inline(monkeypatch):
    """The shipped path: no thread hand-off at all."""
    mod = _load_module(None)
    sandbox = _call(mod, monkeypatch, expect_thread=False)
    assert sandbox.execute.call_count == 1


def test_flag_on_calls_execute_on_a_thread(monkeypatch):
    mod = _load_module("true")
    sandbox = _call(mod, monkeypatch, expect_thread=True)
    assert sandbox.execute.call_count == 1


def test_execute_receives_identical_arguments_either_way(monkeypatch):
    """Byte-identical call, not merely a successful one.

    The offload must be a pure scheduling change. If the two branches ever
    drift — a renamed kwarg, a dropped config — this catches it, because
    the only legitimate difference is which thread runs the call.
    """
    off = _call(_load_module(None), monkeypatch, expect_thread=False)
    on = _call(_load_module("true"), monkeypatch, expect_thread=True)

    off_args = off.execute.call_args
    on_args = on.execute.call_args

    assert off_args.args == on_args.args
    assert set(off_args.kwargs) == set(on_args.kwargs)

    # request_id is a fresh uuid4 per call, so it differs by construction.
    # Assert it is still passed and well-formed rather than that it matches.
    import uuid as _uuid

    for args in (off_args, on_args):
        _uuid.UUID(args.kwargs["request_id"])

    for key in off_args.kwargs:
        if key == "request_id":
            continue
        if key == "frame":
            # numpy array: compare shape rather than identity.
            assert off_args.kwargs[key].shape == on_args.kwargs[key].shape
        else:
            assert off_args.kwargs[key] == on_args.kwargs[key], f"differs: {key}"


@pytest.mark.parametrize("offload", [None, "true"])
def test_a_failed_execution_is_reported_the_same_either_way(monkeypatch, offload):
    """A failed ExecutionResult must stay a failure through the hand-off.

    `execute` signals inference failure by RETURNING success=False, not by
    raising, and the route converts that into a response with
    status="failed" rather than an exception. Both details matter: if the
    offload branch ever lost the error, a broken model would start
    reporting success.
    """
    mod = _load_module(offload)
    registry, sandbox = _wire(mod)

    failed = MagicMock()
    failed.success = False
    failed.output = None
    failed.error = "boom"
    sandbox.execute.return_value = failed

    monkeypatch.setattr(mod, "get_registry", lambda: registry)
    monkeypatch.setattr(mod, "get_sandbox_manager", lambda: sandbox)
    monkeypatch.setattr(mod, "get_pipeline", lambda: MagicMock(), raising=False)

    response = asyncio.run(mod.submit_inference(_request(mod)))

    assert sandbox.execute.call_count == 1
    assert response.status == "failed"
    assert response.error and "boom" in response.error


# -----------------------------------------------------------------------------
# The startup report
# -----------------------------------------------------------------------------


def test_offload_status_reports_the_flag():
    """main.py logs this after configure_logging(), not at import.

    A module-level logger.info in this file is dropped: `ai.server.main`
    imports the routes before the lifespan configures logging, so the
    record goes nowhere. That happened once in a real deploy — the flag
    was active and the confirmation line never printed, which reads
    exactly like the flag failing. The value is exposed instead and logged
    where logging works.
    """
    on = _load_module("true").offload_status()
    off = _load_module(None).offload_status()

    assert on["offload_to_thread"] is True
    assert off["offload_to_thread"] is False
    # Names the variable, so the log line says how to change it.
    assert on["env"] == "RUTH_RUNTIME_OFFLOAD_INFERENCE"
