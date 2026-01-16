"""Application startup and shutdown lifecycle management.

Provides:
- Lifespan context manager for FastAPI
- Startup hooks (database init, VAS client init, logging setup)
- Shutdown hooks (database cleanup, VAS client cleanup)
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.database import close_database, init_database
from app.core.logging import configure_logging, get_logger
from app.deps.services import set_vas_client
from app.integrations.vas import VASClient

logger = get_logger(__name__)

# Global VAS client for cleanup
_vas_client: VASClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager.

    Handles startup and shutdown events for the FastAPI application.

    Startup:
        1. Configure logging
        2. Initialize database connection pool
        3. Initialize VAS client

    Shutdown:
        1. Close VAS client
        2. Close database connections
        3. Release any held resources

    Args:
        app: FastAPI application instance
    """
    global _vas_client

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

    logger.info("Ruth AI Backend startup complete")

    yield  # Application runs here

    # ===== SHUTDOWN =====
    logger.info("Shutting down Ruth AI Backend")

    # Close VAS client
    if _vas_client:
        try:
            await _vas_client.close()
            logger.info("VAS client closed")
        except Exception as e:
            logger.error("Error closing VAS client", error=str(e))

    # Close database connections
    try:
        await close_database()
    except Exception as e:
        logger.error("Error during database shutdown", error=str(e))

    logger.info("Ruth AI Backend shutdown complete")
