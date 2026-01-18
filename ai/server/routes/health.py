"""
Ruth AI Unified Runtime - Health Endpoint

Provides runtime health status and model availability.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query, HTTPException, Request, status
from pydantic import BaseModel, Field

from ai.server.dependencies import get_registry, get_reporter
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
    reporter = get_reporter()

    if not registry or not reporter:
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

    # Base response
    response = HealthResponse(
        status=overall_status,
        runtime_id=reporter.runtime_id,
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
