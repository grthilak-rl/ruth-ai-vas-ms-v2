"""Health check endpoint scaffold.

Provides:
- GET /api/v1/health endpoint
- Basic liveness check (responds 200)
- Component health stubs (no real checks yet)

Per Infrastructure Design, full health response includes:
- database: healthy | unhealthy
- redis: healthy | unhealthy
- ai_runtime: healthy | degraded | unhealthy
- vas: healthy | unhealthy

This is a scaffold - real component checks will be added in later tasks.
"""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(tags=["Health"])
logger = get_logger(__name__)


class ComponentHealth(BaseModel):
    """Health status of a single component."""

    status: Literal["healthy", "degraded", "unhealthy"]
    latency_ms: int | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    """Health check response schema.

    Matches Infrastructure Design document specification.
    """

    status: Literal["healthy", "degraded", "unhealthy"]
    service: str = "ruth-ai-backend"
    version: str
    timestamp: datetime
    components: dict[str, ComponentHealth]
    uptime_seconds: int | None = None


def _determine_overall_status(
    components: dict[str, ComponentHealth],
) -> Literal["healthy", "degraded", "unhealthy"]:
    """Determine overall health status based on components.

    - If any component is unhealthy: overall is unhealthy
    - If any component is degraded: overall is degraded
    - Otherwise: overall is healthy
    """
    statuses = [c.status for c in components.values()]

    if "unhealthy" in statuses:
        return "unhealthy"
    if "degraded" in statuses:
        return "degraded"
    return "healthy"


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns the health status of the Ruth AI Backend and its dependencies.",
)
async def health_check() -> HealthResponse:
    """Health check endpoint.

    Returns health status of the backend and all dependencies.
    This is a scaffold - component checks return healthy stubs.

    Returns:
        HealthResponse with component health statuses
    """
    settings = get_settings()

    # Scaffold: all components report healthy
    # Real health checks will be implemented in subsequent tasks
    components = {
        "database": ComponentHealth(status="healthy", latency_ms=None),
        "redis": ComponentHealth(status="healthy", latency_ms=None),
        "ai_runtime": ComponentHealth(status="healthy", latency_ms=None),
        "vas": ComponentHealth(status="healthy", latency_ms=None),
    }

    overall_status = _determine_overall_status(components)

    response = HealthResponse(
        status=overall_status,
        service="ruth-ai-backend",
        version=__version__,
        timestamp=datetime.now(timezone.utc),
        components=components,
        uptime_seconds=None,  # Will be tracked in later task
    )

    logger.debug(
        "Health check completed",
        status=overall_status,
        environment=settings.ruth_ai_env,
    )

    return response


@router.get(
    "/health/live",
    status_code=200,
    summary="Liveness probe",
    description="Simple liveness check for container orchestration.",
)
async def liveness() -> dict[str, str]:
    """Kubernetes liveness probe endpoint.

    Returns 200 if the process is alive.
    Does not check dependencies.
    """
    return {"status": "ok"}


@router.get(
    "/health/ready",
    status_code=200,
    summary="Readiness probe",
    description="Readiness check for container orchestration.",
)
async def readiness() -> dict[str, str]:
    """Kubernetes readiness probe endpoint.

    Returns 200 if the service is ready to accept requests.
    Scaffold implementation - will check dependencies in later task.
    """
    # Scaffold: always ready
    # Real implementation will verify database, redis, etc.
    return {"status": "ready"}
