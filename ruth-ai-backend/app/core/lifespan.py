"""Application startup and shutdown lifecycle management.

Provides:
- Lifespan context manager for FastAPI
- Startup hooks (database init, Redis init, VAS client init, NLP Chat client init)
- Shutdown hooks (cleanup for all clients)
- Startup time tracking for uptime calculation
"""

import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.database import close_database, init_database, get_db_session
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, init_redis
from app.deps.services import set_nlp_chat_client, set_redis_client, set_vas_client
from app.integrations.nlp_chat import NLPChatClient
from app.integrations.vas import (
    VASAuthenticationError,
    VASClient,
    VASConnectionError,
    VASTimeoutError,
)
from app.integrations.unified_runtime.router import RuntimeRouter
from app.integrations.unified_runtime.client import UnifiedRuntimeClient
from app.services.inference_loop import InferenceLoopService, set_inference_loop

logger = get_logger(__name__)

# Global clients for cleanup
_vas_client: VASClient | None = None
_nlp_chat_client: NLPChatClient | None = None
_inference_loop: InferenceLoopService | None = None

# Startup timestamp for uptime calculation
_startup_time: float | None = None


def get_startup_time() -> float | None:
    """Get the application startup timestamp.

    Returns:
        Unix timestamp when application started, or None if not started
    """
    return _startup_time


def get_uptime_seconds() -> int | None:
    """Get the application uptime in seconds.

    Returns:
        Uptime in seconds, or None if application not started
    """
    if _startup_time is None:
        return None
    return int(time.time() - _startup_time)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager.

    Handles startup and shutdown events for the FastAPI application.

    Startup:
        1. Record startup time
        2. Configure logging
        3. Initialize database connection pool
        4. Initialize Redis connection pool
        5. Initialize VAS client
        6. Initialize NLP Chat client (connects to separate microservice)
        7. Initialize Inference Loop (continuous AI inference)

    Shutdown:
        1. Stop Inference Loop
        2. Close NLP Chat client
        3. Close VAS client
        4. Close Redis connections
        5. Close database connections

    Args:
        app: FastAPI application instance
    """
    global _vas_client, _nlp_chat_client, _inference_loop, _startup_time

    # Record startup time
    _startup_time = time.time()

    # ===== STARTUP =====
    settings = get_settings()

    # Configure logging first
    configure_logging()

    logger.info(
        "Starting Ruth AI Backend",
        environment=settings.ruth_ai_env,
        host=settings.host,
        port=settings.port,
    )

    # Initialize database
    try:
        await init_database()
    except Exception as e:
        logger.error("Failed to initialize database", error=str(e))
        raise

    # Initialize Redis
    try:
        redis_client = await init_redis()
        set_redis_client(redis_client)
        logger.info("Redis client initialized")
    except Exception as e:
        logger.warning(
            "Failed to initialize Redis client",
            error=str(e),
        )
        # Redis is optional - health check will show as unhealthy

    # Initialize VAS client with retry on transient failure.
    # Why: VAS may not be reachable at the exact moment Ruth boots
    # (compose ordering, slow VAS warmup). Without retry, _vas_client
    # stays None for the whole process lifetime and the InferenceLoop
    # (which is gated on _vas_client below) never starts.
    vas_max_attempts = 3
    for attempt in range(1, vas_max_attempts + 1):
        try:
            _vas_client = VASClient(
                base_url=settings.vas_base_url,
                client_id=settings.vas_client_id,
                client_secret=settings.vas_client_secret,
            )
            await _vas_client.connect()
            set_vas_client(_vas_client)
            logger.info(
                "VAS client initialized",
                base_url=settings.vas_base_url,
                attempt=attempt,
            )
            break
        except VASAuthenticationError as e:
            # Credentials problem — retrying won't fix it. Fail fast.
            logger.error(
                "Failed to initialize VAS client: bad credentials, not retrying",
                error=str(e),
            )
            _vas_client = None
            break
        except (VASConnectionError, VASTimeoutError) as e:
            if attempt < vas_max_attempts:
                backoff = 2 ** attempt  # 2s, 4s, 8s
                logger.warning(
                    "VAS client init failed (transient), will retry",
                    error=str(e),
                    error_type=type(e).__name__,
                    attempt=attempt,
                    backoff_sec=backoff,
                )
                await asyncio.sleep(backoff)
            else:
                logger.error(
                    "VAS client init failed after all retries; "
                    "InferenceLoop will not start. Restart Ruth AI once VAS is reachable.",
                    error=str(e),
                    attempts=attempt,
                )
                _vas_client = None
        except Exception as e:
            # Unknown error — log with type for visibility, don't retry.
            logger.error(
                "Failed to initialize VAS client (unexpected error type)",
                error=str(e),
                error_type=type(e).__name__,
            )
            _vas_client = None
            break

    # Initialize NLP Chat client (connects to separate microservice).
    # Skipped entirely when nlp_chat_enabled=False: avoids a pointless
    # health check during boot and prevents the chat endpoint from
    # blowing up on a NoneType client. The health aggregator reports
    # this case as status="disabled".
    if settings.nlp_chat_enabled:
        try:
            _nlp_chat_client = NLPChatClient(
                base_url=settings.nlp_chat_service_url,
                timeout_seconds=settings.nlp_chat_timeout_seconds,
            )
            set_nlp_chat_client(_nlp_chat_client)

            # Check if NLP Chat Service is available
            is_healthy = await _nlp_chat_client.is_healthy()
            if is_healthy:
                is_enabled = await _nlp_chat_client.is_enabled()
                logger.info(
                    "NLP Chat client initialized",
                    base_url=settings.nlp_chat_service_url,
                    service_enabled=is_enabled,
                )
            else:
                logger.warning(
                    "NLP Chat Service not reachable, chat functionality will be unavailable",
                    base_url=settings.nlp_chat_service_url,
                )
        except Exception as e:
            logger.warning(
                "Failed to initialize NLP Chat client, chat functionality will be unavailable",
                error=str(e),
            )
            # NLP Chat is optional - chat endpoint will return 502 if unavailable
    else:
        logger.info("NLP Chat disabled via config (nlp_chat_enabled=False)")

    # Auto-sync devices from VAS at startup so the InferenceLoop sees
    # a populated devices table on its first poll and operators don't
    # need to remember to call /internal/sync/devices manually after
    # every restart. Failure is non-fatal — manual sync remains
    # available via /internal/sync/devices and a Ruth restart with
    # VAS reachable will retry.
    if _vas_client is None:
        logger.info(
            "Skipping device auto-sync — VAS client not initialized. "
            "Restart Ruth AI once VAS is reachable, or call "
            "/internal/sync/devices manually."
        )
    else:
        try:
            from app.core.cache import DEVICES_LIST_CACHE_KEY, cache_delete
            from app.services.device_service import DeviceService

            db_gen = get_db_session()
            db = await db_gen.__anext__()
            try:
                device_service = DeviceService(vas_client=_vas_client, db=db)
                synced = await device_service.sync_devices_from_vas()
                logger.info(
                    "Device auto-sync at startup completed",
                    synced_count=len(synced),
                )
            finally:
                try:
                    await db_gen.__anext__()
                except StopAsyncIteration:
                    pass

            # Device set may have changed; invalidate the cached
            # /api/v1/devices response so the first frontend poll
            # after boot sees the fresh data.
            await cache_delete(DEVICES_LIST_CACHE_KEY)
        except Exception as e:
            logger.warning(
                "Device auto-sync at startup failed — continuing without it. "
                "Manual sync via /internal/sync/devices remains available.",
                error=str(e),
                error_type=type(e).__name__,
            )

    # Initialize Inference Loop (continuous AI inference)
    if _vas_client:
        try:
            # Create unified runtime client
            unified_client = UnifiedRuntimeClient()
            await unified_client.connect()

            # Create runtime router
            runtime_router = RuntimeRouter(
                vas_client=_vas_client,
                unified_runtime_client=unified_client,
            )

            # Create and start inference loop
            _inference_loop = InferenceLoopService(
                runtime_router=runtime_router,
                vas_client=_vas_client,
                db_session_factory=get_db_session,
                loop_interval=1.0,  # Check every 1 second
            )
            await _inference_loop.start()
            set_inference_loop(_inference_loop)

            logger.info("Inference loop started")
        except Exception as e:
            logger.error(
                "Failed to initialize inference loop",
                error=str(e),
            )
            # Inference loop is optional - AI detection will not work

    # Launch VAS stream-event consumer (non-fatal — empty VAS_REDIS_URL
    # disables it, connection errors are logged and retried).
    try:
        from app.services.vas_event_consumer import vas_event_consumer
        asyncio.create_task(vas_event_consumer.start(), name="vas-event-consumer")
        logger.info("VAS event consumer task scheduled")
    except Exception as e:
        logger.error("Failed to schedule VAS event consumer", error=str(e))

    logger.info("Ruth AI Backend startup complete")

    yield  # Application runs here

    # ===== SHUTDOWN =====
    logger.info("Shutting down Ruth AI Backend")

    # Stop Inference Loop
    if _inference_loop:
        try:
            await _inference_loop.stop()
            logger.info("Inference loop stopped")
        except Exception as e:
            logger.error("Error stopping inference loop", error=str(e))

    # Stop VAS event consumer
    try:
        from app.services.vas_event_consumer import vas_event_consumer
        await vas_event_consumer.stop()
        logger.info("VAS event consumer stopped")
    except Exception as e:
        logger.error("Error stopping VAS event consumer", error=str(e))

    # Close NLP Chat client
    if _nlp_chat_client:
        try:
            await _nlp_chat_client.close()
            logger.info("NLP Chat client closed")
        except Exception as e:
            logger.error("Error closing NLP Chat client", error=str(e))

    # Close VAS client
    if _vas_client:
        try:
            await _vas_client.close()
            logger.info("VAS client closed")
        except Exception as e:
            logger.error("Error closing VAS client", error=str(e))

    # Close Redis connections
    try:
        await close_redis()
    except Exception as e:
        logger.error("Error during Redis shutdown", error=str(e))

    # Close database connections
    try:
        await close_database()
    except Exception as e:
        logger.error("Error during database shutdown", error=str(e))

    logger.info("Ruth AI Backend shutdown complete")
