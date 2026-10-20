"""Health check endpoints for Ruth AI Backend.

Provides:
- GET /api/v1/health - Full health check with all component statuses
- GET /api/v1/health/live - Kubernetes liveness probe
- GET /api/v1/health/ready - Kubernetes readiness probe

Per Infrastructure Design, health response includes:
- database: healthy | unhealthy
- redis: healthy | unhealthy
- ai_runtime: healthy | degraded | unhealthy
- vas: healthy | unhealthy

All checks implement proper timeouts to prevent blocking.
"""

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import select

from app import __version__
from app.core.config import get_settings
from app.core.database import get_engine
from app.core.lifespan import get_uptime_seconds
from app.core.logging import get_logger
from app.deps import DBSession
from app.deps.services import get_redis_client_optional, get_vas_client_optional
from app.schemas.health import (
    ComponentHealth,
    HealthResponse,
    LivenessResponse,
    ReadinessResponse,
)
from app.services.health_service import HealthService

router = APIRouter(tags=["Health"])
logger = get_logger(__name__)


def _get_health_service() -> HealthService:
    """Create a HealthService instance with available dependencies."""
    return HealthService(
        engine=get_engine(),
        redis_client=get_redis_client_optional(),
        vas_client=get_vas_client_optional(),
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns the health status of the Ruth AI Backend and its dependencies.",
    responses={
        200: {
            "description": "Health check completed (status may be healthy, degraded, or unhealthy)",
            "content": {
                "application/json": {
                    "example": {
                        "status": "healthy",
                        "service": "ruth-ai-backend",
                        "version": "0.1.0",
                        "timestamp": "2025-01-16T10:30:00Z",
                        "components": {
                            "database": {
                                "status": "healthy",
                                "latency_ms": 12,
                                "details": {
                                    "pool_size": 10,
                                    "pool_checkedout": 3,
                                },
                            },
                            "redis": {
                                "status": "healthy",
                                "latency_ms": 2,
                                "details": {
                                    "used_memory_human": "1.2MB",
                                    "connected_clients": 5,
                                },
                            },
                            "ai_runtime": {
                                "status": "healthy",
                                "latency_ms": 45,
                                "details": {
                                    "models_loaded": ["fall_detection_v1"],
                                    "gpu_available": True,
                                },
                            },
                            "vas": {
                                "status": "healthy",
                                "latency_ms": 23,
                                "details": {
                                    "version": "1.0.0",
                                    "service": "VAS Backend",
                                },
                            },
                        },
                        "uptime_seconds": 3600,
                    }
                }
            },
        }
    },
)
async def health_check() -> HealthResponse:
    """Health check endpoint.

    Returns health status of the backend and all dependencies.
    All component checks run concurrently with individual timeouts.

    Returns:
        HealthResponse with component health statuses
    """
    settings = get_settings()
    health_service = _get_health_service()

    # Run all health checks concurrently
    components = await health_service.check_all(
        db_timeout=settings.health_check_db_timeout,
        redis_timeout=settings.health_check_redis_timeout,
        ai_runtime_timeout=settings.health_check_ai_runtime_timeout,
        vas_timeout=settings.health_check_vas_timeout,
        nlp_chat_timeout=settings.health_check_nlp_chat_timeout,
    )

    overall_status = health_service.determine_overall_status(components)

    response = HealthResponse(
        status=overall_status,
        service="ruth-ai-backend",
        version=__version__,
        timestamp=datetime.now(timezone.utc),
        components=components,
        uptime_seconds=get_uptime_seconds(),
    )

    logger.debug(
        "Health check completed",
        status=overall_status,
        environment=settings.ruth_ai_env,
        components={
            name: comp.status for name, comp in components.items()
        },
    )

    return response


@router.get(
    "/health/auto-resume",
    summary="Auto-resume activity and parked cameras",
    description=(
        "What the reconciler has done in the last 24 hours, and which "
        "cameras it has given up on for now. A parked camera is one whose "
        "video is live and whose dependencies are up, but which still will "
        "not start — a real fault, not a blip."
    ),
)
async def auto_resume_status(db: DBSession) -> dict:
    from app.models import INTENT_ACTIVE, Device, DeviceInferenceIntent
    from app.services.inference_intent import is_parked, retry_due_at
    from app.services.inference_reconciler import get_reconciler

    reconciler = get_reconciler()
    rows = (
        await db.execute(
            select(DeviceInferenceIntent, Device)
            .join(Device, Device.id == DeviceInferenceIntent.device_id)
            .where(DeviceInferenceIntent.desired_state == INTENT_ACTIVE)
        )
    ).all()

    parked = []
    for intent, device in rows:
        if not is_parked(intent):
            continue
        due = retry_due_at(intent)
        parked.append(
            {
                "camera": device.name,
                "device_id": str(device.id),
                "since": intent.last_attempt_at.isoformat() if intent.last_attempt_at else None,
                "consecutive_failures": intent.consecutive_failures,
                "last_error": intent.last_error,
                "retry_due_at": due.isoformat() if due else None,
            }
        )

    resumes = reconciler.resumes_last_24h() if reconciler else []
    last = reconciler.last_outcome if reconciler else None
    return {
        "enabled": reconciler is not None,
        "last_run_at": reconciler.last_run_at.isoformat()
        if reconciler and reconciler.last_run_at
        else None,
        "resumes_last_24h": resumes,
        "resume_count_24h": len(resumes),
        "parked": parked,
        # Set when the whole cycle was skipped because a shared dependency
        # was down. One alert for the fleet, not one per camera.
        "dependency_error": last.dependency_error if last else None,
    }


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    status_code=200,
    summary="Liveness probe",
    description="Simple liveness check for container orchestration. Returns 200 if the process is alive.",
    responses={
        200: {
            "description": "Service is alive",
            "content": {
                "application/json": {
                    "example": {"status": "ok"}
                }
            },
        }
    },
)
async def liveness() -> LivenessResponse:
    """Kubernetes liveness probe endpoint.

    Returns 200 if the process is alive.
    Does not check dependencies - this is intentional for liveness probes.
    """
    return LivenessResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    status_code=200,
    summary="Readiness probe",
    description="Readiness check for container orchestration. Verifies database connectivity.",
    responses={
        200: {
            "description": "Service readiness status",
            "content": {
                "application/json": {
                    "examples": {
                        "ready": {
                            "summary": "Service is ready",
                            "value": {"status": "ready"},
                        },
                        "not_ready": {
                            "summary": "Service is not ready",
                            "value": {
                                "status": "not_ready",
                                "message": "Database is unhealthy",
                            },
                        },
                    }
                }
            },
        }
    },
)
async def readiness() -> ReadinessResponse:
    """Kubernetes readiness probe endpoint.

    Returns ready status if the service can accept requests.
    Requires database to be healthy at minimum.
    """
    settings = get_settings()
    health_service = _get_health_service()

    # Only check database for readiness (fast check)
    db_health = await health_service.check_database(
        timeout_seconds=settings.health_check_db_timeout
    )

    if db_health.status == "healthy":
        return ReadinessResponse(status="ready")

    return ReadinessResponse(
        status="not_ready",
        message=db_health.error or "Database is unhealthy",
    )
