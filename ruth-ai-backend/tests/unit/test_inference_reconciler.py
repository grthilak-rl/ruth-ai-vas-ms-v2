"""Auto-resume: what it does, and more importantly what it refuses to do.

BL-11 A. Camera 74004 ran 21.3 hours with live video and no inference
because nothing recorded that anyone had asked for inference, so nothing
could put it back.

The dangerous failure here is not "failed to resume" — that is visible.
It is resuming something an operator deliberately stopped, or parking the
whole fleet during a network blip so that recovery is unavailable exactly
when it is needed. Those cases get the most tests.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.inference_intent import (
    BACKOFF_MINUTES,
    PARK_AFTER_FAILURES,
    backoff_for,
    is_parked,
    may_attempt,
    retry_due_at,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def intent(**kw):
    """A desired-active intent with sane defaults."""
    base = dict(
        device_id=uuid4(),
        desired_state="active",
        models=[{"model_id": "safety_vest", "model_version": None, "config": None}],
        inference_fps=2,
        confidence_threshold=0.7,
        consecutive_failures=0,
        last_attempt_at=None,
        last_error=None,
        updated_at=NOW - timedelta(hours=1),
        updated_by="operator",
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Parking and backoff (pure, so tested directly)
# ---------------------------------------------------------------------------


def test_not_parked_before_the_threshold():
    assert is_parked(intent(consecutive_failures=PARK_AFTER_FAILURES - 1)) is False


def test_parked_at_the_threshold():
    assert is_parked(intent(consecutive_failures=PARK_AFTER_FAILURES)) is True


def test_backoff_schedule_is_capped_and_repeats():
    """5 -> 15 -> 60, then 60 for ever. A parked camera is retried
    indefinitely, just not often."""
    got = [
        backoff_for(PARK_AFTER_FAILURES + i).total_seconds() / 60
        for i in range(5)
    ]
    assert got == [5, 15, 60, 60, 60]
    assert got[: len(BACKOFF_MINUTES)] == list(BACKOFF_MINUTES)


def test_backoff_is_zero_before_parking():
    assert backoff_for(0) == timedelta(0)
    assert backoff_for(PARK_AFTER_FAILURES - 1) == timedelta(0)


def test_parked_camera_waits_for_its_backoff():
    i = intent(consecutive_failures=PARK_AFTER_FAILURES, last_attempt_at=NOW)
    assert may_attempt(i, NOW + timedelta(minutes=4)) is False
    assert may_attempt(i, NOW + timedelta(minutes=5)) is True


def test_retry_due_at_is_none_when_not_parked():
    assert retry_due_at(intent(consecutive_failures=0, last_attempt_at=NOW)) is None


# ---------------------------------------------------------------------------
# The cycle
# ---------------------------------------------------------------------------


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class FakeDB:
    """Enough session for reconcile_once: two selects and a commit."""

    def __init__(self, intents, running_ids):
        self._intents = intents
        self._running = running_ids
        self.committed = False
        self._call = 0

    async def execute(self, _stmt):
        self._call += 1
        # First select: intents joined to devices. Second: running sessions.
        if self._call == 1:
            return FakeResult(self._intents)
        return FakeResult(list(self._running))

    async def commit(self):
        self.committed = True

    async def flush(self):
        pass


def device(name="75096", device_id=None, video="live", active=True, vas_enabled=None):
    """A Ruth device row, plus what VAS will say about it.

    `vas_enabled` defaults to the Ruth value so most tests do not have to
    think about the two being separate — the cases where they diverge are
    the point of the disable/re-enable tests.
    """
    return SimpleNamespace(
        id=device_id or uuid4(),
        name=name,
        vas_device_id=f"vas-{name}",
        is_active=active,
        enabled=active,
        _video=video,
        _vas_enabled=active if vas_enabled is None else vas_enabled,
    )


class FakeVAS:
    def __init__(self, devices, raise_on_list=False):
        self._devices = devices
        self._raise = raise_on_list

    async def get_devices(self):
        if self._raise:
            raise ConnectionError("VAS unreachable")
        return [
            SimpleNamespace(
                id=d.vas_device_id,
                video_state=d._video,
                enabled=d._vas_enabled,
                is_active=d._vas_enabled,
            )
            for d in self._devices
        ]


class FakeStreamService:
    def __init__(self, fail_with=None):
        self.started = []
        self.stopped = []
        self._fail = fail_with

    async def stop_inference(self, device_id):
        self.stopped.append(device_id)

    async def start_stream(self, device_id, **kw):
        if self._fail:
            raise self._fail
        self.started.append((device_id, kw))
        return SimpleNamespace(models=None, models_revision=0)


def build(intents_and_devices, running=(), vas_raises=False, start_fails=None):
    from app.services.inference_reconciler import InferenceReconciler

    devices = [d for _i, d in intents_and_devices]
    db = FakeDB(intents_and_devices, running)
    streams = FakeStreamService(fail_with=start_fails)

    # An async *generator*, like app.core.database.get_db_session: the
    # reconciler wraps it in asynccontextmanager so a failure reaches the
    # generator's except branch. A fake that is already a context manager
    # would let a bug in that wrapping pass unnoticed.
    async def session_factory():
        yield db

    rec = InferenceReconciler(
        db_session_factory=session_factory,
        stream_service_factory=lambda _db: streams,
        vas_client=FakeVAS(devices, raise_on_list=vas_raises),
        interval_seconds=60,
    )
    return rec, db, streams


@pytest.mark.asyncio
async def test_resumes_a_camera_whose_session_died():
    d = device()
    i = intent(device_id=d.id)
    rec, db, streams = build([(i, d)], running=[])
    out = await rec.reconcile_once()
    assert out.resumed == ["75096"]
    assert len(streams.started) == 1
    assert i.consecutive_failures == 0
    assert db.committed


@pytest.mark.asyncio
async def test_leaves_a_running_camera_alone():
    d = device()
    i = intent(device_id=d.id)
    rec, _db, streams = build([(i, d)], running=[d.id])
    out = await rec.reconcile_once()
    assert out.resumed == [] and streams.started == []


@pytest.mark.asyncio
async def test_an_operator_stop_is_never_resumed():
    """desired_state 'off' is excluded by the query itself, so there is no
    path by which a stopped camera is restarted."""
    rec, _db, streams = build([], running=[])
    out = await rec.reconcile_once()
    assert out.checked == 0 and streams.started == []


@pytest.mark.asyncio
async def test_video_offline_is_not_a_failure():
    """The camera-offline case. Counting it would park the fleet during a
    site link flap — exactly when recovery matters most."""
    d = device(video="offline")
    i = intent(device_id=d.id)
    rec, _db, streams = build([(i, d)], running=[])
    out = await rec.reconcile_once()
    assert out.skipped_no_video == ["75096"]
    assert out.failed == [] and streams.started == []
    assert i.consecutive_failures == 0


@pytest.mark.asyncio
async def test_resumes_once_video_comes_back():
    d = device(video="offline")
    i = intent(device_id=d.id)
    rec, _db, streams = build([(i, d)], running=[])
    await rec.reconcile_once()
    assert streams.started == []

    d._video = "live"
    rec2, _db2, streams2 = build([(i, d)], running=[])
    out = await rec2.reconcile_once()
    assert out.resumed == ["75096"] and len(streams2.started) == 1


@pytest.mark.asyncio
async def test_vas_down_parks_nobody():
    """A shared dependency is one system problem, not twelve camera
    problems. The cycle is skipped whole and nothing is counted."""
    pairs = [(intent(device_id=uuid4()), device(name=f"cam{i}")) for i in range(3)]
    for i, (it, d) in enumerate(pairs):
        it.device_id = d.id
    rec, _db, streams = build(pairs, running=[], vas_raises=True)
    out = await rec.reconcile_once()
    assert out.dependency_error is not None
    assert out.failed == [] and out.parked == [] and streams.started == []
    assert all(it.consecutive_failures == 0 for it, _d in pairs)


@pytest.mark.asyncio
async def test_a_real_failure_counts_and_parks_on_the_second():
    d = device()
    i = intent(device_id=d.id)
    rec, _db, _s = build([(i, d)], running=[], start_fails=RuntimeError("no runtime"))
    out = await rec.reconcile_once()
    assert out.failed == ["75096"]
    assert i.consecutive_failures == 1 and not is_parked(i)

    rec2, _db2, _s2 = build([(i, d)], running=[], start_fails=RuntimeError("no runtime"))
    out2 = await rec2.reconcile_once()
    assert i.consecutive_failures == 2 and is_parked(i)
    assert "75096" in out2.parked
    assert "no runtime" in i.last_error


@pytest.mark.asyncio
async def test_a_parked_camera_is_skipped_until_its_backoff_expires():
    d = device()
    i = intent(
        device_id=d.id,
        consecutive_failures=PARK_AFTER_FAILURES,
        last_attempt_at=datetime.now(timezone.utc),
    )
    rec, _db, streams = build([(i, d)], running=[])
    out = await rec.reconcile_once()
    assert out.parked == ["75096"] and streams.started == []


@pytest.mark.asyncio
async def test_grace_period_after_an_intent_change():
    """The picker writes intent, then starts a session a moment later.
    Without the grace window the reconciler sees the gap and races it."""
    d = device()
    i = intent(device_id=d.id, updated_at=datetime.now(timezone.utc))
    rec, _db, streams = build([(i, d)], running=[])
    out = await rec.reconcile_once()
    assert out.skipped_grace == ["75096"] and streams.started == []


@pytest.mark.asyncio
async def test_disabled_cameras_are_never_touched():
    d = device(active=False)
    i = intent(device_id=d.id)
    rec, _db, streams = build([(i, d)], running=[])
    out = await rec.reconcile_once()
    assert out.checked == 0 and streams.started == []


@pytest.mark.asyncio
async def test_success_clears_a_previous_failure_count():
    d = device()
    i = intent(device_id=d.id, consecutive_failures=1, last_error="earlier")
    rec, _db, _s = build([(i, d)], running=[])
    await rec.reconcile_once()
    assert i.consecutive_failures == 0 and i.last_error is None


@pytest.mark.asyncio
async def test_a_recovered_camera_stops_being_parked():
    """It came back on its own — by a picker action, say. The failure
    history has to clear or it stays parked for ever."""
    d = device()
    i = intent(device_id=d.id, consecutive_failures=PARK_AFTER_FAILURES)
    rec, _db, _s = build([(i, d)], running=[d.id])
    await rec.reconcile_once()
    assert i.consecutive_failures == 0 and not is_parked(i)


@pytest.mark.asyncio
async def test_restores_every_model_not_just_the_first():
    """start_stream only knows about one model; the session is
    multi-model, so a resume that kept only models[0] would silently drop
    the rest."""
    d = device()
    models = [
        {"model_id": "safety_vest", "model_version": None, "config": None},
        {"model_id": "hard_hat", "model_version": None, "config": None},
        {"model_id": "gloves_2", "model_version": None, "config": None},
    ]
    i = intent(device_id=d.id, models=models)
    rec, _db, streams = build([(i, d)], running=[])
    out = await rec.reconcile_once()
    assert out.resumed == ["75096"]
    # the first model seeds start_stream...
    assert streams.started[0][1]["model_id"] == "safety_vest"


@pytest.mark.asyncio
async def test_active_intent_with_no_models_is_a_failure_not_a_crash():
    d = device()
    i = intent(device_id=d.id, models=[])
    rec, _db, _s = build([(i, d)], running=[])
    out = await rec.reconcile_once()
    assert out.failed == ["75096"]
    assert "no models recorded" in i.last_error


# ---------------------------------------------------------------------------
# Disabled in VAS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabling_in_vas_stops_the_session_within_one_cycle():
    """Nothing else stops inference when a camera is disabled, so it would
    otherwise keep running on a camera nobody can see."""
    d = device(vas_enabled=False)
    i = intent(device_id=d.id)
    rec, _db, streams = build([(i, d)], running=[d.id])
    out = await rec.reconcile_once()
    assert out.suspended == ["75096"]
    assert streams.stopped == [d.id]
    assert i.desired_state == "suspended"


@pytest.mark.asyncio
async def test_suspending_keeps_the_models():
    """The whole point: re-enabling must restore the same analysis without
    anyone having to remember what was running."""
    models = [
        {"model_id": "hard_hat", "model_version": None, "config": None},
        {"model_id": "gloves_2", "model_version": None, "config": None},
    ]
    d = device(vas_enabled=False)
    i = intent(device_id=d.id, models=models)
    rec, _db, _s = build([(i, d)], running=[d.id])
    await rec.reconcile_once()
    assert i.desired_state == "suspended"
    assert i.models == models


@pytest.mark.asyncio
async def test_re_enabling_resumes_the_same_models():
    d = device(vas_enabled=False)
    models = [{"model_id": "hard_hat", "model_version": None, "config": None}]
    i = intent(device_id=d.id, models=models)
    rec, _db, streams = build([(i, d)], running=[d.id])
    await rec.reconcile_once()
    assert i.desired_state == "suspended"

    # VAS says it is back.
    d._vas_enabled = True
    d.enabled = True
    d.is_active = True
    i.updated_at = NOW - timedelta(hours=1)  # past the grace window
    rec2, _db2, streams2 = build([(i, d)], running=[])
    out = await rec2.reconcile_once()
    assert out.unsuspended == ["75096"]
    assert out.resumed == ["75096"]
    assert streams2.started[0][1]["model_id"] == "hard_hat"
    assert i.desired_state == "active"


@pytest.mark.asyncio
async def test_enabled_is_refreshed_from_the_cycles_own_vas_call():
    """No separate device sync: a camera disabled in VAS used to stay
    'enabled' in Ruth until startup or a manual sync."""
    d = device(vas_enabled=False)
    assert d.enabled is True  # Ruth's stale view
    i = intent(device_id=d.id)
    rec, _db, _s = build([(i, d)], running=[])
    await rec.reconcile_once()
    assert d.enabled is False


@pytest.mark.asyncio
async def test_operator_off_is_still_never_resumed_even_when_enabled():
    """suspended and off must not be confused: only one comes back."""
    d = device()
    i = intent(device_id=d.id, desired_state="off")
    # 'off' rows are excluded by the query, so the reconciler never sees it.
    rec, _db, streams = build([], running=[])
    out = await rec.reconcile_once()
    assert out.checked == 0 and out.unsuspended == [] and streams.started == []


@pytest.mark.asyncio
async def test_a_camera_missing_from_vas_is_not_treated_as_disabled():
    """Unknown is not False. VAS failing to list a camera must not look
    the same as an operator deleting it."""
    d = device()
    i = intent(device_id=d.id)
    rec, _db, streams = build([(i, d)], running=[])
    rec._vas._devices = []  # VAS returns nothing for this camera
    out = await rec.reconcile_once()
    assert out.suspended == []
    assert i.desired_state == "active"
    # no video known either, so it is skipped rather than failed
    assert out.failed == [] and streams.stopped == []
