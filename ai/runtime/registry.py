"""
Ruth AI Runtime - Model Registry

This module provides the in-memory registry for tracking all discovered,
validated, and loaded models. It serves as the central coordination point
for model lifecycle management.

The registry is thread-safe and supports concurrent reads with exclusive
writes using a read-write lock pattern.

Design Principles:
- Thread-safe operations for concurrent access
- Model-agnostic (no knowledge of what models do)
- Failure isolation (one model's state doesn't affect others)
- Observable (emits events for state changes)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Iterator, Optional

from ai.runtime.models import (
    HealthStatus,
    LoadState,
    ModelDescriptor,
    ModelVersionDescriptor,
)

logger = logging.getLogger(__name__)


# =============================================================================
# EVENTS - Registry state change events
# =============================================================================


class RegistryEventType(Enum):
    """Types of events emitted by the registry."""

    MODEL_DISCOVERED = "model_discovered"
    MODEL_REMOVED = "model_removed"
    VERSION_DISCOVERED = "version_discovered"
    VERSION_REMOVED = "version_removed"
    STATE_CHANGED = "state_changed"
    HEALTH_CHANGED = "health_changed"


@dataclass
class RegistryEvent:
    """Event emitted when registry state changes."""

    event_type: RegistryEventType
    model_id: str
    version: Optional[str] = None
    old_state: Optional[LoadState] = None
    new_state: Optional[LoadState] = None
    old_health: Optional[HealthStatus] = None
    new_health: Optional[HealthStatus] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        result = {
            "event_type": self.event_type.value,
            "model_id": self.model_id,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.version:
            result["version"] = self.version
        if self.old_state:
            result["old_state"] = self.old_state.value
        if self.new_state:
            result["new_state"] = self.new_state.value
        if self.old_health:
            result["old_health"] = self.old_health.value
        if self.new_health:
            result["new_health"] = self.new_health.value
        return result


# Type alias for event listeners
EventListener = Callable[[RegistryEvent], None]


# =============================================================================
# MODEL REGISTRY
# =============================================================================


class ModelRegistry:
    """
    Thread-safe in-memory registry for model descriptors.

    The registry maintains:
    - All discovered models and their versions
    - Current lifecycle state of each version
    - Health status of loaded models
    - Event listeners for state changes

    Usage:
        registry = ModelRegistry()
        registry.register_version(descriptor)

        # Query models
        model = registry.get_model("fall_detection")
        version = registry.get_version("fall_detection", "1.0.0")

        # Update state
        registry.update_state("fall_detection", "1.0.0", LoadState.READY)

        # Subscribe to events
        registry.add_listener(my_callback)
    """

    def __init__(self):
        """Initialize an empty registry."""
        self._models: dict[str, ModelDescriptor] = {}
        self._lock = threading.RWLock() if hasattr(threading, 'RWLock') else _RWLock()
        self._listeners: list[EventListener] = []
        self._listener_lock = threading.Lock()

    # =========================================================================
    # Registration Methods
    # =========================================================================

    def register_model(self, model: ModelDescriptor) -> None:
        """
        Register a new model (without versions).

        Use this when discovering a model directory before
        scanning its versions.

        Args:
            model: Model descriptor to register
        """
        with self._lock.write():
            if model.model_id in self._models:
                logger.warning(
                    "Model already registered, skipping",
                    extra={"model_id": model.model_id},
                )
                return

            self._models[model.model_id] = model

            logger.info(
                "Model registered",
                extra={
                    "model_id": model.model_id,
                    "path": str(model.directory_path),
                },
            )

        self._emit(
            RegistryEvent(
                event_type=RegistryEventType.MODEL_DISCOVERED,
                model_id=model.model_id,
            )
        )

    def register_version(self, descriptor: ModelVersionDescriptor) -> None:
        """
        Register a model version.

        If the parent model doesn't exist, it will be created.

        Args:
            descriptor: Version descriptor to register
        """
        with self._lock.write():
            model_id = descriptor.model_id

            # Create parent model if needed
            if model_id not in self._models:
                self._models[model_id] = ModelDescriptor(
                    model_id=model_id,
                    directory_path=descriptor.directory_path.parent,
                )
                logger.info(
                    "Model auto-created for version",
                    extra={"model_id": model_id},
                )

            # Add version to model
            model = self._models[model_id]
            model.add_version(descriptor)

            logger.info(
                "Version registered",
                extra={
                    "model_id": model_id,
                    "version": descriptor.version,
                    "state": descriptor.state.value,
                },
            )

        self._emit(
            RegistryEvent(
                event_type=RegistryEventType.VERSION_DISCOVERED,
                model_id=model_id,
                version=descriptor.version,
                new_state=descriptor.state,
            )
        )

    def unregister_model(self, model_id: str) -> Optional[ModelDescriptor]:
        """
        Remove a model and all its versions from the registry.

        Args:
            model_id: Model to remove

        Returns:
            Removed ModelDescriptor or None if not found
        """
        with self._lock.write():
            model = self._models.pop(model_id, None)

            if model:
                logger.info(
                    "Model unregistered",
                    extra={
                        "model_id": model_id,
                        "versions_removed": model.version_count,
                    },
                )

        if model:
            self._emit(
                RegistryEvent(
                    event_type=RegistryEventType.MODEL_REMOVED,
                    model_id=model_id,
                )
            )

        return model

    def unregister_version(
        self, model_id: str, version: str
    ) -> Optional[ModelVersionDescriptor]:
        """
        Remove a specific version from the registry.

        Args:
            model_id: Parent model ID
            version: Version to remove

        Returns:
            Removed descriptor or None if not found
        """
        with self._lock.write():
            if model_id not in self._models:
                return None

            model = self._models[model_id]
            descriptor = model.remove_version(version)

            if descriptor:
                logger.info(
                    "Version unregistered",
                    extra={"model_id": model_id, "version": version},
                )

                # Remove empty models
                if model.version_count == 0:
                    del self._models[model_id]
                    logger.info(
                        "Empty model removed",
                        extra={"model_id": model_id},
                    )

        if descriptor:
            self._emit(
                RegistryEvent(
                    event_type=RegistryEventType.VERSION_REMOVED,
                    model_id=model_id,
                    version=version,
                )
            )

        return descriptor

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_model(self, model_id: str) -> Optional[ModelDescriptor]:
        """
        Get a model descriptor by ID.

        Args:
            model_id: Model identifier

        Returns:
            ModelDescriptor or None if not found
        """
        with self._lock.read():
            return self._models.get(model_id)

    def get_version(
        self, model_id: str, version: str
    ) -> Optional[ModelVersionDescriptor]:
        """
        Get a specific version descriptor.

        Args:
            model_id: Model identifier
            version: Version string

        Returns:
            ModelVersionDescriptor or None if not found
        """
        with self._lock.read():
            model = self._models.get(model_id)
            if model:
                return model.get_version(version)
            return None

    def get_all_models(self) -> list[ModelDescriptor]:
        """
        Get all registered models.

        Returns:
            List of all ModelDescriptors
        """
        with self._lock.read():
            return list(self._models.values())

    def get_all_versions(self) -> list[ModelVersionDescriptor]:
        """
        Get all registered versions across all models.

        Returns:
            List of all ModelVersionDescriptors
        """
        with self._lock.read():
            versions = []
            for model in self._models.values():
                versions.extend(model.versions.values())
            return versions

    def get_ready_versions(self) -> list[ModelVersionDescriptor]:
        """
        Get all versions in READY state.

        Returns:
            List of ready ModelVersionDescriptors
        """
        with self._lock.read():
            ready = []
            for model in self._models.values():
                for version in model.versions.values():
                    if version.state == LoadState.READY:
                        ready.append(version)
            return ready

    def get_versions_by_state(
        self, state: LoadState
    ) -> list[ModelVersionDescriptor]:
        """
        Get all versions in a specific state.

        Args:
            state: LoadState to filter by

        Returns:
            List of matching ModelVersionDescriptors
        """
        with self._lock.read():
            matches = []
            for model in self._models.values():
                for version in model.versions.values():
                    if version.state == state:
                        matches.append(version)
            return matches

    def model_exists(self, model_id: str) -> bool:
        """Check if a model is registered."""
        with self._lock.read():
            return model_id in self._models

    def version_exists(self, model_id: str, version: str) -> bool:
        """Check if a specific version is registered."""
        with self._lock.read():
            model = self._models.get(model_id)
            if model:
                return version in model.versions
            return False

    @property
    def model_count(self) -> int:
        """Get number of registered models."""
        with self._lock.read():
            return len(self._models)

    @property
    def version_count(self) -> int:
        """Get total number of registered versions."""
        with self._lock.read():
            return sum(m.version_count for m in self._models.values())

    @property
    def ready_count(self) -> int:
        """Get number of versions in READY state."""
        with self._lock.read():
            count = 0
            for model in self._models.values():
                count += len(model.ready_versions)
            return count

    # =========================================================================
    # State Management
    # =========================================================================

    def update_state(
        self,
        model_id: str,
        version: str,
        new_state: LoadState,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> bool:
        """
        Update the state of a model version.

        Args:
            model_id: Model identifier
            version: Version string
            new_state: New LoadState
            error: Optional error message
            error_code: Optional error code

        Returns:
            True if update successful, False if version not found
        """
        old_state = None

        with self._lock.write():
            model = self._models.get(model_id)
            if not model:
                return False

            descriptor = model.get_version(version)
            if not descriptor:
                return False

            old_state = descriptor.state
            descriptor.transition_to(new_state, error, error_code)

            logger.info(
                "Version state changed",
                extra={
                    "model_id": model_id,
                    "version": version,
                    "old_state": old_state.value,
                    "new_state": new_state.value,
                },
            )

        self._emit(
            RegistryEvent(
                event_type=RegistryEventType.STATE_CHANGED,
                model_id=model_id,
                version=version,
                old_state=old_state,
                new_state=new_state,
            )
        )

        return True

    def update_health(
        self,
        model_id: str,
        version: str,
        new_health: HealthStatus,
    ) -> bool:
        """
        Update the health status of a model version.

        Args:
            model_id: Model identifier
            version: Version string
            new_health: New HealthStatus

        Returns:
            True if update successful, False if version not found
        """
        old_health = None

        with self._lock.write():
            model = self._models.get(model_id)
            if not model:
                return False

            descriptor = model.get_version(version)
            if not descriptor:
                return False

            old_health = descriptor.health
            descriptor.health = new_health

            logger.info(
                "Version health changed",
                extra={
                    "model_id": model_id,
                    "version": version,
                    "old_health": old_health.value,
                    "new_health": new_health.value,
                },
            )

        self._emit(
            RegistryEvent(
                event_type=RegistryEventType.HEALTH_CHANGED,
                model_id=model_id,
                version=version,
                old_health=old_health,
                new_health=new_health,
            )
        )

        return True

    def record_inference(self, model_id: str, version: str) -> None:
        """
        Record a successful inference for metrics.

        Args:
            model_id: Model identifier
            version: Version string
        """
        with self._lock.write():
            model = self._models.get(model_id)
            if model:
                descriptor = model.get_version(version)
                if descriptor:
                    descriptor.inference_count += 1

    def record_error(self, model_id: str, version: str) -> None:
        """
        Record an error for metrics.

        Args:
            model_id: Model identifier
            version: Version string
        """
        with self._lock.write():
            model = self._models.get(model_id)
            if model:
                descriptor = model.get_version(version)
                if descriptor:
                    descriptor.error_count += 1

    # =========================================================================
    # Event System
    # =========================================================================

    def add_listener(self, listener: EventListener) -> None:
        """
        Add an event listener.

        Args:
            listener: Callback function for events
        """
        with self._listener_lock:
            self._listeners.append(listener)

    def remove_listener(self, listener: EventListener) -> bool:
        """
        Remove an event listener.

        Args:
            listener: Listener to remove

        Returns:
            True if removed, False if not found
        """
        with self._listener_lock:
            try:
                self._listeners.remove(listener)
                return True
            except ValueError:
                return False

    def _emit(self, event: RegistryEvent) -> None:
        """Emit an event to all listeners."""
        with self._listener_lock:
            listeners = list(self._listeners)

        for listener in listeners:
            try:
                listener(event)
            except Exception as e:
                logger.error(
                    "Event listener error",
                    extra={
                        "event_type": event.event_type.value,
                        "error": str(e),
                    },
                )

    # =========================================================================
    # Serialization
    # =========================================================================

    def to_dict(self) -> dict[str, Any]:
        """
        Convert registry state to dictionary.

        Useful for API responses and debugging.
        """
        with self._lock.read():
            return {
                "model_count": len(self._models),
                "version_count": sum(m.version_count for m in self._models.values()),
                "ready_count": sum(
                    len(m.ready_versions) for m in self._models.values()
                ),
                "models": {
                    model_id: model.to_dict()
                    for model_id, model in self._models.items()
                },
            }

    def get_status_summary(self) -> dict[str, int]:
        """
        Get summary counts by state.

        Returns:
            Dictionary mapping state names to counts
        """
        with self._lock.read():
            counts: dict[str, int] = {}
            for model in self._models.values():
                for version in model.versions.values():
                    state_name = version.state.value
                    counts[state_name] = counts.get(state_name, 0) + 1
            return counts


# =============================================================================
# READ-WRITE LOCK IMPLEMENTATION
# =============================================================================


class _RWLock:
    """
    Fair read-write lock for thread safety.

    Allows multiple concurrent readers but exclusive writers.
    Uses writer-preference to prevent writer starvation:
    - When a writer is waiting, new readers block
    - Existing readers complete, then writer runs
    - After writer, readers can proceed again

    This prevents the case where a continuous stream of readers
    could indefinitely block a waiting writer.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._readers_ok = threading.Condition(self._lock)
        self._writers_ok = threading.Condition(self._lock)
        self._readers = 0
        self._writers_waiting = 0
        self._writer_active = False

    def read(self) -> "_RWLockReadContext":
        """Acquire read lock."""
        return _RWLockReadContext(self)

    def write(self) -> "_RWLockWriteContext":
        """Acquire write lock."""
        return _RWLockWriteContext(self)

    def _acquire_read(self) -> None:
        with self._lock:
            # Wait if a writer is active OR if writers are waiting
            # (writer-preference to prevent starvation)
            while self._writer_active or self._writers_waiting > 0:
                self._readers_ok.wait()
            self._readers += 1

    def _release_read(self) -> None:
        with self._lock:
            self._readers -= 1
            if self._readers == 0:
                # Wake up any waiting writer
                self._writers_ok.notify()

    def _acquire_write(self) -> None:
        with self._lock:
            self._writers_waiting += 1
            try:
                # Wait for all readers to finish and no other writer active
                while self._readers > 0 or self._writer_active:
                    self._writers_ok.wait()
                self._writer_active = True
            finally:
                self._writers_waiting -= 1

    def _release_write(self) -> None:
        with self._lock:
            self._writer_active = False
            # If there are waiting writers, wake one up
            # Otherwise, wake up all waiting readers
            if self._writers_waiting > 0:
                self._writers_ok.notify()
            else:
                self._readers_ok.notify_all()


class _RWLockReadContext:
    """Context manager for read lock."""

    def __init__(self, lock: _RWLock):
        self._lock = lock

    def __enter__(self) -> "_RWLockReadContext":
        self._lock._acquire_read()
        return self

    def __exit__(self, *args: Any) -> None:
        self._lock._release_read()


class _RWLockWriteContext:
    """Context manager for write lock."""

    def __init__(self, lock: _RWLock):
        self._lock = lock

    def __enter__(self) -> "_RWLockWriteContext":
        self._lock._acquire_write()
        return self

    def __exit__(self, *args: Any) -> None:
        self._lock._release_write()
