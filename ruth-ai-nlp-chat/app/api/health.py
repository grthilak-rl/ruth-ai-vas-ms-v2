"""Health check endpoints for NLP Chat Service.

Provides health information for:
- Service liveness (is it running?)
- Service readiness (can it serve requests?)
- Component status (Ollama, Database)
"""

from datetime import datetime
from enum import Enum

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
import structlog

from app.core.config import get_settings
from app.core.database import get_db_session
from app.api.chat import get_ollama_client

router = APIRouter(tags=["Health"])
logger = structlog.get_logger(__name__)

# Track startup time
_startup_time: datetime | None = None


def set_startup_time(t: datetime) -> None:
    """Set the service startup time."""
    global _startup_time
    _startup_time = t


class HealthStatus(str, Enum):
    """Health status values."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth(BaseModel):
    """Health status of a component."""
    status: HealthStatus
    message: str | None = None
    latency_ms: int | None = None


class HealthResponse(BaseModel):
    """Response for health check endpoints."""
    status: HealthStatus
    service: str = "Ruth AI NLP Chat Service"
    version: str
    uptime_seconds: int | None = None
    components: dict[str, ComponentHealth] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ServiceControlResponse(BaseModel):
    """Response for service control endpoints."""
    enabled: bool
    message: str


# Service enabled state (can be toggled via API)
_service_enabled: bool = True


def is_service_enabled() -> bool:
    """Check if NLP service is enabled."""
    return _service_enabled


def set_service_enabled(enabled: bool) -> None:
    """Enable or disable the NLP service."""
    global _service_enabled
    _service_enabled = enabled


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Full health check",
    description="Returns detailed health status of the NLP Chat Service and its dependencies.",
)
async def health_check() -> HealthResponse:
    """Comprehensive health check with component status."""
    from app import __version__

    settings = get_settings()
    components: dict[str, ComponentHealth] = {}
    overall_status = HealthStatus.HEALTHY

    # Check Ollama
    try:
        ollama_client = get_ollama_client()
        import time
        start = time.time()
        is_healthy = await ollama_client.health_check()
        latency = int((time.time() - start) * 1000)

        if is_healthy:
            models = await ollama_client.list_models()
            sql_model_available = settings.ollama_sql_model in models
            nlg_model_available = settings.ollama_nlg_model in models

            if sql_model_available and nlg_model_available:
                components["ollama"] = ComponentHealth(
                    status=HealthStatus.HEALTHY,
                    message=f"Connected, models available",
                    latency_ms=latency,
                )
            else:
                missing = []
                if not sql_model_available:
                    missing.append(settings.ollama_sql_model)
                if not nlg_model_available:
                    missing.append(settings.ollama_nlg_model)
                components["ollama"] = ComponentHealth(
                    status=HealthStatus.DEGRADED,
                    message=f"Missing models: {', '.join(missing)}",
                    latency_ms=latency,
                )
                overall_status = HealthStatus.DEGRADED
        else:
            components["ollama"] = ComponentHealth(
                status=HealthStatus.UNHEALTHY,
                message="Ollama not responding",
            )
            overall_status = HealthStatus.UNHEALTHY
    except Exception as e:
        components["ollama"] = ComponentHealth(
            status=HealthStatus.UNHEALTHY,
            message=f"Error: {str(e)[:100]}",
        )
        overall_status = HealthStatus.UNHEALTHY

    # Check Database
    try:
        from sqlalchemy import text
        import time
        start = time.time()
        async for session in get_db_session():
            await session.execute(text("SELECT 1"))
            latency = int((time.time() - start) * 1000)
            components["database"] = ComponentHealth(
                status=HealthStatus.HEALTHY,
                message="Connected",
                latency_ms=latency,
            )
            break
    except Exception as e:
        components["database"] = ComponentHealth(
            status=HealthStatus.UNHEALTHY,
            message=f"Error: {str(e)[:100]}",
        )
        overall_status = HealthStatus.UNHEALTHY

    # Calculate uptime
    uptime = None
    if _startup_time:
        uptime = int((datetime.utcnow() - _startup_time).total_seconds())

    return HealthResponse(
        status=overall_status,
        version=__version__,
        uptime_seconds=uptime,
        components=components,
    )


@router.get(
    "/health/live",
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
    description="Simple check if service is running (for Kubernetes).",
)
async def liveness() -> dict:
    """Kubernetes liveness probe."""
    return {"status": "ok"}


@router.get(
    "/health/ready",
    status_code=status.HTTP_200_OK,
    summary="Readiness probe",
    description="Check if service is ready to accept requests.",
)
async def readiness() -> dict:
    """Kubernetes readiness probe."""
    if not _service_enabled:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is disabled",
        )
    return {"status": "ready", "enabled": _service_enabled}


@router.post(
    "/control/enable",
    response_model=ServiceControlResponse,
    summary="Enable NLP service",
    description="Enable the NLP chat service to accept requests.",
)
async def enable_service() -> ServiceControlResponse:
    """Enable the NLP service."""
    set_service_enabled(True)
    logger.info("NLP service enabled via API")
    return ServiceControlResponse(
        enabled=True,
        message="NLP Chat Service is now enabled",
    )


@router.post(
    "/control/disable",
    response_model=ServiceControlResponse,
    summary="Disable NLP service",
    description="Disable the NLP chat service. Requests will return 503.",
)
async def disable_service() -> ServiceControlResponse:
    """Disable the NLP service."""
    set_service_enabled(False)
    logger.info("NLP service disabled via API")
    return ServiceControlResponse(
        enabled=False,
        message="NLP Chat Service is now disabled",
    )


@router.get(
    "/control/status",
    response_model=ServiceControlResponse,
    summary="Get service status",
    description="Check if NLP service is enabled or disabled.",
)
async def service_status() -> ServiceControlResponse:
    """Get current service enabled status."""
    return ServiceControlResponse(
        enabled=_service_enabled,
        message="NLP Chat Service is enabled" if _service_enabled else "NLP Chat Service is disabled",
    )
