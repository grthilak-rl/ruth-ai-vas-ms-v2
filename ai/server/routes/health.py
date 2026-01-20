"""
Ruth AI Unified Runtime - Health Endpoints

Provides runtime health status, liveness, and readiness probes.

Endpoint Design:
- GET /health         - Detailed health status (verbose mode available)
- GET /health/live    - Liveness probe (is the process alive?)
- GET /health/ready   - Readiness probe (can it serve requests?)

Container Orchestrator Usage:
- Kubernetes: livenessProbe → /health/live, readinessProbe → /health/ready
- Docker: HEALTHCHECK → /health/ready
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ai.server.dependencies import get_registry, get_capability_publisher, get_sandbox_manager
from ai.server.config import get_config
from ai.runtime.models import HealthStatus, LoadState

router = APIRouter()


class GPUDeviceHealth(BaseModel):
    """GPU device health information."""

    device_id: int
    name: str
    total_memory_mb: float
    used_memory_mb: float
    available_memory_mb: float
    utilization_percent: Optional[float] = None
    temperature_c: Optional[float] = None


class ModelHealth(BaseModel):
    """Per-model health information."""

    model_id: str
    version: str
    state: str
    health: str
    inference_count: int = 0
    error_count: int = 0


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(description="Overall health status: healthy, degraded, unhealthy")
    runtime_id: str = Field(description="Unique runtime instance ID")
    models_loaded: int = Field(description="Total number of loaded models")
    models_healthy: int = Field(description="Number of healthy models")
    models_degraded: int = Field(description="Number of degraded models")
    models_unhealthy: int = Field(description="Number of unhealthy models")
    models_ready: int = Field(description="Number of models ready for inference")

    # Phase 3: Extended health info
    gpu_available: Optional[bool] = None
    gpu_device_count: Optional[int] = None
    gpu_devices: Optional[List[GPUDeviceHealth]] = None
    models: Optional[List[ModelHealth]] = None

    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "runtime_id": "unified-runtime-001",
                "models_loaded": 3,
                "models_healthy": 3,
                "models_degraded": 0,
                "models_unhealthy": 0,
                "models_ready": 3,
            }
        }


@router.get("", response_model=HealthResponse, tags=["health"])
async def health_check(
    request: Request,
    verbose: bool = Query(
        default=False,
        description="Include detailed GPU and per-model health information"
    )
) -> HealthResponse:
    """
    Check runtime health status.

    Args:
        verbose: If True, include GPU stats and per-model details

    Returns:
        Health status including model counts and overall health

    Raises:
        503: Runtime not ready or unhealthy
    """
    registry = get_registry()
    publisher = get_capability_publisher()
    config = get_config()

    if not registry:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime not initialized"
        )

    # Count models by state and health
    all_versions = registry.get_all_versions()

    models_ready = sum(1 for v in all_versions if v.state == LoadState.READY)
    models_loaded = len(all_versions)

    # Count by health status
    models_healthy = sum(1 for v in all_versions if v.health == HealthStatus.HEALTHY)
    models_degraded = sum(1 for v in all_versions if v.health == HealthStatus.DEGRADED)
    models_unhealthy = sum(1 for v in all_versions if v.health == HealthStatus.UNHEALTHY)

    # Determine overall status
    if models_loaded == 0:
        overall_status = "unhealthy"
    elif models_unhealthy > 0 or models_degraded > 0:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    # Get runtime_id from publisher or config
    runtime_id = publisher.runtime_id if publisher else config.runtime_id

    # Base response
    response = HealthResponse(
        status=overall_status,
        runtime_id=runtime_id,
        models_loaded=models_loaded,
        models_healthy=models_healthy,
        models_degraded=models_degraded,
        models_unhealthy=models_unhealthy,
        models_ready=models_ready,
    )

    # Add extended information if verbose
    if verbose:
        # GPU information
        gpu_manager = getattr(request.app.state, "gpu_manager", None)
        if gpu_manager:
            gpu_manager.update_device_stats()
            gpu_stats = gpu_manager.get_stats()

            response.gpu_available = gpu_stats["status"] == "available"
            response.gpu_device_count = gpu_stats["device_count"]

            # GPU devices
            if gpu_stats["devices"]:
                response.gpu_devices = [
                    GPUDeviceHealth(
                        device_id=d["device_id"],
                        name=d["name"],
                        total_memory_mb=d["total_memory_mb"],
                        used_memory_mb=d["used_memory_mb"],
                        available_memory_mb=d["available_memory_mb"],
                        utilization_percent=d.get("utilization_percent"),
                        temperature_c=d.get("temperature_c"),
                    )
                    for d in gpu_stats["devices"]
                ]

        # Per-model health
        response.models = [
            ModelHealth(
                model_id=v.model_id,
                version=v.version,
                state=v.state.value,
                health=v.health.value,
                inference_count=v.inference_count,
                error_count=v.error_count,
            )
            for v in all_versions
        ]

    return response


class LivenessResponse(BaseModel):
    """Liveness probe response - minimal check that process is alive."""

    status: str = Field(description="alive or dead")
    timestamp: str = Field(description="Current server timestamp")


class ReadinessResponse(BaseModel):
    """Readiness probe response - checks if runtime can serve requests."""

    ready: bool = Field(description="True if runtime can accept inference requests")
    status: str = Field(description="ready, not_ready, or degraded")
    models_ready: int = Field(description="Number of models ready for inference")
    reason: Optional[str] = Field(None, description="Reason if not ready")


@router.get("/live", response_model=LivenessResponse, tags=["health"])
async def liveness_probe() -> LivenessResponse:
    """
    Liveness probe - checks if the process is alive.

    This endpoint always returns 200 if the HTTP server is responsive.
    It does NOT check model state or dependencies.

    Use case: Kubernetes livenessProbe - restart container if this fails.

    Returns:
        LivenessResponse with status "alive"
    """
    from datetime import datetime, timezone

    return LivenessResponse(
        status="alive",
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )


@router.get("/ready", response_model=ReadinessResponse, tags=["health"])
async def readiness_probe(request: Request) -> ReadinessResponse:
    """
    Readiness probe - checks if runtime can serve inference requests.

    This endpoint checks:
    1. Registry is initialized
    2. At least one model is loaded and READY
    3. Sandbox manager is available

    Use case: Kubernetes readinessProbe - stop routing traffic if not ready.

    Returns:
        ReadinessResponse with ready status

    Raises:
        503: Runtime not ready to serve requests
    """
    from datetime import datetime

    registry = get_registry()
    sandbox_manager = get_sandbox_manager()

    # Check 1: Components initialized
    if not registry:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ReadinessResponse(
                ready=False,
                status="not_ready",
                models_ready=0,
                reason="Registry not initialized"
            ).model_dump()
        )

    if not sandbox_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ReadinessResponse(
                ready=False,
                status="not_ready",
                models_ready=0,
                reason="Sandbox manager not initialized"
            ).model_dump()
        )

    # Check 2: At least one model is READY
    all_versions = registry.get_all_versions()
    models_ready = sum(1 for v in all_versions if v.state == LoadState.READY)

    if models_ready == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ReadinessResponse(
                ready=False,
                status="not_ready",
                models_ready=0,
                reason="No models ready for inference"
            ).model_dump()
        )

    # Check 3: Determine if degraded (some models unhealthy)
    models_unhealthy = sum(1 for v in all_versions if v.health == HealthStatus.UNHEALTHY)
    models_degraded = sum(1 for v in all_versions if v.health == HealthStatus.DEGRADED)

    if models_unhealthy > 0 or models_degraded > 0:
        return ReadinessResponse(
            ready=True,
            status="degraded",
            models_ready=models_ready,
            reason=f"{models_unhealthy} unhealthy, {models_degraded} degraded models"
        )

    return ReadinessResponse(
        ready=True,
        status="ready",
        models_ready=models_ready,
        reason=None
    )
