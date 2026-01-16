"""Ruth AI NLP Chat Service - FastAPI Application.

Standalone microservice for natural language database queries.
Can be started/stopped independently of the main Ruth AI backend.

Usage:
    uvicorn app.main:app --host 0.0.0.0 --port 8081
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from app import __version__
from app.api import chat, health
from app.api.chat import set_ollama_client
from app.api.health import is_service_enabled, set_startup_time
from app.core.config import get_settings
from app.core.database import close_database, init_database
from app.integrations.ollama import OllamaClient

logger = structlog.get_logger(__name__)

# Global Ollama client for cleanup
_ollama_client: OllamaClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    global _ollama_client

    settings = get_settings()

    # Record startup time
    set_startup_time(datetime.utcnow())

    logger.info(
        "Starting Ruth AI NLP Chat Service",
        version=__version__,
        host=settings.host,
        port=settings.port,
    )

    # Initialize database
    try:
        await init_database()
        logger.info("Database initialized")
    except Exception as e:
        logger.error("Failed to initialize database", error=str(e))
        raise

    # Initialize Ollama client
    try:
        _ollama_client = OllamaClient(
            base_url=settings.ollama_base_url,
            timeout_seconds=settings.ollama_timeout_seconds,
        )
        is_healthy = await _ollama_client.health_check()
        set_ollama_client(_ollama_client)

        if is_healthy:
            models = await _ollama_client.list_models()
            logger.info(
                "Ollama client initialized",
                base_url=settings.ollama_base_url,
                available_models=len(models),
            )
        else:
            logger.warning(
                "Ollama not reachable, chat will fail until Ollama is available",
                base_url=settings.ollama_base_url,
            )
    except Exception as e:
        logger.warning("Failed to initialize Ollama client", error=str(e))

    logger.info("Ruth AI NLP Chat Service startup complete")

    yield  # Application runs here

    # Shutdown
    logger.info("Shutting down Ruth AI NLP Chat Service")

    if _ollama_client:
        await _ollama_client.close()
        logger.info("Ollama client closed")

    await close_database()
    logger.info("Database connections closed")

    logger.info("Ruth AI NLP Chat Service shutdown complete")


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Ruth AI NLP Chat Service",
        description="Natural language database queries for Ruth AI",
        version=__version__,
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        openapi_url="/openapi.json" if settings.is_development else None,
        lifespan=lifespan,
    )

    # CORS middleware
    if settings.is_development:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Service enabled check middleware
    @app.middleware("http")
    async def check_service_enabled(request: Request, call_next):
        """Check if service is enabled before processing chat requests."""
        # Allow health endpoints always
        if request.url.path.startswith("/health") or request.url.path.startswith("/control"):
            return await call_next(request)

        # Check if service is enabled for other endpoints
        if not is_service_enabled():
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": "service_disabled",
                    "message": "NLP Chat Service is currently disabled",
                },
            )

        return await call_next(request)

    # Register routers
    app.include_router(health.router)
    app.include_router(chat.router)

    return app


# Create application instance
app = create_application()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.is_development,
        log_level=settings.nlp_log_level,
    )
