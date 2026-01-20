"""Ruth AI Backend - FastAPI Application Entrypoint.

This is the main entry point for the Ruth AI Backend service.
The application follows async-first design principles and is
structured for horizontal scalability.

Usage:
    uvicorn app.main:app --host 0.0.0.0 --port 8080

Or via the CLI:
    python -m app.main
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.internal import events as internal_events
from app.api.internal import ai_runtime as internal_ai_runtime
from app.api.v1 import ai, analytics, chat, devices, events, hardware, health, models, violations
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.lifespan import lifespan
from app.core.metrics import create_metrics_router
from app.core.middleware import RequestIDMiddleware, RequestLoggingMiddleware


def create_application() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance
    """
    settings = get_settings()

    app = FastAPI(
        title="Ruth AI Backend",
        description="Backend API for Ruth AI Video Analytics Platform",
        version=__version__,
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        openapi_url="/openapi.json" if settings.is_development else None,
        lifespan=lifespan,
    )

    # Add middleware (order matters - first added is outermost)
    # Request ID should be outermost so it's available to all others
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    # CORS middleware for development
    if settings.is_development:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Register API routers
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(devices.router, prefix="/api/v1")
    app.include_router(events.router, prefix="/api/v1")
    app.include_router(violations.router, prefix="/api/v1")
    app.include_router(analytics.router, prefix="/api/v1")
    app.include_router(models.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(hardware.router, prefix="/api/v1")
    app.include_router(ai.router, prefix="/api/v1")

    # Internal endpoints (no authentication for vertical slice)
    app.include_router(internal_events.router, prefix="/internal")
    app.include_router(internal_ai_runtime.router, prefix="/internal")

    # Observability endpoint
    app.include_router(create_metrics_router())

    # Register centralized exception handlers
    register_exception_handlers(app)

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
        log_level=settings.ruth_ai_log_level,
    )
