"""Internal endpoints for AI Runtime registration and health.

POST /internal/v1/ai-runtime/register - Register runtime and capabilities
POST /internal/v1/ai-runtime/health - Push health update
POST /internal/v1/ai-runtime/deregister - Deregister on shutdown
POST /internal/v1/ai-runtime/deregister/version - Deregister specific version

These endpoints are called by the AI Runtime (push-based) and are not
exposed to external clients. They maintain an in-memory registry of
available AI runtimes and their capabilities.

Contract:
- Runtimes push their capabilities on startup and periodically
- Backend stores capabilities for routing/discovery
- Health updates are lightweight status pushes
- Deregistration happens on graceful shutdown
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.logging import get_logger

router = APIRouter(tags=["Internal AI Runtime"])
logger = get_logger(__name__)


# =============================================================================
# IN-MEMORY RUNTIME REGISTRY
# =============================================================================

# Store registered runtimes and their capabilities
# In production, this could be backed by Redis for multi-instance support
_registered_runtimes: Dict[str, "RuntimeRegistration"] = {}


class RuntimeRegistration:
    """In-memory storage for a registered runtime."""

    def __init__(
        self,
        runtime_id: str,
        runtime_health: str,
        models: List[Dict[str, Any]],
        capacity: Dict[str, Any],
        summary: Dict[str, int],
    ):
        self.runtime_id = runtime_id
        self.runtime_health = runtime_health
        self.models = models
        self.capacity = capacity
        self.summary = summary
        self.registered_at = datetime.now(timezone.utc)
        self.last_health_update = self.registered_at
        self.last_registration_update = self.registered_at

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "runtime_id": self.runtime_id,
            "runtime_health": self.runtime_health,
            "models": self.models,
            "capacity": self.capacity,
            "summary": self.summary,
            "registered_at": self.registered_at.isoformat(),
            "last_health_update": self.last_health_update.isoformat(),
            "last_registration_update": self.last_registration_update.isoformat(),
        }


# =============================================================================
# REQUEST/RESPONSE SCHEMAS
# =============================================================================


class CapacityConcurrency(BaseModel):
    """Concurrency capacity details."""

    max_concurrent: int
    active: int
    available: int


class CapacityBackpressure(BaseModel):
    """Backpressure status."""

    level: str  # "none", "soft", "hard"
    queue_depth: int
    queue_capacity: int


class CapacityReport(BaseModel):
    """Runtime capacity report."""

    concurrency: CapacityConcurrency
    per_model_limits: Dict[str, int] = Field(default_factory=dict)
    backpressure: CapacityBackpressure


class VersionHardware(BaseModel):
    """Version hardware compatibility."""

    supports_cpu: bool
    supports_gpu: bool
    supports_jetson: bool


class VersionPerformance(BaseModel):
    """Version performance hints."""

    inference_time_hint_ms: int
    recommended_fps: int
    max_fps: Optional[int] = None
    recommended_batch_size: int
    max_concurrent: int


class VersionMetrics(BaseModel):
    """Version inference metrics."""

    inference_count: int = 0
    error_count: int = 0


class VersionCapability(BaseModel):
    """Capability payload for a single model version."""

    model_id: str
    version: str
    display_name: str
    description: str
    input_types: List[str]
    input_format: str
    output_event_types: List[str]
    provides_bounding_boxes: bool
    provides_metadata: bool
    hardware: VersionHardware
    performance: VersionPerformance
    status: str  # "active", "idle", "starting", "stopping", "error"
    health: str  # "healthy", "degraded", "unhealthy", "unknown"
    metrics: VersionMetrics = Field(default_factory=VersionMetrics)
    degraded_reason: Optional[str] = None
    registered_at: str
    last_inference_at: Optional[str] = None
    last_health_change: Optional[str] = None


class ModelCapabilityReport(BaseModel):
    """Aggregated capability report for a model."""

    model_id: str
    health: str
    total_versions: int
    healthy_versions: int
    degraded_versions: int
    versions: List[VersionCapability]


class RegistrationSummary(BaseModel):
    """Summary statistics for registration."""

    total_models: int
    healthy_models: int
    total_versions: int
    ready_versions: int


class RuntimeRegisterRequest(BaseModel):
    """Request to register runtime capabilities."""

    runtime_id: str
    timestamp: str
    runtime_health: str
    summary: RegistrationSummary
    models: List[ModelCapabilityReport]
    capacity: CapacityReport


class RuntimeRegisterResponse(BaseModel):
    """Response for runtime registration."""

    status: str
    runtime_id: str
    registered_at: str
    models_registered: int
    versions_registered: int


class HealthUpdateRequest(BaseModel):
    """Request to push health update."""

    runtime_id: str
    timestamp: str
    runtime_health: str
    models: Dict[str, str]  # model_id -> health status


class HealthUpdateResponse(BaseModel):
    """Response for health update."""

    status: str
    runtime_id: str
    updated_at: str


class DeregisterRequest(BaseModel):
    """Request to deregister runtime."""

    runtime_id: str
    timestamp: str
    reason: str  # "graceful_shutdown", "error", etc.


class DeregisterResponse(BaseModel):
    """Response for runtime deregistration."""

    status: str
    runtime_id: str
    deregistered_at: str


class DeregisterVersionRequest(BaseModel):
    """Request to deregister a specific version."""

    runtime_id: str
    model_id: str
    version: str
    timestamp: str
    reason: str  # "version_unloaded", "error", etc.


class DeregisterVersionResponse(BaseModel):
    """Response for version deregistration."""

    status: str
    runtime_id: str
    model_id: str
    version: str
    deregistered_at: str


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.post(
    "/v1/ai-runtime/register",
    response_model=RuntimeRegisterResponse,
    status_code=status.HTTP_200_OK,
    summary="Register AI runtime capabilities",
    description="Internal endpoint for AI Runtime to register/update its capabilities.",
)
async def register_runtime(
    request: RuntimeRegisterRequest,
) -> RuntimeRegisterResponse:
    """Register or update AI runtime capabilities.

    This endpoint:
    1. Creates or updates runtime registration
    2. Stores model capabilities for routing
    3. Updates health status
    4. Returns acknowledgment

    The registration is idempotent - calling multiple times with the same
    runtime_id will update the existing registration.
    """
    correlation_id = request.runtime_id[:8]

    logger.info(
        "AI Runtime registration received",
        runtime_id=request.runtime_id,
        runtime_health=request.runtime_health,
        total_models=request.summary.total_models,
        ready_versions=request.summary.ready_versions,
        correlation_id=correlation_id,
    )

    # Count versions across all models
    versions_registered = sum(len(m.versions) for m in request.models)

    # Create or update registration
    registration = RuntimeRegistration(
        runtime_id=request.runtime_id,
        runtime_health=request.runtime_health,
        models=[m.model_dump() for m in request.models],
        capacity=request.capacity.model_dump(),
        summary=request.summary.model_dump(),
    )

    # Check if this is a re-registration
    is_update = request.runtime_id in _registered_runtimes

    _registered_runtimes[request.runtime_id] = registration

    if is_update:
        logger.info(
            "AI Runtime registration updated",
            runtime_id=request.runtime_id,
            models_registered=request.summary.total_models,
            versions_registered=versions_registered,
            correlation_id=correlation_id,
        )
    else:
        logger.info(
            "AI Runtime registered (new)",
            runtime_id=request.runtime_id,
            models_registered=request.summary.total_models,
            versions_registered=versions_registered,
            correlation_id=correlation_id,
        )

    return RuntimeRegisterResponse(
        status="registered",
        runtime_id=request.runtime_id,
        registered_at=registration.registered_at.isoformat(),
        models_registered=request.summary.total_models,
        versions_registered=versions_registered,
    )


@router.post(
    "/v1/ai-runtime/health",
    response_model=HealthUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Push AI runtime health update",
    description="Internal endpoint for AI Runtime to push health status updates.",
)
async def push_health(
    request: HealthUpdateRequest,
) -> HealthUpdateResponse:
    """Push health status update from AI runtime.

    This is a lightweight endpoint that only updates health status,
    not full capabilities. Used for frequent health heartbeats.

    Note: If runtime is not registered, the health update is accepted
    but logged as a warning. The runtime should re-register.
    """
    correlation_id = request.runtime_id[:8]

    logger.debug(
        "AI Runtime health update received",
        runtime_id=request.runtime_id,
        runtime_health=request.runtime_health,
        model_count=len(request.models),
        correlation_id=correlation_id,
    )

    now = datetime.now(timezone.utc)

    # Update existing registration if present
    if request.runtime_id in _registered_runtimes:
        registration = _registered_runtimes[request.runtime_id]
        registration.runtime_health = request.runtime_health
        registration.last_health_update = now

        # Update per-model health in stored models
        for model in registration.models:
            model_id = model.get("model_id")
            if model_id and model_id in request.models:
                model["health"] = request.models[model_id]
                # Update versions too
                for version in model.get("versions", []):
                    version["health"] = request.models[model_id]

        logger.debug(
            "AI Runtime health updated",
            runtime_id=request.runtime_id,
            correlation_id=correlation_id,
        )
    else:
        # Runtime not registered - accept but log warning
        logger.warning(
            "Health update from unregistered runtime",
            runtime_id=request.runtime_id,
            correlation_id=correlation_id,
        )

    return HealthUpdateResponse(
        status="updated",
        runtime_id=request.runtime_id,
        updated_at=now.isoformat(),
    )


@router.post(
    "/v1/ai-runtime/deregister",
    response_model=DeregisterResponse,
    status_code=status.HTTP_200_OK,
    summary="Deregister AI runtime",
    description="Internal endpoint for AI Runtime graceful shutdown deregistration.",
)
async def deregister_runtime(
    request: DeregisterRequest,
) -> DeregisterResponse:
    """Deregister AI runtime on shutdown.

    Called during graceful shutdown to remove the runtime from
    the active registry. This prevents the backend from routing
    requests to a shutting-down runtime.
    """
    correlation_id = request.runtime_id[:8]

    logger.info(
        "AI Runtime deregistration received",
        runtime_id=request.runtime_id,
        reason=request.reason,
        correlation_id=correlation_id,
    )

    now = datetime.now(timezone.utc)

    # Remove from registry
    if request.runtime_id in _registered_runtimes:
        del _registered_runtimes[request.runtime_id]
        logger.info(
            "AI Runtime deregistered",
            runtime_id=request.runtime_id,
            reason=request.reason,
            correlation_id=correlation_id,
        )
    else:
        logger.warning(
            "Deregistration for unknown runtime",
            runtime_id=request.runtime_id,
            correlation_id=correlation_id,
        )

    return DeregisterResponse(
        status="deregistered",
        runtime_id=request.runtime_id,
        deregistered_at=now.isoformat(),
    )


@router.post(
    "/v1/ai-runtime/deregister/version",
    response_model=DeregisterVersionResponse,
    status_code=status.HTTP_200_OK,
    summary="Deregister specific model version",
    description="Internal endpoint to deregister a specific model version.",
)
async def deregister_version(
    request: DeregisterVersionRequest,
) -> DeregisterVersionResponse:
    """Deregister a specific model version.

    Called when a model version is unloaded or becomes unavailable.
    Removes only the specified version, leaving other versions intact.
    """
    correlation_id = request.runtime_id[:8]

    logger.info(
        "Model version deregistration received",
        runtime_id=request.runtime_id,
        model_id=request.model_id,
        version=request.version,
        reason=request.reason,
        correlation_id=correlation_id,
    )

    now = datetime.now(timezone.utc)

    # Update registration if present
    if request.runtime_id in _registered_runtimes:
        registration = _registered_runtimes[request.runtime_id]

        # Find and remove the version
        for model in registration.models:
            if model.get("model_id") == request.model_id:
                versions = model.get("versions", [])
                model["versions"] = [
                    v for v in versions if v.get("version") != request.version
                ]

                # Update counts
                model["total_versions"] = len(model["versions"])
                model["healthy_versions"] = sum(
                    1 for v in model["versions"] if v.get("health") == "healthy"
                )
                model["degraded_versions"] = sum(
                    1 for v in model["versions"] if v.get("health") == "degraded"
                )

                # Update model health based on remaining versions
                if model["healthy_versions"] > 0:
                    model["health"] = "healthy"
                elif model["degraded_versions"] > 0:
                    model["health"] = "degraded"
                elif model["total_versions"] > 0:
                    model["health"] = "unhealthy"
                else:
                    model["health"] = "unavailable"

                logger.info(
                    "Model version deregistered",
                    runtime_id=request.runtime_id,
                    model_id=request.model_id,
                    version=request.version,
                    remaining_versions=model["total_versions"],
                    correlation_id=correlation_id,
                )
                break

        # Update summary
        registration.summary["ready_versions"] = sum(
            len(m.get("versions", [])) for m in registration.models
        )
        registration.last_registration_update = now
    else:
        logger.warning(
            "Version deregistration for unknown runtime",
            runtime_id=request.runtime_id,
            correlation_id=correlation_id,
        )

    return DeregisterVersionResponse(
        status="deregistered",
        runtime_id=request.runtime_id,
        model_id=request.model_id,
        version=request.version,
        deregistered_at=now.isoformat(),
    )


# =============================================================================
# QUERY ENDPOINTS (for backend internal use)
# =============================================================================


@router.get(
    "/v1/ai-runtime/status",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get all registered AI runtimes",
    description="Internal endpoint to query registered AI runtimes.",
)
async def get_runtime_status() -> Dict[str, Any]:
    """Get status of all registered AI runtimes.

    Returns summary and details of all registered runtimes.
    Useful for debugging and monitoring.
    """
    runtimes = []
    total_models = 0
    total_versions = 0
    healthy_runtimes = 0

    for runtime in _registered_runtimes.values():
        runtimes.append(runtime.to_dict())
        total_models += runtime.summary.get("total_models", 0)
        total_versions += runtime.summary.get("ready_versions", 0)
        if runtime.runtime_health == "healthy":
            healthy_runtimes += 1

    return {
        "summary": {
            "total_runtimes": len(_registered_runtimes),
            "healthy_runtimes": healthy_runtimes,
            "total_models": total_models,
            "total_versions": total_versions,
        },
        "runtimes": runtimes,
    }


@router.get(
    "/v1/ai-runtime/{runtime_id}",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get specific AI runtime details",
    description="Internal endpoint to query a specific AI runtime.",
)
async def get_runtime_details(runtime_id: str) -> Dict[str, Any]:
    """Get details of a specific AI runtime."""
    if runtime_id not in _registered_runtimes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Runtime {runtime_id} not found",
        )

    return _registered_runtimes[runtime_id].to_dict()


@router.get(
    "/v1/ai-runtime/models/available",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get all available AI models",
    description="Internal endpoint to get all available models across runtimes.",
)
async def get_available_models() -> Dict[str, Any]:
    """Get all available AI models across all registered runtimes.

    Aggregates models from all healthy runtimes for routing/discovery.
    """
    models: Dict[str, Dict[str, Any]] = {}

    for runtime in _registered_runtimes.values():
        if runtime.runtime_health not in ("healthy", "degraded"):
            continue

        for model in runtime.models:
            model_id = model.get("model_id")
            if not model_id:
                continue

            if model_id not in models:
                models[model_id] = {
                    "model_id": model_id,
                    "health": model.get("health", "unknown"),
                    "available_versions": [],
                    "runtimes": [],
                }

            # Add runtime to model's runtime list
            models[model_id]["runtimes"].append(
                {
                    "runtime_id": runtime.runtime_id,
                    "health": runtime.runtime_health,
                }
            )

            # Add versions
            for version in model.get("versions", []):
                version_info = {
                    "version": version.get("version"),
                    "health": version.get("health"),
                    "status": version.get("status"),
                    "runtime_id": runtime.runtime_id,
                }
                models[model_id]["available_versions"].append(version_info)

    return {
        "total_models": len(models),
        "models": list(models.values()),
    }
