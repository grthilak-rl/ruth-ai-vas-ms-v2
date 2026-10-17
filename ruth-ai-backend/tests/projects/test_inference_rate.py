"""The achieved-vs-requested inference rate summary.

Exists because the two numbers are far apart in production (measured 4% of
requested on HPCL) and only the requested one used to be visible. The
arithmetic has three edge cases that would each produce a nonsense figure
on screen, so each is pinned here.

`frames_processed` counts model *publications*, not ticks — see
InferenceLoop._add_session_counter — which is what makes it directly
comparable with `inference_fps x len(models)` without rescaling.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1.models import MIN_RATE_UPTIME_SECONDS, _inference_rate
from app.models import Device, StreamSession, StreamState

pytestmark = pytest.mark.skipif(
    not os.environ.get("PROJECT_TEST_DATABASE_URL"),
    reason="PROJECT_TEST_DATABASE_URL not set",
)


async def _device(db, name: str = "CAM") -> Device:
    d = Device(vas_device_id=f"vas-{uuid.uuid4()}", name=name, is_active=True, enabled=True)
    db.add(d)
    await db.flush()
    return d


async def _session(
    db,
    device,
    *,
    fps: int = 10,
    n_models: int = 3,
    frames: int = 0,
    uptime_s: float | None = 100.0,
    state: StreamState = StreamState.LIVE,
) -> StreamSession:
    started = (
        datetime.now(timezone.utc) - timedelta(seconds=uptime_s)
        if uptime_s is not None
        else None
    )
    s = StreamSession(
        device_id=device.id,
        model_id="safety_vest",
        inference_fps=fps,
        confidence_threshold=0.5,
        state=state,
        started_at=started,
        frames_processed=frames,
        models=[{"model_id": f"m{i}"} for i in range(n_models)] if n_models else None,
    )
    db.add(s)
    await db.flush()
    return s


async def test_requested_is_fps_times_models(db) -> None:
    d = await _device(db)
    await _session(db, d, fps=10, n_models=3, frames=0)
    await db.commit()

    r = await _inference_rate(db)
    assert r.cameras == 1
    assert r.model_slots == 3
    assert r.requested_per_second == 30.0


async def test_effective_is_publications_over_uptime(db) -> None:
    d = await _device(db)
    # 150 publications over 100s = 1.5/s.
    await _session(db, d, fps=10, n_models=3, frames=150, uptime_s=100.0)
    await db.commit()

    r = await _inference_rate(db)
    assert r.effective_per_second == pytest.approx(1.5, abs=0.05)
    # 1.5 of 30 requested.
    assert r.percent_of_requested == pytest.approx(5.0, abs=0.5)


async def test_a_just_started_session_is_skipped(db) -> None:
    """A fresh session's average is meaningless and wildly overstated.

    Guarding only on `uptime <= 0` does not work, because time always
    advances: this case first produced 72/s against a 30/s request (240%)
    from a session 0.07s old. Anything younger than
    MIN_RATE_UPTIME_SECONDS is omitted instead.
    """
    d = await _device(db)
    await _session(db, d, frames=5, uptime_s=0.0)
    await db.commit()

    r = await _inference_rate(db)
    assert r.cameras == 0
    assert r.effective_per_second == 0.0
    assert r.percent_of_requested is None


async def test_a_session_just_past_the_threshold_is_counted(db) -> None:
    """The guard must not silently swallow normal sessions."""
    d = await _device(db)
    uptime = MIN_RATE_UPTIME_SECONDS + 5.0
    await _session(db, d, fps=10, n_models=3, frames=int(uptime * 2), uptime_s=uptime)
    await db.commit()

    r = await _inference_rate(db)
    assert r.cameras == 1
    assert r.effective_per_second == pytest.approx(2.0, abs=0.2)


async def test_a_session_with_no_started_at_is_skipped(db) -> None:
    d = await _device(db)
    await _session(db, d, frames=100, uptime_s=None)
    await db.commit()

    r = await _inference_rate(db)
    assert r.cameras == 0


async def test_null_models_counts_as_one_model(db) -> None:
    """A legacy single-model session has models=NULL, not a 1-element list."""
    d = await _device(db)
    await _session(db, d, fps=4, n_models=0, frames=100, uptime_s=50.0)
    await db.commit()

    r = await _inference_rate(db)
    assert r.model_slots == 1
    assert r.requested_per_second == 4.0


async def test_only_live_sessions_count(db) -> None:
    d1 = await _device(db, "LIVE-CAM")
    d2 = await _device(db, "STOPPED-CAM")
    await _session(db, d1, frames=100, uptime_s=100.0)
    await _session(db, d2, frames=9999, uptime_s=100.0, state=StreamState.STOPPED)
    await db.commit()

    r = await _inference_rate(db)
    assert r.cameras == 1
    # The stopped session's 9999 frames must not inflate the live rate.
    assert r.effective_per_second == pytest.approx(1.0, abs=0.05)


async def test_nothing_live_is_all_zeros_not_an_error(db) -> None:
    r = await _inference_rate(db)
    assert (r.cameras, r.model_slots, r.requested_per_second, r.effective_per_second) == (
        0,
        0,
        0.0,
        0.0,
    )
    assert r.percent_of_requested is None


async def test_rates_sum_across_cameras(db) -> None:
    """The fleet figure is the sum, which is what the UI compares."""
    for i in range(3):
        d = await _device(db, f"CAM-{i}")
        await _session(db, d, fps=10, n_models=3, frames=100, uptime_s=100.0)
    await db.commit()

    r = await _inference_rate(db)
    assert r.cameras == 3
    assert r.model_slots == 9
    assert r.requested_per_second == 90.0
    assert r.effective_per_second == pytest.approx(3.0, abs=0.1)
