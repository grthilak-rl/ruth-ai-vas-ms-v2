"""
Ruth AI Unified Runtime - Capabilities Endpoint

Reports available models and runtime capabilities to the backend.
"""

from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ai.server.dependencies import get_registry, get_reporter
from ai.runtime.models import LoadState, HealthStatus, InputType

router = APIRouter()


class ModelCapability(BaseModel):
    """Capability information for a single model version."""

    model_id: str = Field(description="Unique model identifier")
    version: str = Field(description="Semantic version")
    display_name: str = Field(description="Human-readable name")
    state: str = Field(description="Model load state")
    health: str = Field(description="Model health status")
    input_type: str = Field(description="Input type: frame, batch, or temporal")
    supports_cpu: bool = Field(description="Can run on CPU")
    supports_gpu: bool = Field(description="Can run on GPU")
    inference_time_hint_ms: Optional[int] = Field(None, description="Expected inference time")

    class Config:
        json_schema_extra = {
            "example": {
                "model_id": "fall_detection",
                "version": "1.0.0",
                "display_name": "Fall Detection",
                "state": "ready",
                "health": "healthy",
                "input_type": "frame",
                "supports_cpu": True,
                "supports_gpu": True,
                "inference_time_hint_ms": 200,
            }
        }


class CapabilitiesResponse(BaseModel):
    """Runtime capabilities response."""

    runtime_id: str = Field(description="Unique runtime instance ID")
    runtime_version: str = Field(description="Runtime software version")
    timestamp: datetime = Field(description="Response generation time")
    hardware_type: str = Field(description="Hardware type: cpu, gpu, or jetson")
    models: List[ModelCapability] = Field(description="Available models")
    total_models: int = Field(description="Total number of models")
    ready_models: int = Field(description="Number of models ready for inference")

    class Config:
        json_schema_extra = {
            "example": {
                "runtime_id": "unified-runtime-001",
                "runtime_version": "1.0.0",
                "timestamp": "2026-01-18T12:00:00Z",
                "hardware_type": "gpu",
                "models": [
                    {
                        "model_id": "fall_detection",
                        "version": "1.0.0",
                        "display_name": "Fall Detection",
                        "state": "ready",
                        "health": "healthy",
                        "input_type": "frame",
                        "supports_cpu": True,
                        "supports_gpu": True,
                        "inference_time_hint_ms": 200,
                    }
                ],
                "total_models": 1,
                "ready_models": 1,
            }
        }


@router.get("", response_model=CapabilitiesResponse, tags=["capabilities"])
async def get_capabilities() -> CapabilitiesResponse:
    """
    Get runtime capabilities and available models.

    Returns:
        Capabilities including all loaded models and their status

    Raises:
        503: Runtime not ready
    """
    registry = get_registry()
    reporter = get_reporter()

    if not registry or not reporter:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime not initialized"
        )

    # Collect model capabilities
    model_capabilities: List[ModelCapability] = []

    for version_descriptor in registry.get_all_versions():
        model_cap = ModelCapability(
            model_id=version_descriptor.model_id,
            version=version_descriptor.version,
            display_name=version_descriptor.display_name,
            state=version_descriptor.state.value,
            health=version_descriptor.health.value,
            input_type=version_descriptor.input_spec.type.value,
            supports_cpu=version_descriptor.hardware.supports_cpu,
            supports_gpu=version_descriptor.hardware.supports_gpu,
            inference_time_hint_ms=version_descriptor.performance.inference_time_hint_ms,
        )
        model_capabilities.append(model_cap)

    # Count ready models
    ready_models = sum(1 for m in model_capabilities if m.state == LoadState.READY.value)

    # Detect hardware type (simple heuristic for now)
    import torch
    hardware_type = "gpu" if torch.cuda.is_available() else "cpu"

    return CapabilitiesResponse(
        runtime_id=reporter.runtime_id,
        runtime_version="1.0.0",
        timestamp=datetime.utcnow(),
        hardware_type=hardware_type,
        models=model_capabilities,
        total_models=len(model_capabilities),
        ready_models=ready_models,
    )
