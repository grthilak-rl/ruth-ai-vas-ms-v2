"""VAS Stream Event Consumer.

Consumes lifecycle events published by VAS on Redis Streams
(key: "vas:stream_events") and drives local activation/pause.

Design:
    - Uses a dedicated Redis connection to VAS_REDIS_URL (not the
      Ruth AI redis) so the two systems stay decoupled.
    - Persists the last-read stream ID in Ruth AI's own Redis under the
      key "vas:last_event_id", so restarts resume without replay/loss.
    - Reads with XREAD BLOCK 5000 (5s blocking) — no busy polling.
    - On connection errors: exponential backoff 1s -> 2s -> 4s ... max 30s.
    - Non-fatal: if VAS_REDIS_URL is empty or unreachable, log a warning
      and keep retrying — Ruth AI never crashes over this.

Events consumed (see vas-ms-v2/backend/app/services/stream_supervisor.py):
    stream.started   -> activate(stream_id)
    stream.stopped   -> pause(stream_id)
    stream.crashed   -> pause(stream_id)
    stream.failed    -> pause(stream_id)
    stream.restarted -> activate(stream_id)   (treat as fresh start)
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis_client

logger = get_logger(__name__)

VAS_STREAM_KEY = "vas:stream_events"
LAST_ID_KEY = "vas:last_event_id"
BLOCK_MS = 5000           # XREAD BLOCK 5s
BACKOFF_BASE_SEC = 1.0
BACKOFF_MAX_SEC = 30.0

# Events that mean "stream should be running"
ACTIVATE_EVENTS = {"stream.started", "stream.restarted"}
# Events that mean "stream should be paused/off"
PAUSE_EVENTS = {"stream.stopped", "stream.crashed", "stream.failed"}


class VASEventConsumer:
    """Background task that tails vas:stream_events on VAS's Redis."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._vas_redis: Optional[aioredis.Redis] = None
        self._running = False

    # ---------- lifecycle ----------

    async def start(self) -> None:
        """Run the consumer loop. Safe to launch as a fire-and-forget task."""
        if self._running:
            return
        self._running = True

        vas_url = (self._settings.vas_redis_url or "").strip()
        if not vas_url:
            logger.info(
                "VAS event consumer disabled (VAS_REDIS_URL not set) — "
                "Ruth AI will not react to VAS stream events"
            )
            self._running = False
            return

        logger.info("VAS event consumer starting", vas_redis_url=vas_url)

        backoff = BACKOFF_BASE_SEC
        while self._running:
            try:
                await self._run_once(vas_url)
                # Clean exit path — only when self._running flips to False
                break
            except asyncio.CancelledError:
                break
            except (RedisError, ConnectionError, OSError) as e:
                logger.warning(
                    "VAS event consumer connection error — will retry",
                    error=str(e),
                    backoff_sec=backoff,
                )
            except Exception as e:
                logger.exception(
                    "VAS event consumer unexpected error — will retry",
                    error=str(e),
                )
            # Backoff before retry
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                break
            backoff = min(backoff * 2, BACKOFF_MAX_SEC)

        logger.info("VAS event consumer stopped")

    async def stop(self) -> None:
        self._running = False
        if self._vas_redis is not None:
            try:
                await self._vas_redis.aclose()
            except Exception:
                pass
            self._vas_redis = None

    # ---------- main loop ----------

    async def _run_once(self, vas_url: str) -> None:
        """One connected session: read last-id, loop XREAD, process events."""
        # Fresh connection per attempt so transient DNS/TCP failures are clean.
        self._vas_redis = aioredis.from_url(vas_url, decode_responses=True)
        await self._vas_redis.ping()
        logger.info("VAS event consumer connected")

        last_id = await self._load_last_id()
        logger.info("VAS event consumer resuming", from_id=last_id)

        while self._running:
            try:
                resp = await self._vas_redis.xread(
                    streams={VAS_STREAM_KEY: last_id},
                    block=BLOCK_MS,
                    count=32,
                )
            except asyncio.CancelledError:
                raise
            if not resp:
                # Block expired with no new entries — loop and block again.
                continue

            # resp = [(stream_key, [(entry_id, {field: value, ...}), ...])]
            for _stream_key, entries in resp:
                for entry_id, fields in entries:
                    try:
                        await self._handle_event(entry_id, fields)
                    except Exception as e:
                        logger.exception(
                            "Error processing VAS event — continuing",
                            entry_id=entry_id,
                            error=str(e),
                        )
                    last_id = entry_id
                    await self._save_last_id(last_id)

    async def _handle_event(self, entry_id: str, fields: Dict[str, Any]) -> None:
        event = fields.get("event") or ""
        stream_id = fields.get("stream_id") or ""
        room_id = fields.get("room_id") or stream_id
        timestamp = fields.get("timestamp") or ""
        status = fields.get("status") or ""

        logger.info(
            "VAS event received",
            entry_id=entry_id,
            event_type=event,
            stream_id=stream_id,
            room_id=room_id,
            vas_status=status,
            vas_timestamp=timestamp,
        )

        # Late-import to avoid circular import at module load time
        from app.services.inference_loop import get_inference_loop

        loop = get_inference_loop()
        if loop is None:
            logger.debug("Inference loop not initialized — event noted only")
            return

        if event in ACTIVATE_EVENTS:
            await loop.activate(stream_id)
        elif event in PAUSE_EVENTS:
            await loop.pause(stream_id)
        else:
            logger.debug("Ignoring VAS event type", event=event)

    # ---------- last-id persistence (Ruth AI redis) ----------

    async def _load_last_id(self) -> str:
        client = get_redis_client()
        if client is None:
            return "$"  # Only new entries from now
        try:
            val = await client.get(LAST_ID_KEY)
            return val or "$"
        except RedisError:
            logger.warning(
                "Could not read VAS last_id from Ruth AI redis — starting from $"
            )
            return "$"

    async def _save_last_id(self, entry_id: str) -> None:
        client = get_redis_client()
        if client is None:
            return
        try:
            await client.set(LAST_ID_KEY, entry_id)
        except RedisError as e:
            logger.warning("Could not persist VAS last_id", error=str(e))


# Module-level singleton
vas_event_consumer = VASEventConsumer()
