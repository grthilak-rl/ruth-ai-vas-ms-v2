"""Redis client initialization and management.

Provides:
- Async Redis client creation with connection pooling
- Health check function
- Graceful shutdown handling
"""

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Global Redis client (initialized during lifespan)
_redis_client: Redis | None = None
_connection_pool: ConnectionPool | None = None


def get_redis_client() -> Redis | None:
    """Get the Redis client instance.

    Returns None if not initialized.
    """
    return _redis_client


async def init_redis() -> Redis:
    """Initialize the Redis client with connection pooling.

    Called during application startup.

    Returns:
        Configured Redis async client
    """
    global _redis_client, _connection_pool

    settings = get_settings()

    logger.info(
        "Initializing Redis connection",
        url=str(settings.redis_url).replace(
            settings.redis_url.password or "", "***"
        )
        if settings.redis_url.password
        else str(settings.redis_url),
        max_connections=settings.redis_max_connections,
    )

    # Create connection pool
    _connection_pool = ConnectionPool.from_url(
        str(settings.redis_url),
        max_connections=settings.redis_max_connections,
        decode_responses=True,
    )

    # Create Redis client with the pool
    _redis_client = Redis(connection_pool=_connection_pool)

    # Verify connection
    try:
        await _redis_client.ping()
        logger.info("Redis connection initialized successfully")
    except RedisError as e:
        logger.warning(
            "Redis connection failed during initialization",
            error=str(e),
        )
        # Don't raise - Redis may be optional for some operations

    return _redis_client


async def close_redis() -> None:
    """Close Redis connections.

    Called during application shutdown.
    """
    global _redis_client, _connection_pool

    if _redis_client is not None:
        logger.info("Closing Redis connections")
        try:
            await _redis_client.aclose()
        except Exception as e:
            logger.error("Error closing Redis client", error=str(e))
        finally:
            _redis_client = None

    if _connection_pool is not None:
        try:
            await _connection_pool.disconnect()
        except Exception as e:
            logger.error("Error disconnecting Redis pool", error=str(e))
        finally:
            _connection_pool = None

        logger.info("Redis connections closed")


async def check_redis_health() -> tuple[bool, str | None]:
    """Check Redis connectivity.

    Returns:
        Tuple of (is_healthy, error_message)
    """
    if _redis_client is None:
        return False, "Redis not initialized"

    try:
        pong = await _redis_client.ping()
        if pong:
            return True, None
        return False, "PING returned False"
    except RedisError as e:
        logger.error("Redis health check failed", error=str(e))
        return False, str(e)
    except Exception as e:
        logger.error("Redis health check failed unexpectedly", error=str(e))
        return False, str(e)
