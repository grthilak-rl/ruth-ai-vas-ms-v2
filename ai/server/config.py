"""
Ruth AI Unified Runtime - Configuration

Centralized configuration management using pydantic-settings.
Follows 12-Factor App principles for container deployments.

All configuration is loaded from environment variables with sensible defaults.

Environment Variables:
    # Deployment Profile
    RUTH_AI_ENV: Environment (development, test, production) - default: production
    RUTH_AI_PROFILE: Deployment profile (dev, test, prod-cpu, prod-gpu, edge-jetson)

    # Server
    SERVER_HOST: Server bind host (default: 0.0.0.0)
    SERVER_PORT: Server port (default: 8000)
    LOG_LEVEL: Logging level (default: INFO)
    LOG_FORMAT: Log format: json or text (default: json)

    # Runtime
    RUNTIME_ID: Unique runtime instance ID (auto-generated if not set)
    MODELS_ROOT: Path to models directory (default: ./models)
    MAX_CONCURRENT_INFERENCES: Max concurrent inferences (default: 10)
    AI_RUNTIME_HARDWARE: Hardware mode (auto, cpu, gpu, jetson) - default: auto

    # GPU
    ENABLE_GPU: Enable GPU usage (default: true)
    GPU_MEMORY_RESERVE_MB: Memory to reserve for PyTorch (default: 512)
    GPU_FALLBACK_TO_CPU: Fall back to CPU when GPU unavailable (default: true)

    # Metrics
    METRICS_ENABLED: Enable Prometheus metrics (default: true)

    # Observability
    REQUEST_ID_HEADER: Header name for request ID (default: X-Request-ID)

    # Shutdown
    GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS: Timeout for graceful shutdown (default: 30)

Usage:
    from ai.server.config import get_config

    config = get_config()
    print(config.server_host)
"""

import os
import uuid
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class RuntimeConfig(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    # =========================================================================
    # Deployment Profile (12-Factor: III. Config)
    # =========================================================================

    ruth_ai_env: str = Field(
        default="production",
        description="Environment name (development, test, production)"
    )

    ruth_ai_profile: str = Field(
        default="prod-cpu",
        description="Deployment profile (dev, test, prod-cpu, prod-gpu, edge-jetson)"
    )

    ai_runtime_hardware: str = Field(
        default="auto",
        description="Hardware mode: auto (detect), cpu, gpu, jetson"
    )

    # =========================================================================
    # Server Configuration
    # =========================================================================

    server_host: str = Field(
        default="0.0.0.0",
        description="Server bind host"
    )

    server_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Server port"
    )

    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    log_format: str = Field(
        default="json",
        description="Log format (json or text)"
    )

    # =========================================================================
    # Runtime Configuration
    # =========================================================================

    runtime_id: str = Field(
        default_factory=lambda: f"unified-runtime-{uuid.uuid4().hex[:8]}",
        description="Unique runtime instance identifier"
    )

    models_root: str = Field(
        default="./models",
        description="Path to models directory"
    )

    max_concurrent_inferences: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Maximum concurrent inference requests"
    )

    # =========================================================================
    # GPU Configuration
    # =========================================================================

    enable_gpu: bool = Field(
        default=True,
        description="Enable GPU usage"
    )

    gpu_memory_reserve_mb: float = Field(
        default=512.0,
        ge=0,
        description="Memory to reserve for PyTorch overhead (MB)"
    )

    gpu_fallback_to_cpu: bool = Field(
        default=True,
        description="Fall back to CPU when GPU unavailable or full"
    )

    # =========================================================================
    # Metrics Configuration
    # =========================================================================

    metrics_enabled: bool = Field(
        default=True,
        description="Enable Prometheus metrics collection"
    )

    metrics_update_interval_seconds: float = Field(
        default=15.0,
        ge=1.0,
        description="Interval for updating GPU metrics"
    )

    # =========================================================================
    # Observability Configuration
    # =========================================================================

    request_id_header: str = Field(
        default="X-Request-ID",
        description="HTTP header name for request ID"
    )

    redact_log_fields: list = Field(
        default=["frame_base64", "password", "token", "api_key"],
        description="Fields to redact in structured logs"
    )

    # =========================================================================
    # Model Configuration
    # =========================================================================

    model_warmup_enabled: bool = Field(
        default=True,
        description="Enable warmup inference after model load"
    )

    model_load_timeout_ms: int = Field(
        default=60000,
        ge=1000,
        description="Model loading timeout (milliseconds)"
    )

    # =========================================================================
    # Shutdown Configuration
    # =========================================================================

    graceful_shutdown_timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Timeout for graceful shutdown (seconds)"
    )

    # =========================================================================
    # Pydantic Configuration
    # =========================================================================

    class Config:
        """Pydantic configuration."""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Ignore extra environment variables


@lru_cache()
def get_config() -> RuntimeConfig:
    """
    Get runtime configuration (cached).

    Returns:
        RuntimeConfig instance
    """
    return RuntimeConfig()


def reload_config() -> RuntimeConfig:
    """
    Reload configuration (clears cache).

    Returns:
        Fresh RuntimeConfig instance
    """
    get_config.cache_clear()
    return get_config()
