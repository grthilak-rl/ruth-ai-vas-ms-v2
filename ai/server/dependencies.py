"""
Ruth AI Unified Runtime - FastAPI Dependencies

Provides dependency injection for runtime components.
"""

from typing import Optional

from ai.runtime.registry import ModelRegistry
from ai.runtime.pipeline import InferencePipeline
from ai.runtime.reporting import HealthReporter, CapabilityPublisher
from ai.runtime.sandbox import SandboxManager
from ai.runtime.backend_client import HTTPBackendClient

# Global runtime components (initialized at startup)
_registry: Optional[ModelRegistry] = None
_pipeline: Optional[InferencePipeline] = None
_reporter: Optional[HealthReporter] = None
_sandbox_manager: Optional[SandboxManager] = None
_backend_client: Optional[HTTPBackendClient] = None
_capability_publisher: Optional[CapabilityPublisher] = None


def set_registry(registry: ModelRegistry) -> None:
    """Set the global registry instance."""
    global _registry
    _registry = registry


def get_registry() -> Optional[ModelRegistry]:
    """Get the global registry instance."""
    return _registry


def set_pipeline(pipeline: InferencePipeline) -> None:
    """Set the global pipeline instance."""
    global _pipeline
    _pipeline = pipeline


def get_pipeline() -> Optional[InferencePipeline]:
    """Get the global pipeline instance."""
    return _pipeline


def set_reporter(reporter: HealthReporter) -> None:
    """Set the global reporter instance."""
    global _reporter
    _reporter = reporter


def get_reporter() -> Optional[HealthReporter]:
    """Get the global reporter instance."""
    return _reporter


def set_sandbox_manager(sandbox_manager: SandboxManager) -> None:
    """Set the global sandbox manager instance."""
    global _sandbox_manager
    _sandbox_manager = sandbox_manager


def get_sandbox_manager() -> Optional[SandboxManager]:
    """Get the global sandbox manager instance."""
    return _sandbox_manager


def set_backend_client(client: HTTPBackendClient) -> None:
    """Set the global backend client instance."""
    global _backend_client
    _backend_client = client


def get_backend_client() -> Optional[HTTPBackendClient]:
    """Get the global backend client instance."""
    return _backend_client


def set_capability_publisher(publisher: CapabilityPublisher) -> None:
    """Set the global capability publisher instance."""
    global _capability_publisher
    _capability_publisher = publisher


def get_capability_publisher() -> Optional[CapabilityPublisher]:
    """Get the global capability publisher instance."""
    return _capability_publisher


def clear_all() -> None:
    """Clear all global instances during shutdown."""
    global _registry, _pipeline, _reporter, _sandbox_manager
    global _backend_client, _capability_publisher
    _registry = None
    _pipeline = None
    _reporter = None
    _sandbox_manager = None
    _backend_client = None
    _capability_publisher = None
