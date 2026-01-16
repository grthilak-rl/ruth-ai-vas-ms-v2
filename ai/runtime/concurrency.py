"""
Ruth AI Runtime - Multi-Model Concurrency Support

This module provides concurrent inference handling across multiple models and
versions while preserving isolation, fairness, and predictability.

Design Principles:
- Isolation: A slow model cannot block others
- Fairness: Best-effort prevention of starvation (not strict guarantees)
- Predictability: Deterministic rejection behavior under overload
- Advisory: Backpressure is signaled, not enforced by backend

Concurrency Model:
- Global concurrency limit: Maximum total concurrent inferences
- Per-model limits: Maximum concurrent for each model (from model.yaml)
- Per-version limits: Optional more granular limits
- Rejection on overload: Explicit errors, never silent drops

Scheduling:
- FIFO within each model's queue
- Best-effort fairness across models (round-robin-ish)
- No strict global ordering guarantees
- No cross-model batching

Fairness Guarantees (DOCUMENTED):
- GUARANTEED: Per-model limits are enforced
- GUARANTEED: Rejection is deterministic and classified
- GUARANTEED: Models cannot monopolize global slots indefinitely
- NOT GUARANTEED: Strict round-robin across models
- NOT GUARANTEED: Latency fairness (some models slower than others)
- NOT GUARANTEED: Throughput fairness (higher limits = more slots)

Backpressure Levels:
- NONE: Normal operation, all slots available
- SOFT: Approaching capacity, may queue briefly
- HARD: At capacity, rejecting new requests

Health Interaction:
- Concurrency pressure does NOT directly degrade health
- Health only degrades from execution failures/timeouts
- Sustained overload may indirectly affect health via timeouts

Usage:
    from ai.runtime.concurrency import (
        ConcurrencyManager,
        AdmissionController,
        ConcurrencySlot,
    )

    # Initialize
    manager = ConcurrencyManager(global_limit=10)
    admission = AdmissionController(manager)

    # Register model limits
    manager.register_model("fall_detection", "1.0.0", max_concurrent=2)

    # Attempt inference
    slot = admission.try_acquire("fall_detection", "1.0.0", "req-123")
    if slot.acquired:
        try:
            # ... do inference ...
            pass
        finally:
            slot.release()
    else:
        # Handle rejection
        error = slot.rejection_error
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Generator, Optional

from ai.runtime.errors import (
    ErrorCode,
    PipelineError,
    pipeline_error,
)

logger = logging.getLogger(__name__)


# =============================================================================
# BACKPRESSURE LEVELS
# =============================================================================


class BackpressureLevel(Enum):
    """Runtime backpressure levels."""

    NONE = "none"  # Normal operation
    SOFT = "soft"  # Approaching capacity, may delay
    HARD = "hard"  # At capacity, rejecting


class RejectionReason(Enum):
    """Reasons for request rejection."""

    GLOBAL_LIMIT = "global_limit"  # Hit global concurrent limit
    MODEL_LIMIT = "model_limit"  # Hit per-model limit
    VERSION_LIMIT = "version_limit"  # Hit per-version limit
    BACKPRESSURE = "backpressure"  # Hard backpressure active
    QUEUE_FULL = "queue_full"  # Queue capacity exceeded
    MODEL_NOT_REGISTERED = "model_not_registered"  # Model unknown
    SHUTDOWN = "shutdown"  # Runtime shutting down


# =============================================================================
# CONCURRENCY SLOT - Represents an acquired execution slot
# =============================================================================


@dataclass
class ConcurrencySlot:
    """
    Represents an acquired concurrency slot.

    Usage:
        slot = admission.try_acquire(...)
        if slot.acquired:
            try:
                # do work
            finally:
                slot.release()
        else:
            handle_rejection(slot.rejection_error)
    """

    acquired: bool
    model_id: str
    version: str
    request_id: str

    # Set if acquired
    slot_id: Optional[str] = None
    acquired_at: Optional[datetime] = None

    # Set if rejected
    rejection_reason: Optional[RejectionReason] = None
    rejection_error: Optional[PipelineError] = None

    # Internal reference for release
    _manager: Optional["ConcurrencyManager"] = field(default=None, repr=False)
    _released: bool = field(default=False, repr=False)

    def release(self) -> None:
        """
        Release the slot back to the pool.

        Safe to call multiple times (idempotent).
        """
        if self._released or not self.acquired or self._manager is None:
            return

        self._manager._release_slot(
            model_id=self.model_id,
            version=self.version,
            slot_id=self.slot_id,
        )
        self._released = True

    def __enter__(self) -> "ConcurrencySlot":
        """Support context manager usage."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Release slot on context exit."""
        self.release()

    @classmethod
    def acquired_slot(
        cls,
        model_id: str,
        version: str,
        request_id: str,
        slot_id: str,
        manager: "ConcurrencyManager",
    ) -> "ConcurrencySlot":
        """Create an acquired slot."""
        return cls(
            acquired=True,
            model_id=model_id,
            version=version,
            request_id=request_id,
            slot_id=slot_id,
            acquired_at=datetime.utcnow(),
            _manager=manager,
        )

    @classmethod
    def rejected_slot(
        cls,
        model_id: str,
        version: str,
        request_id: str,
        reason: RejectionReason,
        error: PipelineError,
    ) -> "ConcurrencySlot":
        """Create a rejected slot."""
        return cls(
            acquired=False,
            model_id=model_id,
            version=version,
            request_id=request_id,
            rejection_reason=reason,
            rejection_error=error,
        )


# =============================================================================
# MODEL CONCURRENCY STATE - Per-model tracking
# =============================================================================


@dataclass
class ModelConcurrencyState:
    """
    Tracks concurrency state for a single model.

    Per-version limits are optional; defaults to model limit.
    """

    model_id: str
    max_concurrent: int  # Model-level limit
    version_limits: dict[str, int] = field(default_factory=dict)

    # Active slots
    active_count: int = 0
    active_by_version: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    active_slots: dict[str, datetime] = field(default_factory=dict)  # slot_id -> acquired_at

    # Metrics
    total_acquired: int = 0
    total_rejected: int = 0
    total_released: int = 0

    def get_version_limit(self, version: str) -> int:
        """Get limit for a specific version (falls back to model limit)."""
        return self.version_limits.get(version, self.max_concurrent)

    def can_acquire(self, version: str) -> tuple[bool, Optional[RejectionReason]]:
        """
        Check if a slot can be acquired for this version.

        Returns (can_acquire, rejection_reason).
        """
        # Check model limit
        if self.active_count >= self.max_concurrent:
            return False, RejectionReason.MODEL_LIMIT

        # Check version limit
        version_limit = self.get_version_limit(version)
        version_active = self.active_by_version.get(version, 0)
        if version_active >= version_limit:
            return False, RejectionReason.VERSION_LIMIT

        return True, None

    def acquire(self, version: str, slot_id: str) -> None:
        """Record slot acquisition."""
        self.active_count += 1
        self.active_by_version[version] = self.active_by_version.get(version, 0) + 1
        self.active_slots[slot_id] = datetime.utcnow()
        self.total_acquired += 1

    def release(self, version: str, slot_id: str) -> bool:
        """
        Record slot release.

        Returns True if slot was actually released.
        """
        if slot_id not in self.active_slots:
            return False

        del self.active_slots[slot_id]
        self.active_count = max(0, self.active_count - 1)
        if version in self.active_by_version:
            self.active_by_version[version] = max(
                0, self.active_by_version[version] - 1
            )
        self.total_released += 1
        return True

    def record_rejection(self) -> None:
        """Record a rejection."""
        self.total_rejected += 1

    @property
    def utilization(self) -> float:
        """Get current utilization (0.0 - 1.0)."""
        if self.max_concurrent == 0:
            return 1.0
        return self.active_count / self.max_concurrent


# =============================================================================
# CONCURRENCY MANAGER - Core slot management
# =============================================================================


class ConcurrencyManager:
    """
    Manages concurrency slots across all models.

    This is the core component that tracks:
    - Global slot utilization
    - Per-model slot utilization
    - Per-version slot utilization

    Design invariants:
    - Slot acquisition is atomic
    - Release is idempotent
    - No blocking operations
    - Deterministic rejection
    """

    # Backpressure thresholds (as fraction of global limit)
    SOFT_THRESHOLD = 0.7  # 70% global utilization
    HARD_THRESHOLD = 0.9  # 90% global utilization

    def __init__(
        self,
        global_limit: int = 10,
        default_model_limit: int = 1,
    ):
        """
        Initialize the concurrency manager.

        Args:
            global_limit: Maximum total concurrent inferences
            default_model_limit: Default per-model limit if not specified
        """
        self.global_limit = global_limit
        self.default_model_limit = default_model_limit

        # State
        self._models: dict[str, ModelConcurrencyState] = {}
        self._global_active = 0
        self._lock = threading.Lock()
        self._shutdown = False

        # Fairness tracking (last-served timestamp per model)
        self._last_served: dict[str, float] = {}

        # Metrics
        self._total_acquired = 0
        self._total_rejected = 0
        self._total_released = 0

        logger.info(
            "ConcurrencyManager initialized",
            extra={
                "global_limit": global_limit,
                "default_model_limit": default_model_limit,
            },
        )

    def register_model(
        self,
        model_id: str,
        version: str,
        max_concurrent: Optional[int] = None,
    ) -> None:
        """
        Register a model version for concurrency tracking.

        Args:
            model_id: Model identifier
            version: Version string
            max_concurrent: Per-model limit (uses default if None)
        """
        limit = max_concurrent if max_concurrent is not None else self.default_model_limit

        with self._lock:
            if model_id not in self._models:
                self._models[model_id] = ModelConcurrencyState(
                    model_id=model_id,
                    max_concurrent=limit,
                )
                logger.info(
                    "Model registered for concurrency",
                    extra={
                        "model_id": model_id,
                        "max_concurrent": limit,
                    },
                )
            else:
                # Update limit if provided
                if max_concurrent is not None:
                    self._models[model_id].max_concurrent = limit

            # Initialize last-served timestamp
            if model_id not in self._last_served:
                self._last_served[model_id] = 0.0

    def register_version_limit(
        self,
        model_id: str,
        version: str,
        max_concurrent: int,
    ) -> None:
        """
        Register a per-version concurrency limit.

        Args:
            model_id: Model identifier
            version: Version string
            max_concurrent: Per-version limit
        """
        with self._lock:
            if model_id not in self._models:
                self._models[model_id] = ModelConcurrencyState(
                    model_id=model_id,
                    max_concurrent=self.default_model_limit,
                )

            self._models[model_id].version_limits[version] = max_concurrent

            logger.debug(
                "Version limit registered",
                extra={
                    "model_id": model_id,
                    "version": version,
                    "max_concurrent": max_concurrent,
                },
            )

    def unregister_model(self, model_id: str) -> None:
        """
        Unregister a model from concurrency tracking.

        Active slots are NOT released - they will be released normally.
        """
        with self._lock:
            if model_id in self._models:
                state = self._models[model_id]

                # Warn if there are active slots
                if state.active_count > 0:
                    logger.warning(
                        "Unregistering model with active slots",
                        extra={
                            "model_id": model_id,
                            "active_count": state.active_count,
                        },
                    )

                # Adjust global count
                self._global_active = max(0, self._global_active - state.active_count)

                del self._models[model_id]
                self._last_served.pop(model_id, None)

                logger.info(
                    "Model unregistered from concurrency",
                    extra={"model_id": model_id},
                )

    def try_acquire(
        self,
        model_id: str,
        version: str,
        request_id: str,
    ) -> ConcurrencySlot:
        """
        Try to acquire a concurrency slot.

        This is a non-blocking operation. Returns immediately with
        either an acquired slot or a rejection.

        Args:
            model_id: Model identifier
            version: Version string
            request_id: Request identifier for tracing

        Returns:
            ConcurrencySlot (check .acquired to see if successful)
        """
        with self._lock:
            return self._try_acquire_locked(model_id, version, request_id)

    def _try_acquire_locked(
        self,
        model_id: str,
        version: str,
        request_id: str,
    ) -> ConcurrencySlot:
        """Internal acquire logic (must hold lock)."""
        # Check shutdown
        if self._shutdown:
            error = pipeline_error(
                code=ErrorCode.PIPE_CONCURRENCY_REJECTED,
                message="Runtime is shutting down",
                model_id=model_id,
                version=version,
                request_id=request_id,
                rejection_reason=RejectionReason.SHUTDOWN.value,
            )
            return ConcurrencySlot.rejected_slot(
                model_id=model_id,
                version=version,
                request_id=request_id,
                reason=RejectionReason.SHUTDOWN,
                error=error,
            )

        # Check model is registered
        if model_id not in self._models:
            # Auto-register with default limit
            self._models[model_id] = ModelConcurrencyState(
                model_id=model_id,
                max_concurrent=self.default_model_limit,
            )
            self._last_served[model_id] = 0.0

        state = self._models[model_id]

        # Check hard backpressure
        if self._is_hard_backpressure():
            state.record_rejection()
            self._total_rejected += 1

            error = pipeline_error(
                code=ErrorCode.PIPE_CONCURRENCY_REJECTED,
                message="Hard backpressure active, rejecting request",
                model_id=model_id,
                version=version,
                request_id=request_id,
                rejection_reason=RejectionReason.BACKPRESSURE.value,
                global_active=self._global_active,
                global_limit=self.global_limit,
            )
            return ConcurrencySlot.rejected_slot(
                model_id=model_id,
                version=version,
                request_id=request_id,
                reason=RejectionReason.BACKPRESSURE,
                error=error,
            )

        # Check global limit
        if self._global_active >= self.global_limit:
            state.record_rejection()
            self._total_rejected += 1

            error = pipeline_error(
                code=ErrorCode.PIPE_CONCURRENCY_REJECTED,
                message=f"Global concurrency limit reached ({self.global_limit})",
                model_id=model_id,
                version=version,
                request_id=request_id,
                rejection_reason=RejectionReason.GLOBAL_LIMIT.value,
                global_active=self._global_active,
                global_limit=self.global_limit,
            )
            return ConcurrencySlot.rejected_slot(
                model_id=model_id,
                version=version,
                request_id=request_id,
                reason=RejectionReason.GLOBAL_LIMIT,
                error=error,
            )

        # Check model/version limits
        can_acquire, reason = state.can_acquire(version)
        if not can_acquire:
            state.record_rejection()
            self._total_rejected += 1

            if reason == RejectionReason.MODEL_LIMIT:
                error = pipeline_error(
                    code=ErrorCode.PIPE_CONCURRENCY_REJECTED,
                    message=f"Model concurrency limit reached ({state.max_concurrent})",
                    model_id=model_id,
                    version=version,
                    request_id=request_id,
                    rejection_reason=reason.value,
                    model_active=state.active_count,
                    model_limit=state.max_concurrent,
                )
            else:  # VERSION_LIMIT
                version_limit = state.get_version_limit(version)
                version_active = state.active_by_version.get(version, 0)
                error = pipeline_error(
                    code=ErrorCode.PIPE_CONCURRENCY_REJECTED,
                    message=f"Version concurrency limit reached ({version_limit})",
                    model_id=model_id,
                    version=version,
                    request_id=request_id,
                    rejection_reason=reason.value,
                    version_active=version_active,
                    version_limit=version_limit,
                )

            return ConcurrencySlot.rejected_slot(
                model_id=model_id,
                version=version,
                request_id=request_id,
                reason=reason,
                error=error,
            )

        # Acquire slot
        slot_id = f"slot-{uuid.uuid4().hex[:12]}"
        state.acquire(version, slot_id)
        self._global_active += 1
        self._total_acquired += 1
        self._last_served[model_id] = time.monotonic()

        logger.debug(
            "Slot acquired",
            extra={
                "model_id": model_id,
                "version": version,
                "slot_id": slot_id,
                "request_id": request_id,
                "global_active": self._global_active,
                "model_active": state.active_count,
            },
        )

        return ConcurrencySlot.acquired_slot(
            model_id=model_id,
            version=version,
            request_id=request_id,
            slot_id=slot_id,
            manager=self,
        )

    def _release_slot(
        self,
        model_id: str,
        version: str,
        slot_id: Optional[str],
    ) -> None:
        """
        Release a concurrency slot (internal method).

        Called by ConcurrencySlot.release().
        """
        with self._lock:
            if model_id not in self._models:
                # Model was unregistered, just decrement global
                self._global_active = max(0, self._global_active - 1)
                self._total_released += 1
                return

            state = self._models[model_id]
            if state.release(version, slot_id):
                self._global_active = max(0, self._global_active - 1)
                self._total_released += 1

                logger.debug(
                    "Slot released",
                    extra={
                        "model_id": model_id,
                        "version": version,
                        "slot_id": slot_id,
                        "global_active": self._global_active,
                        "model_active": state.active_count,
                    },
                )

    def _is_hard_backpressure(self) -> bool:
        """Check if hard backpressure is active (must hold lock)."""
        if self.global_limit == 0:
            return True
        return (self._global_active / self.global_limit) >= self.HARD_THRESHOLD

    def _get_backpressure_level_locked(self) -> BackpressureLevel:
        """
        Get current backpressure level (must hold lock).

        Internal method for use within locked contexts.
        """
        if self.global_limit == 0:
            return BackpressureLevel.HARD

        utilization = self._global_active / self.global_limit

        if utilization >= self.HARD_THRESHOLD:
            return BackpressureLevel.HARD
        if utilization >= self.SOFT_THRESHOLD:
            return BackpressureLevel.SOFT
        return BackpressureLevel.NONE

    def get_backpressure_level(self) -> BackpressureLevel:
        """
        Get current backpressure level.

        This is advisory information for backends.
        """
        with self._lock:
            return self._get_backpressure_level_locked()

    def get_model_stats(self, model_id: str) -> Optional[dict[str, Any]]:
        """Get statistics for a specific model."""
        with self._lock:
            if model_id not in self._models:
                return None

            state = self._models[model_id]
            return {
                "model_id": model_id,
                "max_concurrent": state.max_concurrent,
                "active_count": state.active_count,
                "active_by_version": dict(state.active_by_version),
                "utilization": state.utilization,
                "total_acquired": state.total_acquired,
                "total_rejected": state.total_rejected,
                "total_released": state.total_released,
            }

    def get_global_stats(self) -> dict[str, Any]:
        """Get global concurrency statistics."""
        with self._lock:
            return {
                "global_limit": self.global_limit,
                "global_active": self._global_active,
                "available_slots": max(0, self.global_limit - self._global_active),
                "utilization": (
                    self._global_active / self.global_limit
                    if self.global_limit > 0
                    else 1.0
                ),
                "backpressure": self._get_backpressure_level_locked().value,
                "registered_models": len(self._models),
                "total_acquired": self._total_acquired,
                "total_rejected": self._total_rejected,
                "total_released": self._total_released,
            }

    def shutdown(self) -> None:
        """
        Begin shutdown - reject all new requests.

        Active slots will be released normally.
        """
        with self._lock:
            self._shutdown = True
            logger.info(
                "ConcurrencyManager shutdown initiated",
                extra={
                    "active_slots": self._global_active,
                },
            )


# =============================================================================
# ADMISSION CONTROLLER - High-level admission interface
# =============================================================================


class AdmissionController:
    """
    High-level admission control for inference requests.

    This wraps ConcurrencyManager with a simpler interface
    and provides convenience methods.

    Usage:
        controller = AdmissionController(manager)

        # Simple try-acquire pattern
        slot = controller.try_acquire(model_id, version, request_id)
        if slot.acquired:
            try:
                result = execute_inference()
            finally:
                slot.release()
        else:
            return error_response(slot.rejection_error)

        # Context manager pattern
        with controller.slot_context(model_id, version, request_id) as slot:
            if slot.acquired:
                result = execute_inference()
            else:
                return error_response(slot.rejection_error)
    """

    def __init__(self, manager: ConcurrencyManager):
        """
        Initialize admission controller.

        Args:
            manager: Underlying concurrency manager
        """
        self.manager = manager

    def try_acquire(
        self,
        model_id: str,
        version: str,
        request_id: str,
    ) -> ConcurrencySlot:
        """
        Try to acquire a concurrency slot.

        Returns immediately with acquired or rejected slot.
        """
        return self.manager.try_acquire(model_id, version, request_id)

    @contextmanager
    def slot_context(
        self,
        model_id: str,
        version: str,
        request_id: str,
    ) -> Generator[ConcurrencySlot, None, None]:
        """
        Context manager for slot acquisition.

        Automatically releases slot on exit.

        Usage:
            with controller.slot_context(...) as slot:
                if slot.acquired:
                    # do work
        """
        slot = self.try_acquire(model_id, version, request_id)
        try:
            yield slot
        finally:
            slot.release()

    def can_accept(self, model_id: str, version: str) -> bool:
        """
        Quick check if a request would likely be accepted.

        NOTE: This is a hint only - actual acquisition may still fail
        due to race conditions. Always handle rejection.
        """
        stats = self.manager.get_model_stats(model_id)
        if stats is None:
            # Model not registered, will auto-register
            global_stats = self.manager.get_global_stats()
            return global_stats["available_slots"] > 0

        # Check if model has capacity
        if stats["active_count"] >= stats["max_concurrent"]:
            return False

        # Check global capacity
        global_stats = self.manager.get_global_stats()
        return global_stats["available_slots"] > 0

    def get_rejection_wait_hint_ms(
        self,
        model_id: str,
        version: str,
    ) -> Optional[int]:
        """
        Get a hint for how long to wait before retrying.

        Returns None if no meaningful hint is available.

        NOTE: This is advisory only. Actual wait may vary.
        """
        stats = self.manager.get_model_stats(model_id)
        if stats is None:
            return None

        # Simple heuristic: suggest waiting based on typical inference time
        # This is a rough estimate - actual time varies by model
        if stats["utilization"] >= 1.0:
            return 100  # Model at capacity, suggest short wait
        elif stats["utilization"] >= 0.8:
            return 50

        return None


# =============================================================================
# FAIR SCHEDULER - Best-effort fairness across models
# =============================================================================


class FairScheduler:
    """
    Provides best-effort fairness hints for request scheduling.

    This does NOT enforce fairness - it provides advisory information
    that callers may use to make scheduling decisions.

    Fairness Strategy:
    - Track when each model was last served
    - Prefer models that haven't been served recently
    - Prevent any model from monopolizing resources indefinitely

    NOTE: This is not a strict scheduler. It provides hints only.
    Actual execution order depends on request arrival and availability.
    """

    # If a model hasn't been served in this many seconds,
    # it gets priority in suggestions
    STARVATION_THRESHOLD_S = 1.0

    def __init__(self, manager: ConcurrencyManager):
        """
        Initialize fair scheduler.

        Args:
            manager: Concurrency manager for state access
        """
        self.manager = manager

    def suggest_next_model(
        self,
        candidates: list[str],
    ) -> Optional[str]:
        """
        Suggest which model should be served next.

        Args:
            candidates: List of model_ids with pending requests

        Returns:
            Suggested model_id, or None if no valid suggestion
        """
        if not candidates:
            return None

        # Get current time
        now = time.monotonic()

        # Find model that has been waiting longest
        best_model = None
        best_wait = -1.0

        for model_id in candidates:
            stats = self.manager.get_model_stats(model_id)
            if stats is None:
                continue

            # Skip if model is at capacity
            if stats["active_count"] >= stats["max_concurrent"]:
                continue

            # Get time since last served
            last_served = self.manager._last_served.get(model_id, 0.0)
            wait_time = now - last_served

            if wait_time > best_wait:
                best_wait = wait_time
                best_model = model_id

        return best_model

    def is_starved(self, model_id: str) -> bool:
        """
        Check if a model appears to be starved.

        A model is considered starved if it hasn't been served
        for longer than the starvation threshold.
        """
        last_served = self.manager._last_served.get(model_id)
        if last_served is None:
            return True  # Never served

        wait_time = time.monotonic() - last_served
        return wait_time > self.STARVATION_THRESHOLD_S

    def get_fairness_report(self) -> dict[str, Any]:
        """
        Get a report on fairness metrics.

        Useful for debugging and monitoring.
        """
        now = time.monotonic()
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "models": {},
            "starved_models": [],
        }

        with self.manager._lock:
            for model_id, last_served in self.manager._last_served.items():
                wait_time = now - last_served
                stats = self.manager.get_model_stats(model_id)

                report["models"][model_id] = {
                    "last_served_ago_s": round(wait_time, 3),
                    "is_starved": wait_time > self.STARVATION_THRESHOLD_S,
                    "utilization": stats["utilization"] if stats else None,
                }

                if wait_time > self.STARVATION_THRESHOLD_S:
                    report["starved_models"].append(model_id)

        return report


# =============================================================================
# ERROR CODE ADDITION
# =============================================================================

# Note: The error code PIPE_CONCURRENCY_REJECTED needs to be added to errors.py
# This will be done as part of the integration step.


# =============================================================================
# INTEGRATION HELPERS
# =============================================================================


def create_concurrency_stack(
    global_limit: int = 10,
    default_model_limit: int = 1,
) -> tuple[ConcurrencyManager, AdmissionController, FairScheduler]:
    """
    Create a complete concurrency management stack.

    This is the recommended way to initialize concurrency components.

    Args:
        global_limit: Maximum total concurrent inferences
        default_model_limit: Default per-model limit

    Returns:
        Tuple of (manager, controller, scheduler)
    """
    manager = ConcurrencyManager(
        global_limit=global_limit,
        default_model_limit=default_model_limit,
    )
    controller = AdmissionController(manager)
    scheduler = FairScheduler(manager)

    return manager, controller, scheduler
