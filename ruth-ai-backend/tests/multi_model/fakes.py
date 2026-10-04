"""Fakes for driving the real InferenceLoopService against Postgres.

Deliberately imports nothing that exists only after M1, so the legacy golden
scenario can run unchanged against the pre-M1 code (HEAD) as well.
"""

import asyncio
import uuid
from collections import defaultdict
from types import SimpleNamespace
from typing import Any, Callable


def session_factory_for(sessionmaker):
    """An async-generator factory with get_db_session's commit/rollback semantics."""

    async def factory():
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return factory


class FakeVAS:
    def __init__(self, start_delay: float = 0.0):
        self.start_delay = start_delay

    async def start_stream(self, _vas_device_id: str):
        await asyncio.sleep(self.start_delay)
        return SimpleNamespace(v2_stream_id=str(uuid.uuid4()))

    async def create_snapshot(self, **_kwargs):
        return None

    async def get_streams(self, **_kwargs):
        return SimpleNamespace(streams=[])


class FakeRuntime:
    """Stands in for RuntimeRouter. Records every call; scripts every result.

    script(model_id, n) -> inference result dict for the n-th call of that
    model (0-based), or None to block forever (lets a test stop the loop at
    an exact call count).
    """

    def __init__(
        self,
        script: Callable[[str, int], dict | None],
        latency: float | dict[str, float] = 0.005,
    ):
        self.script = script
        # One latency for every model, or per model_id (default 0.005 s).
        self.latency = latency
        self.calls: list[dict[str, Any]] = []
        self.fetches: list[dict[str, Any]] = []
        self.count: dict[str, int] = defaultdict(int)
        self.in_flight: dict[str, int] = defaultdict(int)
        self.max_in_flight: dict[str, int] = defaultdict(int)
        self.on_call: Callable[[str, int], None] | None = None
        self._clock = None

    def _now(self) -> float:
        return asyncio.get_event_loop().time()

    async def _infer(self, kind: str, model_id: str, config, frame_id) -> dict[str, Any]:
        n = self.count[model_id]
        self.count[model_id] += 1
        if self.on_call is not None:
            self.on_call(model_id, n)
        call = {"kind": kind, "model_id": model_id, "n": n, "config": config, "t": self._now(), "frame": frame_id}
        self.calls.append(call)
        result = self.script(model_id, n)
        if result is None:
            await asyncio.Event().wait()  # park forever; the test stops the loop
        self.in_flight[model_id] += 1
        self.max_in_flight[model_id] = max(self.max_in_flight[model_id], self.in_flight[model_id])
        latency = self.latency.get(model_id, 0.005) if isinstance(self.latency, dict) else self.latency
        try:
            await asyncio.sleep(latency)
        finally:
            self.in_flight[model_id] -= 1
        call["end"] = self._now()
        return {
            "request_id": str(uuid.uuid4()),
            "status": "success",
            "model_id": model_id,
            "model_version": "1.0.0",
            "inference_time_ms": latency * 1000,
            "result": result,
            "error": None,
            "frame_width": 1920,
            "frame_height": 1080,
            "frame_id": frame_id,  # lets tests tie a published result to its tick
        }

    # Legacy single-model path (unchanged API).
    async def submit_inference(self, model_id, stream_id, device_id=None, model_version=None,
                               timestamp=None, priority=0, metadata=None, config=None):
        return await self._infer("legacy", model_id, config, None)

    # Shared-frame path (M1).
    async def fetch_frame(self, stream_id, device_id=None):
        frame = SimpleNamespace(id=len(self.fetches), width=1920, height=1080)
        self.fetches.append({"t": self._now(), "frame": frame.id})
        return frame

    async def submit_inference_with_frame(self, model_id, frame_data, stream_id, device_id=None,
                                          model_version=None, timestamp=None, priority=0,
                                          metadata=None, config=None):
        return await self._infer("multi", model_id, config, frame_data.id)

    def calls_for(self, model_id: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["model_id"] == model_id]


def result(violation: bool, confidence: float = 0.9, label: str = "x") -> dict[str, Any]:
    return {
        "violation_detected": violation,
        "violation_type": label if violation else None,
        "confidence": confidence if violation else 0.1,
        "detections": [{"bbox": [10, 20, 110, 220], "confidence": confidence}] if violation else [],
    }


async def stop_loop(loop) -> None:
    """What InferenceLoopService.stop() intends, without its pre-existing bug.

    stop() iterates self._session_tasks.items() while awaiting each cancelled
    task, and each task's own exit cleanup pops its entry from that dict, so
    the next iteration raises "dictionary changed size during iteration" and
    the main-loop task is never cancelled. Fixed in stop() itself (see
    tests/multi_model/test_loop_shutdown.py); this helper stays because the
    golden scenario must also stop the pre-fix code identically.
    """
    loop._running = False
    tasks = list(loop._session_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.wait(tasks)
    if loop._task is not None:
        loop._task.cancel()
        await asyncio.wait({loop._task})


async def wait_for(condition: Callable[[], bool], timeout: float = 5.0, step: float = 0.01) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while not condition():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(step)
