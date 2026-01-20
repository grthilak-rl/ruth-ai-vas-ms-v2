"""
Unified Runtime Configuration

Defines routing rules for which models use unified runtime vs existing containers.
"""

from typing import Dict, Literal
from pydantic_settings import BaseSettings
from pydantic import Field


class UnifiedRuntimeConfig(BaseSettings):
    """Configuration for unified runtime integration."""

    # Unified runtime URL
    unified_runtime_url: str = Field(
        default="http://unified-ai-runtime:8000",
        description="Unified AI Runtime base URL",
        validation_alias="UNIFIED_RUNTIME_URL"
    )

    # Enable unified runtime (feature flag)
    enable_unified_runtime: bool = Field(
        default=True,
        description="Enable routing to unified runtime",
        validation_alias="UNIFIED_RUNTIME_ENABLE"
    )

    # Timeout for unified runtime requests
    unified_runtime_timeout: float = Field(
        default=30.0,
        description="Timeout for unified runtime inference requests (seconds)",
        validation_alias="UNIFIED_RUNTIME_TIMEOUT"
    )

    # Model routing configuration
    # Maps model_id to routing target: "unified" or "container"
    model_routing: Dict[str, Literal["unified", "container"]] = Field(
        default_factory=lambda: {
            # New models → unified runtime
            "fall_detection": "unified",
            "helmet_detection": "unified",
            "fire_detection": "unified",
            "intrusion_detection": "unified",

            # Demo models → existing containers (protected)
            "fall_detection_container": "container",
            "ppe_detection_container": "container",
        },
        description="Model routing configuration"
    )

    class Config:
        env_prefix = "UNIFIED_RUNTIME_"
        case_sensitive = False


# Global config instance
_config: UnifiedRuntimeConfig | None = None


def get_unified_runtime_config() -> UnifiedRuntimeConfig:
    """Get the global unified runtime configuration."""
    global _config
    if _config is None:
        _config = UnifiedRuntimeConfig()
    return _config


def should_use_unified_runtime(model_id: str) -> bool:
    """
    Determine if a model should use unified runtime.

    Args:
        model_id: Model identifier

    Returns:
        True if model should use unified runtime, False for container
    """
    config = get_unified_runtime_config()

    if not config.enable_unified_runtime:
        return False

    # Check routing configuration
    routing = config.model_routing.get(model_id, "unified")
    return routing == "unified"
