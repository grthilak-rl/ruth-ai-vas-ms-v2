"""Tiny Redis-backed TTL cache helper.

Used for short-TTL caching of expensive composed responses (the
/api/v1/devices endpoint is the first caller). The goal is to absorb
concurrent requests for the same data within a few seconds — not
long-term persistence — so the API surface is intentionally minimal.

Failure mode: every operation is best-effort. If Redis is unreachable
or any error occurs the helpers degrade silently (get returns None,
set is a no-op) and the caller computes the value the slow way.
"""

from __future__ import annotations

import json
from typing import Any

from redis.exceptions import RedisError

from app.core.logging import get_logger
from app.core.redis import get_redis_client

logger = get_logger(__name__)


async def cache_get_json(key: str) -> Any | None:
    """Return the JSON-decoded value at ``key`` or None on miss / error."""
    client = get_redis_client()
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except RedisError as e:
        logger.debug("cache_get_json failed", key=key, error=str(e))
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as e:
        logger.warning("cache value not valid JSON, discarding", key=key, error=str(e))
        return None


async def cache_set_json(key: str, value: Any, ttl_seconds: int) -> None:
    """Store ``value`` as JSON with the given TTL. Silent on error."""
    client = get_redis_client()
    if client is None:
        return
    try:
        await client.set(key, json.dumps(value, default=str), ex=ttl_seconds)
    except (RedisError, TypeError, ValueError) as e:
        logger.debug("cache_set_json failed", key=key, error=str(e))


async def cache_delete(*keys: str) -> None:
    """Delete one or more keys. Silent on error."""
    if not keys:
        return
    client = get_redis_client()
    if client is None:
        return
    try:
        await client.delete(*keys)
    except RedisError as e:
        logger.debug("cache_delete failed", keys=keys, error=str(e))


# Well-known cache keys.
DEVICES_LIST_CACHE_KEY = "ruth:devices:list"
DEVICES_LIST_CACHE_TTL_SECONDS = 5
