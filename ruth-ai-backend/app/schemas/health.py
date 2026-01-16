"""Pydantic schemas for health check API endpoints.

Provides structured health status reporting for:
- Database (PostgreSQL)
- Redis cache
- AI Runtime
- VAS (Video Analytics Service)
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


HealthStatus = Literal["healthy", "degraded", "unhealthy"]


class ComponentDetails(BaseModel):
    """Base model for component-specific details."""

    pass


class DatabaseDetails(ComponentDetails):
    """Database health check details."""

    pool_size: int | None = Field(
        None, description="Configured connection pool size"
    )
    pool_checkedout: int | None = Field(
        None, description="Number of connections currently in use"
    )
    pool_overflow: int | None = Field(
        None, description="Number of overflow connections in use"
    )
    pool_checkedin: int | None = Field(
        None, description="Number of connections available in pool"
    )


class RedisDetails(ComponentDetails):
    """Redis health check details."""

    used_memory_human: str | None = Field(
        None, description="Human-readable used memory (e.g., '1.2MB')"
    )
    connected_clients: int | None = Field(
        None, description="Number of connected clients"
    )
    uptime_in_seconds: int | None = Field(
        None, description="Redis server uptime in seconds"
    )
    redis_version: str | None = Field(
        None, description="Redis server version"
    )


class AIRuntimeDetails(ComponentDetails):
    """AI Runtime health check details."""

    runtime_id: str | None = Field(None, description="Runtime instance identifier")
    models_loaded: list[str] | None = Field(
        None, description="List of loaded model IDs"
    )
    gpu_available: bool | None = Field(
        None, description="Whether GPU acceleration is available"
    )
    hardware_type: str | None = Field(
        None, description="Hardware type (cpu, cuda, tensorrt, jetson)"
    )


class VASDetails(ComponentDetails):
    """VAS health check details."""

    version: str | None = Field(None, description="VAS service version")
    service: str | None = Field(None, description="VAS service name")


class NLPChatDetails(ComponentDetails):
    """NLP Chat Service health check details."""

    version: str | None = Field(None, description="NLP Chat Service version")
    service: str | None = Field(None, description="NLP Chat Service name")
    enabled: bool | None = Field(None, description="Whether the chat service is enabled")
    ollama_status: str | None = Field(None, description="Ollama LLM status")
    models_available: list[str] | None = Field(None, description="Available LLM models")


class ComponentHealth(BaseModel):
    """Health status of a single component."""

    status: HealthStatus = Field(..., description="Component health status")
    latency_ms: int | None = Field(
        None, description="Health check latency in milliseconds"
    )
    error: str | None = Field(
        None, description="Error message if unhealthy or degraded"
    )
    details: dict[str, Any] | None = Field(
        None, description="Component-specific details"
    )


class HealthResponse(BaseModel):
    """Health check response schema.

    Matches Infrastructure Design document specification.
    Returns overall status and individual component health.
    """

    status: HealthStatus = Field(..., description="Overall health status")
    service: str = Field(
        default="ruth-ai-backend", description="Service name"
    )
    version: str = Field(..., description="Service version")
    timestamp: datetime = Field(..., description="Timestamp of health check")
    components: dict[str, ComponentHealth] = Field(
        ..., description="Individual component health statuses"
    )
    uptime_seconds: int | None = Field(
        None, description="Service uptime in seconds"
    )


class LivenessResponse(BaseModel):
    """Response schema for liveness probe."""

    status: Literal["ok"] = Field(default="ok", description="Liveness status")


class ReadinessResponse(BaseModel):
    """Response schema for readiness probe."""

    status: Literal["ready", "not_ready"] = Field(
        ..., description="Readiness status"
    )
    message: str | None = Field(
        None, description="Additional context for not_ready status"
    )
