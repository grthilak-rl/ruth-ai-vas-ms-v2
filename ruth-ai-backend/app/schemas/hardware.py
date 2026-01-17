"""Pydantic schemas for hardware monitoring API endpoint.

Provides structured hardware metrics reporting for:
- GPU (NVIDIA via pynvml)
- CPU (via psutil)
- RAM (via psutil)
- Loaded AI models
- System capacity estimates
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GPUMetrics(BaseModel):
    """GPU hardware metrics."""

    available: bool = Field(..., description="Whether a GPU is available")
    name: str | None = Field(None, description="GPU model name")
    vram_total_gb: float | None = Field(None, description="Total VRAM in GB")
    vram_used_gb: float | None = Field(None, description="Used VRAM in GB")
    vram_percent: int | None = Field(None, description="VRAM usage percentage")
    utilization_percent: int | None = Field(None, description="GPU compute utilization percentage")
    temperature_c: int | None = Field(None, description="GPU temperature in Celsius")


class CPUMetrics(BaseModel):
    """CPU hardware metrics."""

    model: str | None = Field(None, description="CPU model name")
    cores: int | None = Field(None, description="Number of CPU cores")
    usage_percent: float = Field(..., description="Current CPU usage percentage")


class RAMMetrics(BaseModel):
    """RAM memory metrics."""

    total_gb: float = Field(..., description="Total RAM in GB")
    used_gb: float = Field(..., description="Used RAM in GB")
    percent: float = Field(..., description="RAM usage percentage")


class ModelServiceStatus(BaseModel):
    """Status of an individual AI model service."""

    name: str = Field(..., description="Service name")
    models: int = Field(..., description="Number of models loaded")
    status: Literal["healthy", "unhealthy", "unknown"] = Field(
        ..., description="Service health status"
    )


class ModelsMetrics(BaseModel):
    """AI models metrics."""

    loaded_count: int = Field(..., description="Total number of loaded models")
    services: list[ModelServiceStatus] = Field(
        default_factory=list, description="Individual service statuses"
    )


class CapacityMetrics(BaseModel):
    """System capacity estimates."""

    current_cameras: int = Field(..., description="Number of cameras currently active")
    estimated_max_cameras: int = Field(
        ..., description="Estimated maximum cameras based on resources"
    )
    headroom_percent: int = Field(
        ..., description="Available capacity headroom percentage"
    )


class HardwareResponse(BaseModel):
    """Hardware monitoring response schema.

    Returns real-time hardware utilization metrics for the Ruth AI dashboard.
    Includes GPU, CPU, RAM, loaded models, and capacity estimates.
    """

    timestamp: datetime = Field(..., description="Timestamp of metrics collection")
    gpu: GPUMetrics = Field(..., description="GPU metrics")
    cpu: CPUMetrics = Field(..., description="CPU metrics")
    ram: RAMMetrics = Field(..., description="RAM metrics")
    models: ModelsMetrics = Field(..., description="Loaded AI models metrics")
    capacity: CapacityMetrics = Field(..., description="System capacity estimates")
