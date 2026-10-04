"""InferenceLoopService.stop() with several active sessions.

Each session task removes its own entry from _session_tasks when it exits
(including on cancellation). stop() used to iterate that dict while awaiting
the cancelled tasks, so with any active session it raised "dictionary changed
size during iteration" and never cancelled the main loop. DB-free; the
real-loop version is in tests/multi_model/test_loop_shutdown.py.
"""

import asyncio
from unittest.mock import MagicMock

from app.services.inference_loop import InferenceLoopService


def _self_removing_task(loop: InferenceLoopService, key) -> asyncio.Task:
    """Mimics a session task's exit cleanup: pops its own entry on exit."""

    async def run():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            loop._session_tasks.pop(key, None)

    return asyncio.create_task(run())


async def test_stop_with_three_active_sessions_does_not_raise():
    loop = InferenceLoopService(
        runtime_router=MagicMock(), vas_client=MagicMock(), db_session_factory=MagicMock()
    )
    loop._running = True
    main = asyncio.create_task(asyncio.Event().wait())
    loop._task = main
    tasks = {f"session-{i}": None for i in range(3)}
    for key in tasks:
        tasks[key] = _self_removing_task(loop, key)
        loop._session_tasks[key] = tasks[key]
    await asyncio.sleep(0)  # let the tasks start

    await loop.stop()  # raised RuntimeError before the fix

    assert all(t.done() for t in tasks.values())
    assert loop._session_tasks == {}
    assert main.cancelled()  # the main loop is cancelled too
    assert loop._running is False
