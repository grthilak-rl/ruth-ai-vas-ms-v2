"""
Ruth AI Runtime - Model Coordinator

This module provides atomic coordination between the Model Registry and
Sandbox Manager, ensuring that state transitions are consistent across
both components.

The coordinator solves the problem where registry and sandbox maintain
separate state with separate locks, which can lead to inconsistent state
during concurrent operations (e.g., a model in READY state but no sandbox,
or a sandbox existing for a non-READY model).

Design Principles:
- Single point of coordination for model lifecycle
- Atomic state transitions (registry + sandbox updated together)
- Consistent invariants (READY models always have sandboxes)
- Clean rollback on partial failures
- Thread-safe operations

Invariants maintained:
1. A model in READY state MUST have a corresponding sandbox
2. A sandbox MUST NOT exist for a non-READY model
3. State transitions and sandbox creation/destruction are atomic

Usage:
    coordinator = ModelCoordinator(registry, sandbox_manager, loader)

    # Activate a model (creates sandbox, updates state to READY)
    result = coordinator.activate_model(model_id, version, loaded_model, descriptor)

    # Deactivate a model (destroys sandbox, updates state)
    coordinator.deactivate_model(model_id, version, new_state, error, error_code)

    # Get a model ready for inference (returns sandbox if available)
    sandbox = coordinator.get_ready_sandbox(model_id, version)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from ai.runtime.loader import LoadedModel
from ai.runtime.models import (
    HealthStatus,
    LoadState,
    ModelVersionDescriptor,
)
from ai.runtime.registry import ModelRegistry
from ai.runtime.sandbox import ExecutionSandbox, SandboxManager

logger = logging.getLogger(__name__)


# =============================================================================
# COORDINATION RESULT TYPES
# =============================================================================


class CoordinationResultCode(Enum):
    """Result codes for coordination operations."""

    SUCCESS = "success"
    MODEL_NOT_FOUND = "model_not_found"
    VERSION_NOT_FOUND = "version_not_found"
    INVALID_STATE_TRANSITION = "invalid_state_transition"
    SANDBOX_CREATION_FAILED = "sandbox_creation_failed"
    SANDBOX_NOT_FOUND = "sandbox_not_found"
    ALREADY_ACTIVE = "already_active"
    ALREADY_INACTIVE = "already_inactive"
    LOCK_TIMEOUT = "lock_timeout"


@dataclass
class CoordinationResult:
    """Result of a coordination operation."""

    success: bool
    code: CoordinationResultCode
    message: str
    sandbox: Optional[ExecutionSandbox] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

    @classmethod
    def ok(
        cls,
        message: str = "Operation successful",
        sandbox: Optional[ExecutionSandbox] = None,
    ) -> "CoordinationResult":
        """Create a successful result."""
        return cls(
            success=True,
            code=CoordinationResultCode.SUCCESS,
            message=message,
            sandbox=sandbox,
        )

    @classmethod
    def fail(cls, code: CoordinationResultCode, message: str) -> "CoordinationResult":
        """Create a failed result."""
        return cls(
            success=False,
            code=code,
            message=message,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "success": self.success,
            "code": self.code.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


# =============================================================================
# MODEL COORDINATOR
# =============================================================================


class ModelCoordinator:
    """
    Coordinates atomic state transitions between Registry and Sandbox Manager.

    This class ensures that the invariants between registry state and sandbox
    existence are always maintained, even under concurrent access.

    Thread Safety:
    - Uses a single coordination lock for atomic operations
    - The lock is held during the entire activate/deactivate operation
    - Individual registry/sandbox operations still use their own locks
    - This provides a higher-level coordination layer

    Usage:
        coordinator = ModelCoordinator(registry, sandbox_manager)

        # Activate a loaded model
        result = coordinator.activate_model(
            model_id="fall_detection",
            version="1.0.0",
            loaded_model=loaded,
            descriptor=descriptor,
        )

        if result.success:
            sandbox = result.sandbox
            # Ready to run inference
    """

    def __init__(
        self,
        registry: ModelRegistry,
        sandbox_manager: SandboxManager,
        on_activation: Optional[Callable[[str, str], None]] = None,
        on_deactivation: Optional[Callable[[str, str], None]] = None,
        lock_timeout_seconds: float = 30.0,
    ):
        """
        Initialize the model coordinator.

        Args:
            registry: The model registry instance
            sandbox_manager: The sandbox manager instance
            on_activation: Optional callback when a model is activated
            on_deactivation: Optional callback when a model is deactivated
            lock_timeout_seconds: Maximum time to wait for coordination lock
        """
        self.registry = registry
        self.sandbox_manager = sandbox_manager
        self.on_activation = on_activation
        self.on_deactivation = on_deactivation
        self.lock_timeout_seconds = lock_timeout_seconds

        # Single coordination lock for atomic operations
        self._lock = threading.Lock()

        # Track coordinated models for debugging
        self._active_models: set[str] = set()  # Set of qualified_ids

    def activate_model(
        self,
        model_id: str,
        version: str,
        loaded_model: LoadedModel,
        descriptor: ModelVersionDescriptor,
    ) -> CoordinationResult:
        """
        Atomically activate a model (create sandbox + update state to READY).

        This operation ensures that either:
        - Both sandbox creation AND state update succeed (atomically)
        - Neither happens (rollback on failure)

        Args:
            model_id: Model identifier
            version: Model version
            loaded_model: The loaded model instance
            descriptor: Model version descriptor

        Returns:
            CoordinationResult with sandbox if successful
        """
        qualified_id = f"{model_id}:{version}"
        log_context = {"model_id": model_id, "version": version}

        logger.debug("Attempting to activate model", extra=log_context)

        # Acquire coordination lock with timeout
        acquired = self._lock.acquire(timeout=self.lock_timeout_seconds)
        if not acquired:
            logger.error("Failed to acquire coordination lock", extra=log_context)
            return CoordinationResult.fail(
                CoordinationResultCode.LOCK_TIMEOUT,
                f"Timed out waiting for coordination lock ({self.lock_timeout_seconds}s)",
            )

        try:
            # Check if already active
            if qualified_id in self._active_models:
                existing_sandbox = self.sandbox_manager.get_sandbox(model_id, version)
                if existing_sandbox:
                    logger.warning("Model already active", extra=log_context)
                    return CoordinationResult.fail(
                        CoordinationResultCode.ALREADY_ACTIVE,
                        f"Model {qualified_id} is already active",
                    )

            # Verify model exists in registry
            reg_descriptor = self.registry.get_version(model_id, version)
            if reg_descriptor is None:
                logger.error("Model version not found in registry", extra=log_context)
                return CoordinationResult.fail(
                    CoordinationResultCode.VERSION_NOT_FOUND,
                    f"Version {version} not found for model {model_id}",
                )

            # Step 1: Create sandbox first
            try:
                sandbox = self.sandbox_manager.create_sandbox(loaded_model, descriptor)
            except Exception as e:
                logger.error(
                    "Failed to create sandbox",
                    extra={**log_context, "error": str(e)},
                )
                return CoordinationResult.fail(
                    CoordinationResultCode.SANDBOX_CREATION_FAILED,
                    f"Failed to create sandbox: {e}",
                )

            # Step 2: Update registry state to READY
            try:
                success = self.registry.update_state(model_id, version, LoadState.READY)
                if not success:
                    # Rollback: Remove the sandbox we just created
                    logger.warning(
                        "State update failed, rolling back sandbox",
                        extra=log_context,
                    )
                    self.sandbox_manager.remove_sandbox(model_id, version)
                    return CoordinationResult.fail(
                        CoordinationResultCode.INVALID_STATE_TRANSITION,
                        "Failed to update model state to READY",
                    )
            except Exception as e:
                # Rollback: Remove the sandbox
                logger.error(
                    "State update raised exception, rolling back sandbox",
                    extra={**log_context, "error": str(e)},
                )
                self.sandbox_manager.remove_sandbox(model_id, version)
                raise

            # Both operations succeeded - mark as active
            self._active_models.add(qualified_id)

            logger.info(
                "Model activated successfully",
                extra={
                    **log_context,
                    "device": loaded_model.device,
                },
            )

            # Trigger callback outside lock
            if self.on_activation:
                try:
                    self.on_activation(model_id, version)
                except Exception as e:
                    logger.warning(
                        "Activation callback failed",
                        extra={**log_context, "error": str(e)},
                    )

            return CoordinationResult.ok(
                message=f"Model {qualified_id} activated",
                sandbox=sandbox,
            )

        finally:
            self._lock.release()

    def deactivate_model(
        self,
        model_id: str,
        version: str,
        new_state: LoadState = LoadState.UNLOADED,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> CoordinationResult:
        """
        Atomically deactivate a model (destroy sandbox + update state).

        This operation ensures that both sandbox destruction and state update
        happen atomically.

        Args:
            model_id: Model identifier
            version: Model version
            new_state: State to transition to (default: UNLOADED)
            error: Optional error message
            error_code: Optional error code

        Returns:
            CoordinationResult indicating success/failure
        """
        qualified_id = f"{model_id}:{version}"
        log_context = {
            "model_id": model_id,
            "version": version,
            "new_state": new_state.value,
        }

        logger.debug("Attempting to deactivate model", extra=log_context)

        # Acquire coordination lock with timeout
        acquired = self._lock.acquire(timeout=self.lock_timeout_seconds)
        if not acquired:
            logger.error("Failed to acquire coordination lock", extra=log_context)
            return CoordinationResult.fail(
                CoordinationResultCode.LOCK_TIMEOUT,
                f"Timed out waiting for coordination lock ({self.lock_timeout_seconds}s)",
            )

        try:
            # Check if model is tracked as active
            if qualified_id not in self._active_models:
                # Still try to clean up orphaned resources
                sandbox = self.sandbox_manager.get_sandbox(model_id, version)
                if sandbox is None:
                    logger.warning("Model already inactive", extra=log_context)
                    return CoordinationResult.fail(
                        CoordinationResultCode.ALREADY_INACTIVE,
                        f"Model {qualified_id} is already inactive",
                    )

            # Step 1: Remove sandbox
            sandbox_removed = self.sandbox_manager.remove_sandbox(model_id, version)
            if not sandbox_removed:
                logger.warning(
                    "Sandbox not found during deactivation",
                    extra=log_context,
                )
                # Continue anyway - sandbox might have been orphaned

            # Step 2: Update registry state
            state_updated = self.registry.update_state(
                model_id, version, new_state, error, error_code
            )
            if not state_updated:
                logger.warning(
                    "Failed to update state during deactivation",
                    extra=log_context,
                )
                # Continue anyway - we've already removed the sandbox

            # Mark as inactive
            self._active_models.discard(qualified_id)

            logger.info(
                "Model deactivated successfully",
                extra=log_context,
            )

            # Trigger callback
            if self.on_deactivation:
                try:
                    self.on_deactivation(model_id, version)
                except Exception as e:
                    logger.warning(
                        "Deactivation callback failed",
                        extra={**log_context, "error": str(e)},
                    )

            return CoordinationResult.ok(
                message=f"Model {qualified_id} deactivated",
            )

        finally:
            self._lock.release()

    def get_ready_sandbox(
        self,
        model_id: str,
        version: str,
    ) -> Optional[ExecutionSandbox]:
        """
        Get sandbox for a model only if it's in READY state.

        This method verifies both the registry state AND sandbox existence
        before returning the sandbox.

        Args:
            model_id: Model identifier
            version: Model version

        Returns:
            ExecutionSandbox if model is ready, None otherwise
        """
        qualified_id = f"{model_id}:{version}"

        # Quick check without full lock
        if qualified_id not in self._active_models:
            return None

        # Verify state is READY
        descriptor = self.registry.get_version(model_id, version)
        if descriptor is None or descriptor.state != LoadState.READY:
            return None

        # Get sandbox
        sandbox = self.sandbox_manager.get_sandbox(model_id, version)

        # Verify invariant (READY model should have sandbox)
        if sandbox is None:
            logger.error(
                "Invariant violation: READY model has no sandbox",
                extra={"model_id": model_id, "version": version},
            )
            # Attempt to fix by marking model as not active
            self._active_models.discard(qualified_id)

        return sandbox

    def is_active(self, model_id: str, version: str) -> bool:
        """
        Check if a model is currently active (READY with sandbox).

        Args:
            model_id: Model identifier
            version: Model version

        Returns:
            True if model is active
        """
        qualified_id = f"{model_id}:{version}"
        return qualified_id in self._active_models

    def get_active_models(self) -> list[str]:
        """
        Get list of active model qualified IDs.

        Returns:
            List of "model_id:version" strings
        """
        with self._lock:
            return list(self._active_models)

    def verify_invariants(self) -> dict[str, Any]:
        """
        Verify that all invariants are maintained.

        Checks:
        1. All active models have READY state
        2. All active models have sandboxes
        3. No sandboxes exist for non-active models

        Returns:
            Dictionary with verification results and any violations found
        """
        violations = []

        with self._lock:
            # Check active models
            for qualified_id in self._active_models:
                model_id, version = qualified_id.split(":", 1)

                # Check registry state
                descriptor = self.registry.get_version(model_id, version)
                if descriptor is None:
                    violations.append({
                        "type": "missing_descriptor",
                        "qualified_id": qualified_id,
                        "message": "Active model has no registry entry",
                    })
                elif descriptor.state != LoadState.READY:
                    violations.append({
                        "type": "wrong_state",
                        "qualified_id": qualified_id,
                        "expected": LoadState.READY.value,
                        "actual": descriptor.state.value,
                        "message": "Active model not in READY state",
                    })

                # Check sandbox existence
                sandbox = self.sandbox_manager.get_sandbox(model_id, version)
                if sandbox is None:
                    violations.append({
                        "type": "missing_sandbox",
                        "qualified_id": qualified_id,
                        "message": "Active model has no sandbox",
                    })

            # Check for orphaned sandboxes
            all_health = self.sandbox_manager.get_all_health()
            for sandbox_qid in all_health.keys():
                if sandbox_qid not in self._active_models:
                    violations.append({
                        "type": "orphaned_sandbox",
                        "qualified_id": sandbox_qid,
                        "message": "Sandbox exists for non-active model",
                    })

        return {
            "valid": len(violations) == 0,
            "active_count": len(self._active_models),
            "violations": violations,
        }

    def repair_invariants(self) -> dict[str, Any]:
        """
        Attempt to repair any invariant violations.

        This is a recovery mechanism for cases where the system
        got into an inconsistent state (e.g., after a crash).

        Returns:
            Dictionary with repair results
        """
        repaired = []
        failed = []

        with self._lock:
            # Check for missing sandboxes
            for qualified_id in list(self._active_models):
                model_id, version = qualified_id.split(":", 1)
                sandbox = self.sandbox_manager.get_sandbox(model_id, version)

                if sandbox is None:
                    # Remove from active set
                    self._active_models.discard(qualified_id)
                    # Update registry state
                    self.registry.update_state(
                        model_id,
                        version,
                        LoadState.FAILED,
                        error="Sandbox missing during invariant repair",
                    )
                    repaired.append({
                        "type": "removed_orphaned_active",
                        "qualified_id": qualified_id,
                    })

            # Check for orphaned sandboxes
            all_health = self.sandbox_manager.get_all_health()
            for sandbox_qid in list(all_health.keys()):
                if sandbox_qid not in self._active_models:
                    model_id, version = sandbox_qid.split(":", 1)
                    removed = self.sandbox_manager.remove_sandbox(model_id, version)
                    if removed:
                        repaired.append({
                            "type": "removed_orphaned_sandbox",
                            "qualified_id": sandbox_qid,
                        })
                    else:
                        failed.append({
                            "type": "failed_to_remove_sandbox",
                            "qualified_id": sandbox_qid,
                        })

        return {
            "repaired": repaired,
            "failed": failed,
            "success": len(failed) == 0,
        }

    def shutdown(self) -> None:
        """
        Shutdown the coordinator and deactivate all models.
        """
        logger.info(
            "Shutting down model coordinator",
            extra={"active_count": len(self._active_models)},
        )

        with self._lock:
            for qualified_id in list(self._active_models):
                model_id, version = qualified_id.split(":", 1)
                try:
                    self.sandbox_manager.remove_sandbox(model_id, version)
                    self.registry.update_state(model_id, version, LoadState.UNLOADED)
                except Exception as e:
                    logger.error(
                        "Error during shutdown",
                        extra={
                            "model_id": model_id,
                            "version": version,
                            "error": str(e),
                        },
                    )

            self._active_models.clear()

        logger.info("Model coordinator shutdown complete")
