"""
Ruth AI Runtime - Model Health & Capability Reporting

This module provides push-based capability registration and health reporting
from the AI Runtime to the backend. It implements the runtime-side of the
Backend ↔ AI Runtime health contract.

Design Principles:
- Push-based: Runtime pushes state to backend, no polling
- Per-version: Health is tracked per model version (authoritative)
- Derived aggregation: Model-level health is derived from versions
- Failure tolerant: Backend outages don't crash runtime
- Model-agnostic: No model-specific logic

Health Derivation Rules:
- Per-version health is authoritative (from ExecutionSandbox/HealthManager)
- Model-level health is derived:
  - Any HEALTHY version → model_id is HEALTHY
  - No HEALTHY, but ≥1 DEGRADED → model_id is DEGRADED
  - All UNHEALTHY → model_id is UNAVAILABLE (not advertised)
- UNHEALTHY versions are NOT advertised to backend
- DEGRADED versions ARE advertised with health=DEGRADED

Retry Behavior:
- Exponential backoff on backend failures (1s → 2s → 4s → ... → 60s max)
- Retries are capped to prevent unbounded growth
- Last-known-good state retained locally during outages
- Correlation IDs in all logs for tracing

Usage:
    from ai.runtime.reporting import (
        CapabilityPublisher,
        HealthAggregator,
        RuntimeCapacityTracker,
    )

    # Initialize
    aggregator = HealthAggregator(registry)
    capacity = RuntimeCapacityTracker(max_concurrent=10)
    publisher = CapabilityPublisher(
        registry=registry,
        aggregator=aggregator,
        capacity_tracker=capacity,
        backend_url="http://backend:8080",
    )

    # Start publishing (listens to registry events)
    publisher.start()

    # On shutdown
    publisher.stop()
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional, Protocol

from ai.runtime.models import (
    HealthStatus,
    InputType,
    LoadState,
    ModelDescriptor,
    ModelVersionDescriptor,
)
from ai.runtime.registry import (
    ModelRegistry,
    RegistryEvent,
    RegistryEventType,
)

# Forward reference for optional ConcurrencyManager integration
# Import at runtime to avoid circular imports
TYPE_CHECKING = False
if TYPE_CHECKING:
    from ai.runtime.concurrency import ConcurrencyManager

logger = logging.getLogger(__name__)


# =============================================================================
# CAPABILITY PAYLOAD - What we report to backend
# =============================================================================


class ModelStatus(Enum):
    """Model operational status for backend reporting."""

    ACTIVE = "active"  # Model is running and processing frames
    IDLE = "idle"  # Model is loaded but not processing
    STARTING = "starting"  # Model is initializing
    STOPPING = "stopping"  # Model is shutting down
    ERROR = "error"  # Model encountered an error


@dataclass
class VersionCapability:
    """
    Capability payload for a single model version.

    This is the unit of registration pushed to the backend.
    Only READY versions with HEALTHY or DEGRADED health are advertised.
    """

    model_id: str
    version: str
    display_name: str
    description: str

    # Input capabilities (opaque to backend)
    input_types: list[str]  # ["frame", "batch", "temporal"]
    input_format: str  # "jpeg", "png", etc.

    # Output declaration (opaque to backend)
    output_event_types: list[str]  # ["fall_detected", "no_fall"]
    provides_bounding_boxes: bool
    provides_metadata: bool

    # Hardware compatibility
    supports_cpu: bool
    supports_gpu: bool
    supports_jetson: bool

    # Performance hints (advisory)
    inference_time_hint_ms: int
    recommended_fps: int
    max_fps: Optional[int]
    recommended_batch_size: int
    max_concurrent: int

    # Current state
    status: ModelStatus
    health: HealthStatus
    degraded_reason: Optional[str] = None

    # Metrics
    inference_count: int = 0
    error_count: int = 0
    last_inference_at: Optional[datetime] = None

    # Timestamps
    registered_at: datetime = field(default_factory=datetime.utcnow)
    last_health_change: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API payload."""
        result = {
            "model_id": self.model_id,
            "version": self.version,
            "display_name": self.display_name,
            "description": self.description,
            "input_types": self.input_types,
            "input_format": self.input_format,
            "output_event_types": self.output_event_types,
            "provides_bounding_boxes": self.provides_bounding_boxes,
            "provides_metadata": self.provides_metadata,
            "hardware": {
                "supports_cpu": self.supports_cpu,
                "supports_gpu": self.supports_gpu,
                "supports_jetson": self.supports_jetson,
            },
            "performance": {
                "inference_time_hint_ms": self.inference_time_hint_ms,
                "recommended_fps": self.recommended_fps,
                "max_fps": self.max_fps,
                "recommended_batch_size": self.recommended_batch_size,
                "max_concurrent": self.max_concurrent,
            },
            "status": self.status.value,
            "health": self.health.value,
            "metrics": {
                "inference_count": self.inference_count,
                "error_count": self.error_count,
            },
            "registered_at": self.registered_at.isoformat(),
        }

        if self.degraded_reason:
            result["degraded_reason"] = self.degraded_reason
        if self.last_inference_at:
            result["last_inference_at"] = self.last_inference_at.isoformat()
        if self.last_health_change:
            result["last_health_change"] = self.last_health_change.isoformat()

        return result

    @classmethod
    def from_descriptor(
        cls,
        descriptor: ModelVersionDescriptor,
        status: ModelStatus = ModelStatus.IDLE,
        degraded_reason: Optional[str] = None,
    ) -> "VersionCapability":
        """
        Create capability from a model version descriptor.

        This is the bridge from runtime data models to reporting payloads.
        """
        # Determine input types from specification
        input_types = [descriptor.input_spec.type.value]
        if descriptor.capabilities.supports_batching:
            if InputType.BATCH.value not in input_types:
                input_types.append(InputType.BATCH.value)

        return cls(
            model_id=descriptor.model_id,
            version=descriptor.version,
            display_name=descriptor.display_name,
            description=descriptor.description,
            input_types=input_types,
            input_format=descriptor.input_spec.format.value,
            output_event_types=list(descriptor.output_spec.event_type_enum),
            provides_bounding_boxes=descriptor.output_spec.provides_bounding_boxes,
            provides_metadata=descriptor.output_spec.provides_metadata,
            supports_cpu=descriptor.hardware.supports_cpu,
            supports_gpu=descriptor.hardware.supports_gpu,
            supports_jetson=descriptor.hardware.supports_jetson,
            inference_time_hint_ms=descriptor.performance.inference_time_hint_ms,
            recommended_fps=descriptor.performance.recommended_fps,
            max_fps=descriptor.performance.max_fps,
            recommended_batch_size=descriptor.performance.recommended_batch_size,
            max_concurrent=descriptor.limits.max_concurrent_inferences,
            status=status,
            health=descriptor.health,
            degraded_reason=degraded_reason,
            inference_count=descriptor.inference_count,
            error_count=descriptor.error_count,
            last_health_change=descriptor.last_state_change,
        )


@dataclass
class ModelCapabilityReport:
    """
    Aggregated capability report for a model (all versions).

    This is used for model-level health reporting.
    """

    model_id: str
    health: HealthStatus  # Derived from version healths
    versions: list[VersionCapability]
    total_versions: int
    healthy_versions: int
    degraded_versions: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API payload."""
        return {
            "model_id": self.model_id,
            "health": self.health.value,
            "total_versions": self.total_versions,
            "healthy_versions": self.healthy_versions,
            "degraded_versions": self.degraded_versions,
            "versions": [v.to_dict() for v in self.versions],
        }


@dataclass
class RuntimeCapacityReport:
    """
    Runtime-level capacity report.

    Advisory information about runtime resource availability.
    """

    # Concurrency
    max_concurrent_inferences: int
    active_inferences: int
    available_slots: int

    # Per-model limits
    per_model_limits: dict[str, int]  # model_id -> max_concurrent

    # Backpressure indicators
    backpressure_level: str  # "none", "soft", "hard"
    queue_depth: int
    queue_capacity: int

    # Resource usage
    memory_used_mb: Optional[int] = None
    memory_available_mb: Optional[int] = None
    gpu_memory_used_mb: Optional[int] = None
    gpu_memory_available_mb: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API payload."""
        result = {
            "concurrency": {
                "max_concurrent": self.max_concurrent_inferences,
                "active": self.active_inferences,
                "available": self.available_slots,
            },
            "per_model_limits": self.per_model_limits,
            "backpressure": {
                "level": self.backpressure_level,
                "queue_depth": self.queue_depth,
                "queue_capacity": self.queue_capacity,
            },
        }

        if self.memory_used_mb is not None:
            result["memory"] = {
                "used_mb": self.memory_used_mb,
                "available_mb": self.memory_available_mb,
            }

        if self.gpu_memory_used_mb is not None:
            result["gpu_memory"] = {
                "used_mb": self.gpu_memory_used_mb,
                "available_mb": self.gpu_memory_available_mb,
            }

        return result


@dataclass
class FullCapabilityReport:
    """
    Complete capability and health report pushed to backend.

    This is the top-level payload for registration.
    """

    runtime_id: str
    timestamp: datetime
    models: list[ModelCapabilityReport]
    capacity: RuntimeCapacityReport
    runtime_health: HealthStatus

    # Summary statistics
    total_models: int
    healthy_models: int
    total_versions: int
    ready_versions: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API payload."""
        return {
            "runtime_id": self.runtime_id,
            "timestamp": self.timestamp.isoformat(),
            "runtime_health": self.runtime_health.value,
            "summary": {
                "total_models": self.total_models,
                "healthy_models": self.healthy_models,
                "total_versions": self.total_versions,
                "ready_versions": self.ready_versions,
            },
            "models": [m.to_dict() for m in self.models],
            "capacity": self.capacity.to_dict(),
        }


# =============================================================================
# HEALTH AGGREGATOR - Derives model-level health from versions
# =============================================================================


class HealthAggregator:
    """
    Aggregates version-level health into model-level health.

    Health Derivation Rules:
    - Per-version health is authoritative
    - Model health is derived from version healths:
      - Any HEALTHY version → model is HEALTHY
      - No HEALTHY, but ≥1 DEGRADED → model is DEGRADED
      - All UNHEALTHY or no ready versions → model is UNAVAILABLE

    The aggregator is stateless - it computes health on demand.
    """

    def __init__(self, registry: ModelRegistry):
        """
        Initialize the health aggregator.

        Args:
            registry: Model registry for reading version states
        """
        self.registry = registry

    def get_version_health(
        self,
        model_id: str,
        version: str,
    ) -> Optional[HealthStatus]:
        """
        Get health status for a specific version.

        Returns None if version not found or not ready.
        """
        descriptor = self.registry.get_version(model_id, version)
        if descriptor is None:
            return None
        if descriptor.state != LoadState.READY:
            return None
        return descriptor.health

    def get_model_health(self, model_id: str) -> HealthStatus:
        """
        Derive model-level health from version healths.

        Rules:
        - Any HEALTHY version → HEALTHY
        - No HEALTHY, ≥1 DEGRADED → DEGRADED
        - All UNHEALTHY or no versions → UNHEALTHY
        """
        model = self.registry.get_model(model_id)
        if model is None:
            return HealthStatus.UNHEALTHY

        healthy_count = 0
        degraded_count = 0
        ready_count = 0

        for version in model.versions.values():
            if version.state != LoadState.READY:
                continue

            ready_count += 1

            if version.health == HealthStatus.HEALTHY:
                healthy_count += 1
            elif version.health == HealthStatus.DEGRADED:
                degraded_count += 1

        # Apply derivation rules
        if healthy_count > 0:
            return HealthStatus.HEALTHY
        if degraded_count > 0:
            return HealthStatus.DEGRADED
        if ready_count == 0:
            return HealthStatus.UNKNOWN

        return HealthStatus.UNHEALTHY

    def get_advertisable_versions(
        self,
        model_id: str,
    ) -> list[ModelVersionDescriptor]:
        """
        Get versions that should be advertised to backend.

        Only READY versions with HEALTHY or DEGRADED health are advertised.
        UNHEALTHY versions are NOT advertised.
        """
        model = self.registry.get_model(model_id)
        if model is None:
            return []

        advertisable = []
        for version in model.versions.values():
            if version.state != LoadState.READY:
                continue
            if version.health in (HealthStatus.HEALTHY, HealthStatus.DEGRADED):
                advertisable.append(version)

        return advertisable

    def get_all_advertisable_versions(self) -> list[ModelVersionDescriptor]:
        """
        Get all versions that should be advertised across all models.
        """
        all_advertisable = []
        for model in self.registry.get_all_models():
            all_advertisable.extend(self.get_advertisable_versions(model.model_id))
        return all_advertisable

    def build_model_report(self, model_id: str) -> Optional[ModelCapabilityReport]:
        """
        Build a capability report for a single model.

        Returns None if model has no advertisable versions.
        """
        model = self.registry.get_model(model_id)
        if model is None:
            return None

        advertisable = self.get_advertisable_versions(model_id)
        if not advertisable:
            return None

        # Convert to capability payloads
        version_capabilities = []
        healthy_count = 0
        degraded_count = 0

        for descriptor in advertisable:
            # Determine operational status
            if descriptor.inference_count > 0:
                status = ModelStatus.ACTIVE
            else:
                status = ModelStatus.IDLE

            # Get degraded reason if applicable
            degraded_reason = None
            if descriptor.health == HealthStatus.DEGRADED:
                degraded_reason = descriptor.last_error

            capability = VersionCapability.from_descriptor(
                descriptor=descriptor,
                status=status,
                degraded_reason=degraded_reason,
            )
            version_capabilities.append(capability)

            if descriptor.health == HealthStatus.HEALTHY:
                healthy_count += 1
            elif descriptor.health == HealthStatus.DEGRADED:
                degraded_count += 1

        model_health = self.get_model_health(model_id)

        return ModelCapabilityReport(
            model_id=model_id,
            health=model_health,
            versions=version_capabilities,
            total_versions=len(model.versions),
            healthy_versions=healthy_count,
            degraded_versions=degraded_count,
        )


# =============================================================================
# RUNTIME CAPACITY TRACKER - Tracks runtime-level capacity
# =============================================================================


class RuntimeCapacityTracker:
    """
    Tracks runtime-level capacity and backpressure.

    This provides advisory information about resource availability.
    Backend may choose to ignore this information.

    Integration with ConcurrencyManager:
    If a ConcurrencyManager is provided, this tracker will use it as the
    source of truth for concurrency data. This prevents duplication and
    ensures consistency between admission control and reporting.

    When no ConcurrencyManager is provided, the tracker maintains its own
    simple slot tracking (for backwards compatibility or standalone use).
    """

    # Backpressure thresholds
    SOFT_THRESHOLD = 0.6  # 60% queue utilization
    HARD_THRESHOLD = 0.8  # 80% queue utilization

    def __init__(
        self,
        max_concurrent: int = 10,
        queue_capacity: int = 100,
        concurrency_manager: Optional["ConcurrencyManager"] = None,
    ):
        """
        Initialize capacity tracker.

        Args:
            max_concurrent: Maximum concurrent inferences (ignored if concurrency_manager provided)
            queue_capacity: Maximum queue depth before hard backpressure
            concurrency_manager: Optional ConcurrencyManager to use as source of truth
        """
        self._concurrency_manager = concurrency_manager
        self.queue_capacity = queue_capacity

        # Use concurrency manager limits if available
        if concurrency_manager is not None:
            self.max_concurrent = concurrency_manager.global_limit
        else:
            self.max_concurrent = max_concurrent

        # Local state (used when no concurrency_manager)
        self._active_count = 0
        self._queue_depth = 0
        self._per_model_limits: dict[str, int] = {}
        self._per_model_active: dict[str, int] = {}
        self._lock = threading.Lock()

    def set_model_limit(self, model_id: str, max_concurrent: int) -> None:
        """Set per-model concurrency limit."""
        if self._concurrency_manager is not None:
            # Delegate to concurrency manager
            self._concurrency_manager.register_model(
                model_id=model_id,
                version="*",  # Model-level limit
                max_concurrent=max_concurrent,
            )
        else:
            with self._lock:
                self._per_model_limits[model_id] = max_concurrent
                if model_id not in self._per_model_active:
                    self._per_model_active[model_id] = 0

    def remove_model(self, model_id: str) -> None:
        """Remove a model from tracking."""
        if self._concurrency_manager is not None:
            # Delegate to concurrency manager
            self._concurrency_manager.unregister_model(model_id)
        else:
            with self._lock:
                self._per_model_limits.pop(model_id, None)
                self._per_model_active.pop(model_id, None)

    def acquire(self, model_id: str) -> bool:
        """
        Try to acquire a slot for inference.

        Returns True if slot acquired, False if at capacity.

        NOTE: When using ConcurrencyManager, prefer using AdmissionController
        directly for full rejection reason information. This method is
        provided for backwards compatibility.
        """
        if self._concurrency_manager is not None:
            # Use concurrency manager - this is a simplified acquire
            # that doesn't return the full ConcurrencySlot
            slot = self._concurrency_manager.try_acquire(
                model_id=model_id,
                version="*",  # Unknown version at this level
                request_id=f"capacity-{model_id}",
            )
            return slot.acquired

        with self._lock:
            # Check global limit
            if self._active_count >= self.max_concurrent:
                return False

            # Check per-model limit
            model_limit = self._per_model_limits.get(model_id, self.max_concurrent)
            model_active = self._per_model_active.get(model_id, 0)
            if model_active >= model_limit:
                return False

            # Acquire
            self._active_count += 1
            self._per_model_active[model_id] = model_active + 1
            return True

    def release(self, model_id: str) -> None:
        """
        Release an inference slot.

        NOTE: When using ConcurrencyManager with AdmissionController,
        slots should be released via ConcurrencySlot.release() instead.
        This method is provided for backwards compatibility.
        """
        if self._concurrency_manager is not None:
            # When using concurrency manager, releases happen through
            # ConcurrencySlot.release() - this is a no-op to avoid
            # double-releasing. The concurrency manager tracks actual slots.
            logger.debug(
                "RuntimeCapacityTracker.release() called with ConcurrencyManager - "
                "slots should be released via ConcurrencySlot.release()"
            )
            return

        with self._lock:
            self._active_count = max(0, self._active_count - 1)
            if model_id in self._per_model_active:
                self._per_model_active[model_id] = max(
                    0, self._per_model_active[model_id] - 1
                )

    def update_queue_depth(self, depth: int) -> None:
        """Update current queue depth."""
        with self._lock:
            self._queue_depth = depth

    def get_backpressure_level(self) -> str:
        """
        Get current backpressure level.

        Returns: "none", "soft", or "hard"
        """
        if self._concurrency_manager is not None:
            # Use concurrency manager's backpressure level
            return self._concurrency_manager.get_backpressure_level().value

        with self._lock:
            if self.queue_capacity == 0:
                return "none"

            utilization = self._queue_depth / self.queue_capacity

            if utilization >= self.HARD_THRESHOLD:
                return "hard"
            if utilization >= self.SOFT_THRESHOLD:
                return "soft"
            return "none"

    def get_report(self) -> RuntimeCapacityReport:
        """Build a capacity report."""
        if self._concurrency_manager is not None:
            # Use concurrency manager as source of truth
            global_stats = self._concurrency_manager.get_global_stats()

            # Build per-model limits from registered models
            per_model_limits = {}
            with self._concurrency_manager._lock:
                for model_id, state in self._concurrency_manager._models.items():
                    per_model_limits[model_id] = state.max_concurrent

            with self._lock:
                return RuntimeCapacityReport(
                    max_concurrent_inferences=global_stats["global_limit"],
                    active_inferences=global_stats["global_active"],
                    available_slots=global_stats["available_slots"],
                    per_model_limits=per_model_limits,
                    backpressure_level=global_stats["backpressure"],
                    queue_depth=self._queue_depth,
                    queue_capacity=self.queue_capacity,
                )

        with self._lock:
            return RuntimeCapacityReport(
                max_concurrent_inferences=self.max_concurrent,
                active_inferences=self._active_count,
                available_slots=max(0, self.max_concurrent - self._active_count),
                per_model_limits=dict(self._per_model_limits),
                backpressure_level=self.get_backpressure_level(),
                queue_depth=self._queue_depth,
                queue_capacity=self.queue_capacity,
            )

    @property
    def active_count(self) -> int:
        """Get current active inference count."""
        if self._concurrency_manager is not None:
            return self._concurrency_manager.get_global_stats()["global_active"]

        with self._lock:
            return self._active_count

    @property
    def available_slots(self) -> int:
        """Get available slots."""
        if self._concurrency_manager is not None:
            return self._concurrency_manager.get_global_stats()["available_slots"]

        with self._lock:
            return max(0, self.max_concurrent - self._active_count)


# =============================================================================
# BACKEND CLIENT PROTOCOL - Interface for backend communication
# =============================================================================


class BackendClientProtocol(Protocol):
    """Protocol for backend communication."""

    def register_capabilities(
        self,
        report: FullCapabilityReport,
        correlation_id: str,
    ) -> bool:
        """
        Push capability report to backend.

        Returns True if successful.
        """
        ...

    def deregister_version(
        self,
        model_id: str,
        version: str,
        correlation_id: str,
    ) -> bool:
        """
        Notify backend that a version is no longer available.

        Returns True if successful.
        """
        ...


class NoOpBackendClient:
    """
    No-op backend client for testing or standalone mode.

    Logs registration attempts but doesn't actually communicate.
    """

    def register_capabilities(
        self,
        report: FullCapabilityReport,
        correlation_id: str,
    ) -> bool:
        logger.info(
            "NoOp: Would register capabilities",
            extra={
                "correlation_id": correlation_id,
                "model_count": report.total_models,
                "version_count": report.ready_versions,
            },
        )
        return True

    def deregister_version(
        self,
        model_id: str,
        version: str,
        correlation_id: str,
    ) -> bool:
        logger.info(
            "NoOp: Would deregister version",
            extra={
                "correlation_id": correlation_id,
                "model_id": model_id,
                "version": version,
            },
        )
        return True


# =============================================================================
# CAPABILITY PUBLISHER - Main orchestration component
# =============================================================================


class PublishTrigger(Enum):
    """Reasons for triggering a capability publish."""

    STARTUP = "startup"  # Runtime startup
    MODEL_LOADED = "model_loaded"  # New model version loaded
    MODEL_UNLOADED = "model_unloaded"  # Model version unloaded
    HEALTH_CHANGED = "health_changed"  # Version health changed
    PERIODIC = "periodic"  # Periodic refresh
    MANUAL = "manual"  # Manual trigger


@dataclass
class PublishRequest:
    """Request to publish capabilities."""

    trigger: PublishTrigger
    model_id: Optional[str] = None
    version: Optional[str] = None
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))


class CapabilityPublisher:
    """
    Orchestrates push-based capability registration to backend.

    This is the main entry point for health and capability reporting.
    It listens to registry events and pushes updates to the backend.

    Features:
    - Push-based (no polling)
    - Event-driven updates
    - Exponential backoff on failures
    - Periodic refresh as safety net
    - Correlation IDs for tracing

    Usage:
        publisher = CapabilityPublisher(
            registry=registry,
            aggregator=health_aggregator,
            capacity_tracker=capacity_tracker,
            backend_client=backend_client,
        )
        publisher.start()
        # ... runtime operates ...
        publisher.stop()
    """

    # Retry configuration
    INITIAL_RETRY_DELAY_S = 1.0
    MAX_RETRY_DELAY_S = 60.0
    RETRY_MULTIPLIER = 2.0

    # Periodic refresh interval (safety net)
    PERIODIC_REFRESH_S = 60.0

    def __init__(
        self,
        registry: ModelRegistry,
        aggregator: HealthAggregator,
        capacity_tracker: RuntimeCapacityTracker,
        backend_client: Optional[BackendClientProtocol] = None,
        runtime_id: Optional[str] = None,
    ):
        """
        Initialize the capability publisher.

        Args:
            registry: Model registry for state queries
            aggregator: Health aggregator for derived health
            capacity_tracker: Runtime capacity tracker
            backend_client: Client for backend communication
            runtime_id: Unique identifier for this runtime instance
        """
        self.registry = registry
        self.aggregator = aggregator
        self.capacity_tracker = capacity_tracker
        self.backend_client = backend_client or NoOpBackendClient()
        self.runtime_id = runtime_id or str(uuid.uuid4())

        # State
        self._running = False
        self._publish_queue: queue.Queue[PublishRequest] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._periodic_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Retry state
        self._consecutive_failures = 0
        self._current_retry_delay = self.INITIAL_RETRY_DELAY_S

        # Last successful state (retained during outages)
        self._last_successful_report: Optional[FullCapabilityReport] = None
        self._last_successful_time: Optional[datetime] = None

        logger.info(
            "CapabilityPublisher initialized",
            extra={"runtime_id": self.runtime_id},
        )

    def start(self) -> None:
        """
        Start the publisher.

        Subscribes to registry events and starts background threads.
        """
        if self._running:
            logger.warning("Publisher already running")
            return

        self._running = True
        self._stop_event.clear()

        # Subscribe to registry events
        self.registry.add_listener(self._on_registry_event)

        # Start worker thread
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="CapabilityPublisher-Worker",
            daemon=True,
        )
        self._worker_thread.start()

        # Start periodic refresh thread
        self._periodic_thread = threading.Thread(
            target=self._periodic_loop,
            name="CapabilityPublisher-Periodic",
            daemon=True,
        )
        self._periodic_thread.start()

        # Trigger initial registration
        self._enqueue(PublishRequest(trigger=PublishTrigger.STARTUP))

        logger.info("CapabilityPublisher started")

    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the publisher gracefully.

        Args:
            timeout: Maximum time to wait for threads to stop
        """
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        # Unsubscribe from registry
        self.registry.remove_listener(self._on_registry_event)

        # Signal worker to stop
        self._publish_queue.put(None)  # type: ignore

        # Wait for threads
        if self._worker_thread:
            self._worker_thread.join(timeout=timeout)
        if self._periodic_thread:
            self._periodic_thread.join(timeout=timeout)

        logger.info("CapabilityPublisher stopped")

    def publish_now(self) -> bool:
        """
        Trigger an immediate capability publish.

        Returns True if publish was successful.
        """
        request = PublishRequest(trigger=PublishTrigger.MANUAL)
        return self._do_publish(request)

    def _enqueue(self, request: PublishRequest) -> None:
        """Enqueue a publish request."""
        try:
            self._publish_queue.put_nowait(request)
        except queue.Full:
            logger.warning(
                "Publish queue full, dropping request",
                extra={
                    "trigger": request.trigger.value,
                    "correlation_id": request.correlation_id,
                },
            )

    def _on_registry_event(self, event: RegistryEvent) -> None:
        """Handle registry events and trigger appropriate publishes."""
        if event.event_type == RegistryEventType.STATE_CHANGED:
            # Check if this is a state that affects advertising
            if event.new_state == LoadState.READY:
                self._enqueue(
                    PublishRequest(
                        trigger=PublishTrigger.MODEL_LOADED,
                        model_id=event.model_id,
                        version=event.version,
                    )
                )
            elif event.new_state in (
                LoadState.UNLOADED,
                LoadState.FAILED,
                LoadState.ERROR,
                LoadState.DISABLED,
            ):
                self._enqueue(
                    PublishRequest(
                        trigger=PublishTrigger.MODEL_UNLOADED,
                        model_id=event.model_id,
                        version=event.version,
                    )
                )

        elif event.event_type == RegistryEventType.HEALTH_CHANGED:
            # Health changes always trigger re-registration
            self._enqueue(
                PublishRequest(
                    trigger=PublishTrigger.HEALTH_CHANGED,
                    model_id=event.model_id,
                    version=event.version,
                )
            )

        elif event.event_type == RegistryEventType.VERSION_REMOVED:
            # Version removal triggers deregistration
            self._enqueue(
                PublishRequest(
                    trigger=PublishTrigger.MODEL_UNLOADED,
                    model_id=event.model_id,
                    version=event.version,
                )
            )

    def _worker_loop(self) -> None:
        """Worker thread that processes publish requests."""
        logger.debug("Worker loop started")

        while self._running:
            try:
                request = self._publish_queue.get(timeout=1.0)

                if request is None:
                    # Shutdown signal
                    break

                self._do_publish(request)

            except queue.Empty:
                continue
            except Exception as e:
                logger.exception(
                    "Error in worker loop",
                    extra={"error": str(e)},
                )

        logger.debug("Worker loop stopped")

    def _periodic_loop(self) -> None:
        """Periodic refresh thread (safety net)."""
        logger.debug("Periodic loop started")

        while not self._stop_event.wait(timeout=self.PERIODIC_REFRESH_S):
            if not self._running:
                break

            self._enqueue(PublishRequest(trigger=PublishTrigger.PERIODIC))

        logger.debug("Periodic loop stopped")

    def _do_publish(self, request: PublishRequest) -> bool:
        """
        Execute a publish request.

        Returns True if successful.
        """
        correlation_id = request.correlation_id

        logger.debug(
            "Publishing capabilities",
            extra={
                "trigger": request.trigger.value,
                "correlation_id": correlation_id,
                "model_id": request.model_id,
                "version": request.version,
            },
        )

        try:
            # Build the report
            report = self._build_report()

            # Attempt to publish
            success = self.backend_client.register_capabilities(
                report=report,
                correlation_id=correlation_id,
            )

            if success:
                self._on_publish_success(report)
                return True
            else:
                self._on_publish_failure(correlation_id, None)
                return False

        except Exception as e:
            self._on_publish_failure(correlation_id, e)
            return False

    def _build_report(self) -> FullCapabilityReport:
        """Build a complete capability report."""
        # Build model reports
        model_reports = []
        total_models = 0
        healthy_models = 0
        total_versions = 0
        ready_versions = 0

        for model in self.registry.get_all_models():
            model_report = self.aggregator.build_model_report(model.model_id)

            if model_report is not None:
                model_reports.append(model_report)
                total_models += 1

                if model_report.health == HealthStatus.HEALTHY:
                    healthy_models += 1

                ready_versions += len(model_report.versions)

            total_versions += len(model.versions)

        # Determine overall runtime health
        if healthy_models > 0:
            runtime_health = HealthStatus.HEALTHY
        elif model_reports:
            runtime_health = HealthStatus.DEGRADED
        else:
            runtime_health = HealthStatus.UNKNOWN

        # Get capacity report
        capacity_report = self.capacity_tracker.get_report()

        return FullCapabilityReport(
            runtime_id=self.runtime_id,
            timestamp=datetime.utcnow(),
            models=model_reports,
            capacity=capacity_report,
            runtime_health=runtime_health,
            total_models=total_models,
            healthy_models=healthy_models,
            total_versions=total_versions,
            ready_versions=ready_versions,
        )

    def _on_publish_success(self, report: FullCapabilityReport) -> None:
        """Handle successful publish."""
        self._consecutive_failures = 0
        self._current_retry_delay = self.INITIAL_RETRY_DELAY_S
        self._last_successful_report = report
        self._last_successful_time = datetime.utcnow()

        logger.info(
            "Capability publish successful",
            extra={
                "runtime_id": self.runtime_id,
                "model_count": report.total_models,
                "ready_versions": report.ready_versions,
            },
        )

    def _on_publish_failure(
        self,
        correlation_id: str,
        error: Optional[Exception],
    ) -> None:
        """Handle failed publish with exponential backoff."""
        self._consecutive_failures += 1

        # Calculate next retry delay
        self._current_retry_delay = min(
            self._current_retry_delay * self.RETRY_MULTIPLIER,
            self.MAX_RETRY_DELAY_S,
        )

        logger.warning(
            "Capability publish failed",
            extra={
                "correlation_id": correlation_id,
                "consecutive_failures": self._consecutive_failures,
                "next_retry_delay_s": self._current_retry_delay,
                "error": str(error) if error else "Unknown",
            },
        )

        # Schedule retry if still running
        if self._running and self._consecutive_failures < 10:
            threading.Timer(
                self._current_retry_delay,
                lambda: self._enqueue(
                    PublishRequest(
                        trigger=PublishTrigger.MANUAL,
                        correlation_id=correlation_id,
                    )
                ),
            ).start()

    @property
    def last_successful_time(self) -> Optional[datetime]:
        """Get timestamp of last successful publish."""
        return self._last_successful_time

    @property
    def consecutive_failures(self) -> int:
        """Get count of consecutive publish failures."""
        return self._consecutive_failures


# =============================================================================
# HEALTH REPORTER - Simplified interface for health updates
# =============================================================================


class HealthReporter:
    """
    Simplified interface for reporting health changes.

    This provides a convenient API for the sandbox/execution layer
    to report health changes without directly coupling to the publisher.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        publisher: Optional[CapabilityPublisher] = None,
    ):
        """
        Initialize health reporter.

        Args:
            registry: Model registry for state updates
            publisher: Optional publisher to notify of changes
        """
        self.registry = registry
        self.publisher = publisher

    def report_healthy(self, model_id: str, version: str) -> bool:
        """
        Report a version as healthy.

        Returns True if update was applied.
        """
        return self._update_health(model_id, version, HealthStatus.HEALTHY)

    def report_degraded(
        self,
        model_id: str,
        version: str,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Report a version as degraded.

        Args:
            model_id: Model identifier
            version: Version string
            reason: Optional reason for degradation

        Returns True if update was applied.
        """
        success = self._update_health(model_id, version, HealthStatus.DEGRADED)

        if success and reason:
            # Update last error to store reason
            descriptor = self.registry.get_version(model_id, version)
            if descriptor:
                descriptor.last_error = reason

        return success

    def report_unhealthy(
        self,
        model_id: str,
        version: str,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Report a version as unhealthy.

        This will cause the version to be removed from backend advertising.

        Returns True if update was applied.
        """
        success = self._update_health(model_id, version, HealthStatus.UNHEALTHY)

        if success and reason:
            descriptor = self.registry.get_version(model_id, version)
            if descriptor:
                descriptor.last_error = reason

        return success

    def _update_health(
        self,
        model_id: str,
        version: str,
        health: HealthStatus,
    ) -> bool:
        """
        Update health status in registry.

        The registry will emit an event that the publisher listens to.
        """
        return self.registry.update_health(model_id, version, health)


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================


def create_reporting_stack(
    registry: ModelRegistry,
    backend_client: Optional[BackendClientProtocol] = None,
    max_concurrent: int = 10,
    queue_capacity: int = 100,
    runtime_id: Optional[str] = None,
    concurrency_manager: Optional["ConcurrencyManager"] = None,
) -> tuple[CapabilityPublisher, HealthReporter, RuntimeCapacityTracker]:
    """
    Create a complete reporting stack.

    This is the recommended way to initialize reporting components.

    Args:
        registry: Model registry
        backend_client: Backend client (uses NoOp if not provided)
        max_concurrent: Maximum concurrent inferences (ignored if concurrency_manager provided)
        queue_capacity: Queue capacity for backpressure
        runtime_id: Optional runtime identifier
        concurrency_manager: Optional ConcurrencyManager for integrated slot tracking

    Returns:
        Tuple of (publisher, reporter, capacity_tracker)

    Example with ConcurrencyManager integration:
        from ai.runtime.concurrency import create_concurrency_stack

        # Create concurrency stack first
        manager, admission, scheduler = create_concurrency_stack(global_limit=10)

        # Create reporting stack with concurrency manager
        publisher, reporter, capacity = create_reporting_stack(
            registry=registry,
            concurrency_manager=manager,
        )

        # Now InferencePipeline can use admission controller,
        # and CapabilityPublisher reports consistent capacity info
    """
    aggregator = HealthAggregator(registry)
    capacity_tracker = RuntimeCapacityTracker(
        max_concurrent=max_concurrent,
        queue_capacity=queue_capacity,
        concurrency_manager=concurrency_manager,
    )

    publisher = CapabilityPublisher(
        registry=registry,
        aggregator=aggregator,
        capacity_tracker=capacity_tracker,
        backend_client=backend_client,
        runtime_id=runtime_id,
    )

    reporter = HealthReporter(
        registry=registry,
        publisher=publisher,
    )

    return publisher, reporter, capacity_tracker
