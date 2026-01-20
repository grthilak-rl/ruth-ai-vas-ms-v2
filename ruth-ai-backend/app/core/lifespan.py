"""Application startup and shutdown lifecycle management.

Provides:
- Lifespan context manager for FastAPI
- Startup hooks (database init, Redis init, VAS client init, NLP Chat client init)
- Shutdown hooks (cleanup for all clients)
- Startup time tracking for uptime calculation
"""

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
from app.integrations.vas import VASClient
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

    # Initialize VAS client
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
        )
    except Exception as e:
        logger.error("Failed to initialize VAS client", error=str(e))
        # VAS is optional for some operations, so we don't raise
        # but the health check will show VAS as unhealthy

    # Initialize NLP Chat client (connects to separate microservice)
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
