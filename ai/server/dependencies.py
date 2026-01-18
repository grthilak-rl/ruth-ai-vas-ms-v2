"""
Ruth AI Unified Runtime - FastAPI Dependencies

Provides dependency injection for runtime components.
"""

from typing import Optional

from ai.runtime.registry import ModelRegistry
from ai.runtime.pipeline import InferencePipeline
from ai.runtime.reporting import HealthReporter
from ai.runtime.sandbox import SandboxManager

# Global runtime components (initialized at startup)
_registry: Optional[ModelRegistry] = None
_pipeline: Optional[InferencePipeline] = None
_reporter: Optional[HealthReporter] = None
_sandbox_manager: Optional[SandboxManager] = None


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
