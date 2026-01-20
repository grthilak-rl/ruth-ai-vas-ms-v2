"""
Ruth AI Runtime - Failure Isolation and Recovery

This module implements failure isolation and recovery mechanisms to prevent
cascading failures, ensure safe runtime continuation, and allow controlled
recovery of failed models.

Design Principles:
- Version-level isolation: Each model version has independent failure state
- Deterministic disablement: Clear criteria, no probabilistic decisions
- Reversible: All disablements can be reversed with explicit re-enable
- Health authority preservation: Builds on top of sandbox health, doesn't replace it
- Concurrency ≠ health: Circuit breaker state is orthogonal to concurrency pressure

Key Components:
- CircuitBreaker: Tracks failure patterns per model version
- RecoveryManager: Coordinates disablement/re-enable with safety checks
- FailurePolicy: Configurable thresholds and cooldowns

Usage:
    from ai.runtime.recovery import (
        CircuitBreaker,
        RecoveryManager,
        FailurePolicy,
        create_recovery_stack,
    )

    # Create with defaults
    recovery_stack = create_recovery_stack(
        registry=registry,
        lifecycle_manager=lifecycle_manager,
    )
    circuit_breaker = recovery_stack["circuit_breaker"]
    recovery_manager = recovery_stack["recovery_manager"]

    # Wire up sandbox health changes
    def on_health_change(model_id, version, old_health, new_health):
        if new_health == HealthStatus.UNHEALTHY:
            circuit_breaker.record_unhealthy_transition(model_id, version)

    # Check if model should be disabled
    if circuit_breaker.should_disable(model_id, version):
        recovery_manager.disable_model(model_id, version, "Recovery threshold exceeded")
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from ai.runtime.models import HealthStatus, LoadState

logger = logging.getLogger(__name__)


# =============================================================================
# PERSISTENCE - File-based circuit breaker state storage
# =============================================================================


class CircuitBreakerPersistence:
    """
    File-based persistence for circuit breaker state.

    Survives container restarts by saving state to a JSON file.
    State is loaded on startup and saved on significant changes.

    The persistence file location can be configured via environment
    variable CIRCUIT_BREAKER_STATE_FILE, defaulting to /app/data/circuit_breaker_state.json.

    Thread-safe: uses a lock for file operations.
    """

    DEFAULT_STATE_FILE = "/app/data/circuit_breaker_state.json"

    def __init__(self, state_file: Optional[str] = None):
        """
        Initialize persistence manager.

        Args:
            state_file: Path to state file (default: from env or DEFAULT_STATE_FILE)
        """
        self._state_file = Path(
            state_file
            or os.environ.get("CIRCUIT_BREAKER_STATE_FILE", self.DEFAULT_STATE_FILE)
        )
        self._lock = threading.Lock()

        # Ensure parent directory exists
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

    def save_state(self, states: dict[str, "CircuitBreakerState"]) -> bool:
        """
        Save circuit breaker states to file.

        Args:
            states: Dictionary of qualified_id -> CircuitBreakerState

        Returns:
            True if save succeeded
        """
        with self._lock:
            try:
                serialized = {}
                for qid, state in states.items():
                    serialized[qid] = {
                        "model_id": state.model_id,
                        "version": state.version,
                        "state": state.state.value,
                        "unhealthy_transitions": state.unhealthy_transitions,
                        "consecutive_timeouts": state.consecutive_timeouts,
                        "recovery_attempts": state.recovery_attempts,
                        "disabled_at": state.disabled_at,
                        "disabled_reason": state.disabled_reason.value if state.disabled_reason else None,
                        "saved_at": datetime.now(timezone.utc).isoformat(),
                    }

                # Write atomically using temp file
                temp_file = self._state_file.with_suffix(".tmp")
                with open(temp_file, "w") as f:
                    json.dump(serialized, f, indent=2)

                # Atomic rename
                temp_file.replace(self._state_file)

                logger.debug(
                    f"Circuit breaker state saved to {self._state_file}",
                    extra={"state_count": len(states)},
                )
                return True

            except Exception as e:
                logger.warning(
                    f"Failed to save circuit breaker state: {e}",
                    extra={"state_file": str(self._state_file)},
                )
                return False

    def load_state(self) -> dict[str, dict[str, Any]]:
        """
        Load circuit breaker states from file.

        Returns:
            Dictionary of qualified_id -> serialized state dict
        """
        with self._lock:
            try:
                if not self._state_file.exists():
                    logger.debug("No circuit breaker state file found, starting fresh")
                    return {}

                with open(self._state_file, "r") as f:
                    data = json.load(f)

                logger.info(
                    f"Loaded circuit breaker state from {self._state_file}",
                    extra={"state_count": len(data)},
                )
                return data

            except Exception as e:
                logger.warning(
                    f"Failed to load circuit breaker state: {e}",
                    extra={"state_file": str(self._state_file)},
                )
                return {}

    def clear_state(self) -> bool:
        """
        Clear persisted state (delete file).

        Returns:
            True if cleared successfully
        """
        with self._lock:
            try:
                if self._state_file.exists():
                    self._state_file.unlink()
                    logger.info(f"Circuit breaker state file cleared: {self._state_file}")
                return True
            except Exception as e:
                logger.warning(f"Failed to clear circuit breaker state file: {e}")
                return False


# =============================================================================
# ENUMS - Circuit breaker states and failure types
# =============================================================================


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, failures tracked
    OPEN = "open"  # Tripped, model should be disabled
    HALF_OPEN = "half_open"  # Testing recovery, limited traffic


class FailureType(Enum):
    """Types of failures tracked by circuit breaker."""

    EXECUTION_ERROR = "execution_error"
    TIMEOUT = "timeout"
    HEALTH_DEGRADATION = "health_degradation"
    UNHEALTHY_TRANSITION = "unhealthy_transition"


class DisablementReason(Enum):
    """Reasons for disabling a model."""

    REPEATED_FAILURES = "repeated_failures"
    SUSTAINED_UNHEALTHY = "sustained_unhealthy"
    COOLDOWN_EXHAUSTED = "cooldown_exhausted"
    MANUAL_DISABLE = "manual_disable"
    RESOURCE_EXHAUSTION = "resource_exhaustion"


# =============================================================================
# DATA CLASSES - Configuration and state tracking
# =============================================================================


@dataclass
class FailurePolicy:
    """
    Configuration for failure isolation thresholds and cooldowns.

    All time values are in seconds.
    """

    # Failure thresholds
    failure_threshold: int = 10  # Failures before circuit opens
    unhealthy_threshold: int = 3  # UNHEALTHY transitions before disable
    timeout_threshold: int = 5  # Consecutive timeouts before disable

    # Time windows
    failure_window_seconds: int = 60  # Window for counting failures
    cooldown_seconds: int = 300  # Cooldown before auto-recovery attempt
    min_recovery_interval_seconds: int = 60  # Min time between recovery attempts

    # Recovery settings
    max_recovery_attempts: int = 3  # Max recovery attempts before permanent disable
    half_open_success_threshold: int = 3  # Successes needed to close circuit
    half_open_timeout_seconds: int = 30  # Time to allow half-open testing

    @classmethod
    def strict(cls) -> "FailurePolicy":
        """Strict policy - quick disablement, long cooldown."""
        return cls(
            failure_threshold=5,
            unhealthy_threshold=2,
            timeout_threshold=3,
            failure_window_seconds=30,
            cooldown_seconds=600,
            max_recovery_attempts=2,
        )

    @classmethod
    def permissive(cls) -> "FailurePolicy":
        """Permissive policy - more tolerance, faster recovery."""
        return cls(
            failure_threshold=20,
            unhealthy_threshold=5,
            timeout_threshold=10,
            failure_window_seconds=120,
            cooldown_seconds=120,
            max_recovery_attempts=5,
        )


@dataclass
class FailureRecord:
    """Record of a single failure event."""

    failure_type: FailureType
    timestamp: float  # time.monotonic() value
    error_code: Optional[str] = None
    message: Optional[str] = None


@dataclass
class CircuitBreakerState:
    """
    State tracking for a single model version's circuit breaker.

    Thread-safe access must be ensured by the CircuitBreaker class.
    """

    model_id: str
    version: str
    state: CircuitState = CircuitState.CLOSED

    # Failure tracking
    failures: list[FailureRecord] = field(default_factory=list)
    unhealthy_transitions: int = 0
    consecutive_timeouts: int = 0

    # Recovery tracking
    recovery_attempts: int = 0
    last_recovery_attempt: Optional[float] = None
    disabled_at: Optional[float] = None
    disabled_reason: Optional[DisablementReason] = None

    # Half-open state tracking
    half_open_started: Optional[float] = None
    half_open_successes: int = 0

    def record_failure(self, record: FailureRecord, window_seconds: int) -> None:
        """Record a failure and prune old entries."""
        self.failures.append(record)
        self._prune_old_failures(window_seconds)

        if record.failure_type == FailureType.TIMEOUT:
            self.consecutive_timeouts += 1
        else:
            self.consecutive_timeouts = 0

        if record.failure_type == FailureType.UNHEALTHY_TRANSITION:
            self.unhealthy_transitions += 1

    def record_success(self) -> None:
        """Record a successful execution."""
        self.consecutive_timeouts = 0

        if self.state == CircuitState.HALF_OPEN:
            self.half_open_successes += 1

    def _prune_old_failures(self, window_seconds: int) -> None:
        """Remove failures outside the tracking window."""
        cutoff = time.monotonic() - window_seconds
        self.failures = [f for f in self.failures if f.timestamp > cutoff]

    def reset_for_recovery(self) -> None:
        """Reset state for a recovery attempt."""
        self.state = CircuitState.HALF_OPEN
        self.half_open_started = time.monotonic()
        self.half_open_successes = 0
        self.recovery_attempts += 1
        self.last_recovery_attempt = time.monotonic()

    def close_circuit(self) -> None:
        """Close the circuit after successful recovery."""
        self.state = CircuitState.CLOSED
        self.failures.clear()
        self.unhealthy_transitions = 0
        self.consecutive_timeouts = 0
        self.half_open_started = None
        self.half_open_successes = 0
        self.disabled_at = None
        self.disabled_reason = None
        # Note: recovery_attempts is NOT reset - tracks lifetime attempts

    def open_circuit(self, reason: DisablementReason) -> None:
        """Open the circuit and mark for disablement."""
        self.state = CircuitState.OPEN
        self.disabled_at = time.monotonic()
        self.disabled_reason = reason

    @property
    def failure_count(self) -> int:
        """Get current failure count within window."""
        return len(self.failures)

    @property
    def qualified_id(self) -> str:
        """Get qualified model:version identifier."""
        return f"{self.model_id}:{self.version}"


@dataclass
class RecoveryResult:
    """Result of a recovery operation."""

    success: bool
    model_id: str
    version: str
    message: str
    previous_state: Optional[LoadState] = None
    new_state: Optional[LoadState] = None
    recovery_attempts: int = 0


# =============================================================================
# CIRCUIT BREAKER - Tracks failure patterns and decides when to disable
# =============================================================================


class CircuitBreaker:
    """
    Circuit breaker implementation for model failure isolation.

    Tracks failure patterns per model version and determines when
    a model should be disabled based on configurable thresholds.

    The circuit breaker operates independently of the health system -
    it observes health transitions but doesn't drive them directly.

    Usage:
        breaker = CircuitBreaker(policy=FailurePolicy())

        # Record failures
        breaker.record_failure(model_id, version, FailureType.EXECUTION_ERROR)

        # Check if should disable
        if breaker.should_disable(model_id, version):
            # Trigger disablement through RecoveryManager
            pass

        # Record health transitions (from sandbox callback)
        breaker.record_unhealthy_transition(model_id, version)
    """

    # Type alias for disable callback
    # Signature: (model_id, version, reason) -> None
    DisableCallback = Callable[[str, str, DisablementReason], None]

    def __init__(
        self,
        policy: Optional[FailurePolicy] = None,
        on_should_disable: Optional[DisableCallback] = None,
        persistence: Optional[CircuitBreakerPersistence] = None,
        enable_persistence: bool = True,
    ):
        """
        Initialize the circuit breaker.

        Args:
            policy: Failure policy configuration
            on_should_disable: Callback when a model should be disabled
            persistence: Optional persistence manager (auto-created if enable_persistence=True)
            enable_persistence: Whether to enable file-based persistence
        """
        self.policy = policy or FailurePolicy()
        self._states: dict[str, CircuitBreakerState] = {}
        self._lock = threading.Lock()
        self._on_should_disable = on_should_disable

        # Setup persistence
        self._persistence = persistence
        if enable_persistence and persistence is None:
            self._persistence = CircuitBreakerPersistence()

        # Load persisted state on startup
        if self._persistence:
            self._load_persisted_state()

    def set_disable_callback(self, callback: Optional[DisableCallback]) -> None:
        """Set or update the disable callback."""
        self._on_should_disable = callback

    def _load_persisted_state(self) -> None:
        """Load persisted state from file on startup."""
        if not self._persistence:
            return

        saved_states = self._persistence.load_state()

        with self._lock:
            for qid, saved in saved_states.items():
                try:
                    state = CircuitBreakerState(
                        model_id=saved["model_id"],
                        version=saved["version"],
                    )
                    state.state = CircuitState(saved["state"])
                    state.unhealthy_transitions = saved.get("unhealthy_transitions", 0)
                    state.consecutive_timeouts = saved.get("consecutive_timeouts", 0)
                    state.recovery_attempts = saved.get("recovery_attempts", 0)
                    state.disabled_at = saved.get("disabled_at")
                    if saved.get("disabled_reason"):
                        state.disabled_reason = DisablementReason(saved["disabled_reason"])

                    self._states[qid] = state

                    logger.info(
                        "Restored circuit breaker state",
                        extra={
                            "model_id": state.model_id,
                            "version": state.version,
                            "state": state.state.value,
                            "recovery_attempts": state.recovery_attempts,
                        },
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to restore circuit breaker state for {qid}: {e}"
                    )

    def _persist_state(self) -> None:
        """Persist current state to file (called on significant changes)."""
        if not self._persistence:
            return

        # Get states under lock
        with self._lock:
            states_copy = dict(self._states)

        # Save outside lock to avoid blocking
        self._persistence.save_state(states_copy)

    def _get_or_create_state(
        self,
        model_id: str,
        version: str,
    ) -> CircuitBreakerState:
        """Get or create circuit breaker state for a model version."""
        qualified_id = f"{model_id}:{version}"

        if qualified_id not in self._states:
            self._states[qualified_id] = CircuitBreakerState(
                model_id=model_id,
                version=version,
            )

        return self._states[qualified_id]

    def get_state(self, model_id: str, version: str) -> Optional[CircuitBreakerState]:
        """Get circuit breaker state for a model version."""
        qualified_id = f"{model_id}:{version}"

        with self._lock:
            return self._states.get(qualified_id)

    def record_failure(
        self,
        model_id: str,
        version: str,
        failure_type: FailureType,
        error_code: Optional[str] = None,
        message: Optional[str] = None,
    ) -> bool:
        """
        Record a failure event for a model version.

        Args:
            model_id: Model identifier
            version: Model version
            failure_type: Type of failure
            error_code: Optional error code
            message: Optional error message

        Returns:
            True if model should now be disabled
        """
        should_disable = False
        disable_reason = None

        with self._lock:
            state = self._get_or_create_state(model_id, version)

            # Don't record failures if already open
            if state.state == CircuitState.OPEN:
                return False

            record = FailureRecord(
                failure_type=failure_type,
                timestamp=time.monotonic(),
                error_code=error_code,
                message=message,
            )
            state.record_failure(record, self.policy.failure_window_seconds)

            # Check disablement criteria
            should_disable, disable_reason = self._check_disable_criteria(state)

            if should_disable:
                state.open_circuit(disable_reason)
                # Persist state change
                self._persist_state()

        # Log the failure
        logger.debug(
            "Circuit breaker recorded failure",
            extra={
                "model_id": model_id,
                "version": version,
                "failure_type": failure_type.value,
                "failure_count": state.failure_count,
                "should_disable": should_disable,
            },
        )

        # Trigger callback outside lock
        if should_disable and self._on_should_disable:
            try:
                self._on_should_disable(model_id, version, disable_reason)
            except Exception as e:
                logger.warning(
                    "Disable callback failed",
                    extra={
                        "model_id": model_id,
                        "version": version,
                        "error": str(e),
                    },
                )

        return should_disable

    def record_unhealthy_transition(self, model_id: str, version: str) -> bool:
        """
        Record a transition to UNHEALTHY health status.

        This is called by the sandbox health change callback when
        a model transitions to UNHEALTHY.

        Returns:
            True if model should now be disabled
        """
        return self.record_failure(
            model_id,
            version,
            FailureType.UNHEALTHY_TRANSITION,
            message="Model transitioned to UNHEALTHY",
        )

    def record_success(self, model_id: str, version: str) -> bool:
        """
        Record a successful execution.

        Returns:
            True if circuit should now close (recovery complete)
        """
        should_close = False

        with self._lock:
            state = self._get_or_create_state(model_id, version)
            state.record_success()

            # Check if half-open circuit should close
            if state.state == CircuitState.HALF_OPEN:
                if state.half_open_successes >= self.policy.half_open_success_threshold:
                    state.close_circuit()
                    should_close = True
                    # Persist state change
                    self._persist_state()

        if should_close:
            logger.info(
                "Circuit breaker closed after recovery",
                extra={
                    "model_id": model_id,
                    "version": version,
                    "recovery_attempts": state.recovery_attempts,
                },
            )

        return should_close

    def _check_disable_criteria(
        self,
        state: CircuitBreakerState,
    ) -> tuple[bool, Optional[DisablementReason]]:
        """
        Check if a model should be disabled based on current state.

        Returns:
            Tuple of (should_disable, reason)
        """
        # Check failure count threshold
        if state.failure_count >= self.policy.failure_threshold:
            return True, DisablementReason.REPEATED_FAILURES

        # Check unhealthy transition threshold
        if state.unhealthy_transitions >= self.policy.unhealthy_threshold:
            return True, DisablementReason.SUSTAINED_UNHEALTHY

        # Check consecutive timeout threshold
        if state.consecutive_timeouts >= self.policy.timeout_threshold:
            return True, DisablementReason.REPEATED_FAILURES

        # Check if max recovery attempts exceeded
        if state.recovery_attempts >= self.policy.max_recovery_attempts:
            return True, DisablementReason.COOLDOWN_EXHAUSTED

        return False, None

    def should_disable(self, model_id: str, version: str) -> bool:
        """
        Check if a model should be disabled.

        Args:
            model_id: Model identifier
            version: Model version

        Returns:
            True if model should be disabled
        """
        with self._lock:
            state = self._states.get(f"{model_id}:{version}")
            if state is None:
                return False

            return state.state == CircuitState.OPEN

    def is_circuit_open(self, model_id: str, version: str) -> bool:
        """Check if circuit is open (model disabled/should be disabled)."""
        return self.should_disable(model_id, version)

    def is_circuit_half_open(self, model_id: str, version: str) -> bool:
        """Check if circuit is half-open (testing recovery)."""
        with self._lock:
            state = self._states.get(f"{model_id}:{version}")
            if state is None:
                return False

            return state.state == CircuitState.HALF_OPEN

    def can_attempt_recovery(self, model_id: str, version: str) -> bool:
        """
        Check if a recovery attempt is allowed.

        Returns:
            True if recovery can be attempted
        """
        with self._lock:
            state = self._states.get(f"{model_id}:{version}")
            if state is None:
                return False

            # Must be in OPEN state
            if state.state != CircuitState.OPEN:
                return False

            # Check max recovery attempts
            if state.recovery_attempts >= self.policy.max_recovery_attempts:
                return False

            # Check minimum recovery interval
            if state.last_recovery_attempt is not None:
                elapsed = time.monotonic() - state.last_recovery_attempt
                if elapsed < self.policy.min_recovery_interval_seconds:
                    return False

            # Check cooldown
            if state.disabled_at is not None:
                elapsed = time.monotonic() - state.disabled_at
                if elapsed < self.policy.cooldown_seconds:
                    return False

            return True

    def prepare_recovery(self, model_id: str, version: str) -> bool:
        """
        Prepare circuit breaker state for a recovery attempt.

        This transitions the circuit to HALF_OPEN state.

        Returns:
            True if recovery preparation succeeded
        """
        with self._lock:
            state = self._states.get(f"{model_id}:{version}")
            if state is None:
                return False

            if state.state != CircuitState.OPEN:
                return False

            state.reset_for_recovery()

        logger.info(
            "Circuit breaker prepared for recovery",
            extra={
                "model_id": model_id,
                "version": version,
                "recovery_attempt": state.recovery_attempts,
            },
        )

        return True

    def abort_recovery(self, model_id: str, version: str, reason: str) -> None:
        """
        Abort a recovery attempt and return to OPEN state.

        Called when recovery fails or is cancelled.
        """
        with self._lock:
            state = self._states.get(f"{model_id}:{version}")
            if state is None:
                return

            if state.state == CircuitState.HALF_OPEN:
                state.state = CircuitState.OPEN
                state.half_open_started = None
                state.half_open_successes = 0

        logger.warning(
            "Recovery attempt aborted",
            extra={
                "model_id": model_id,
                "version": version,
                "reason": reason,
                "recovery_attempts": state.recovery_attempts,
            },
        )

    def force_close(self, model_id: str, version: str) -> bool:
        """
        Force close a circuit (admin override).

        This resets all failure tracking. Use with caution.

        Returns:
            True if circuit was closed
        """
        with self._lock:
            state = self._states.get(f"{model_id}:{version}")
            if state is None:
                return False

            state.close_circuit()
            state.recovery_attempts = 0  # Full reset

        # Persist state change
        self._persist_state()

        logger.info(
            "Circuit breaker force closed",
            extra={
                "model_id": model_id,
                "version": version,
            },
        )

        return True

    def remove_state(self, model_id: str, version: str) -> bool:
        """
        Remove circuit breaker state for a model version.

        Called when a model is unloaded/removed.

        Returns:
            True if state was removed
        """
        qualified_id = f"{model_id}:{version}"
        removed = False

        with self._lock:
            if qualified_id in self._states:
                del self._states[qualified_id]
                removed = True

        if removed:
            self._persist_state()
            return True

        return False

    def get_all_states(self) -> dict[str, CircuitState]:
        """Get circuit state for all tracked models."""
        with self._lock:
            return {
                qid: state.state
                for qid, state in self._states.items()
            }

    def get_open_circuits(self) -> list[tuple[str, str, DisablementReason]]:
        """
        Get all models with open circuits.

        Returns:
            List of (model_id, version, reason) tuples
        """
        with self._lock:
            results = []
            for state in self._states.values():
                if state.state == CircuitState.OPEN:
                    results.append((
                        state.model_id,
                        state.version,
                        state.disabled_reason or DisablementReason.REPEATED_FAILURES,
                    ))
            return results


# =============================================================================
# RECOVERY MANAGER - Coordinates disablement and re-enable operations
# =============================================================================


class RecoveryManager:
    """
    Manages model disablement and recovery operations.

    Coordinates between CircuitBreaker, ModelRegistry, and
    VersionLifecycleManager to safely disable and re-enable models.

    Design Principles:
    - Single source of truth for disablement operations
    - Safety checks before re-enabling
    - Audit trail for all operations
    - Integration with existing lifecycle management

    Usage:
        manager = RecoveryManager(
            registry=registry,
            lifecycle_manager=lifecycle_manager,
            circuit_breaker=circuit_breaker,
        )

        # Disable a failing model
        result = manager.disable_model(
            model_id="fall-detection",
            version="1.0.0",
            reason="Repeated timeout failures",
        )

        # Re-enable after investigation
        result = manager.enable_model(
            model_id="fall-detection",
            version="1.0.0",
            force=False,  # Respect cooldown
        )
    """

    # Type aliases for callbacks
    DisableCallback = Callable[[str, str, str], None]  # model_id, version, reason
    EnableCallback = Callable[[str, str], None]  # model_id, version

    def __init__(
        self,
        registry: Any,  # ModelRegistry - Any to avoid circular import
        lifecycle_manager: Any,  # VersionLifecycleManager
        circuit_breaker: CircuitBreaker,
        on_disable: Optional[DisableCallback] = None,
        on_enable: Optional[EnableCallback] = None,
    ):
        """
        Initialize the recovery manager.

        Args:
            registry: ModelRegistry instance
            lifecycle_manager: VersionLifecycleManager instance
            circuit_breaker: CircuitBreaker instance
            on_disable: Optional callback when model is disabled
            on_enable: Optional callback when model is enabled
        """
        self.registry = registry
        self.lifecycle_manager = lifecycle_manager
        self.circuit_breaker = circuit_breaker
        self._on_disable = on_disable
        self._on_enable = on_enable
        self._lock = threading.Lock()

        # Audit log of operations
        self._operations: list[dict[str, Any]] = []
        self._max_operations = 1000  # Keep last 1000 operations

    def disable_model(
        self,
        model_id: str,
        version: str,
        reason: str,
        is_manual: bool = False,
    ) -> RecoveryResult:
        """
        Disable a model version.

        Args:
            model_id: Model identifier
            version: Model version
            reason: Human-readable reason for disablement
            is_manual: Whether this is a manual admin action

        Returns:
            RecoveryResult with operation outcome
        """
        with self._lock:
            # Get current state
            descriptor = self.registry.get_version(model_id, version)
            if descriptor is None:
                return RecoveryResult(
                    success=False,
                    model_id=model_id,
                    version=version,
                    message=f"Model version not found: {model_id}:{version}",
                )

            previous_state = descriptor.state

            # Already disabled?
            if previous_state == LoadState.DISABLED:
                return RecoveryResult(
                    success=True,
                    model_id=model_id,
                    version=version,
                    message="Model already disabled",
                    previous_state=previous_state,
                    new_state=LoadState.DISABLED,
                )

            # Use lifecycle manager to disable
            disable_reason = f"{'Manual: ' if is_manual else ''}{reason}"
            success = self.lifecycle_manager.mark_disabled(
                model_id,
                version,
                disable_reason,
            )

            if not success:
                return RecoveryResult(
                    success=False,
                    model_id=model_id,
                    version=version,
                    message="Failed to transition model to DISABLED state",
                    previous_state=previous_state,
                )

            # Record operation
            self._record_operation(
                "disable",
                model_id,
                version,
                reason=reason,
                is_manual=is_manual,
                previous_state=previous_state.value,
            )

        logger.warning(
            "Model disabled",
            extra={
                "model_id": model_id,
                "version": version,
                "reason": reason,
                "is_manual": is_manual,
                "previous_state": previous_state.value,
            },
        )

        # Trigger callback outside lock
        if self._on_disable:
            try:
                self._on_disable(model_id, version, reason)
            except Exception as e:
                logger.warning(
                    "Disable callback failed",
                    extra={
                        "model_id": model_id,
                        "version": version,
                        "error": str(e),
                    },
                )

        # Get circuit breaker state for recovery attempts count
        cb_state = self.circuit_breaker.get_state(model_id, version)
        recovery_attempts = cb_state.recovery_attempts if cb_state else 0

        return RecoveryResult(
            success=True,
            model_id=model_id,
            version=version,
            message=f"Model disabled: {reason}",
            previous_state=previous_state,
            new_state=LoadState.DISABLED,
            recovery_attempts=recovery_attempts,
        )

    def enable_model(
        self,
        model_id: str,
        version: str,
        force: bool = False,
    ) -> RecoveryResult:
        """
        Re-enable a disabled model version.

        Args:
            model_id: Model identifier
            version: Model version
            force: If True, bypass cooldown and safety checks

        Returns:
            RecoveryResult with operation outcome
        """
        with self._lock:
            # Get current state
            descriptor = self.registry.get_version(model_id, version)
            if descriptor is None:
                return RecoveryResult(
                    success=False,
                    model_id=model_id,
                    version=version,
                    message=f"Model version not found: {model_id}:{version}",
                )

            previous_state = descriptor.state

            # Must be in DISABLED state
            if previous_state != LoadState.DISABLED:
                return RecoveryResult(
                    success=False,
                    model_id=model_id,
                    version=version,
                    message=f"Model is not disabled (state: {previous_state.value})",
                    previous_state=previous_state,
                )

            # Check if recovery is allowed (unless forced)
            if not force:
                if not self.circuit_breaker.can_attempt_recovery(model_id, version):
                    cb_state = self.circuit_breaker.get_state(model_id, version)
                    recovery_attempts = cb_state.recovery_attempts if cb_state else 0
                    max_attempts = self.circuit_breaker.policy.max_recovery_attempts

                    if recovery_attempts >= max_attempts:
                        return RecoveryResult(
                            success=False,
                            model_id=model_id,
                            version=version,
                            message=f"Max recovery attempts ({max_attempts}) exceeded. Use force=True to override.",
                            previous_state=previous_state,
                            recovery_attempts=recovery_attempts,
                        )
                    else:
                        return RecoveryResult(
                            success=False,
                            model_id=model_id,
                            version=version,
                            message="Recovery cooldown not elapsed. Use force=True to override.",
                            previous_state=previous_state,
                            recovery_attempts=recovery_attempts,
                        )

            # Prepare circuit breaker for recovery (or force close)
            if force:
                self.circuit_breaker.force_close(model_id, version)
            else:
                if not self.circuit_breaker.prepare_recovery(model_id, version):
                    return RecoveryResult(
                        success=False,
                        model_id=model_id,
                        version=version,
                        message="Failed to prepare circuit breaker for recovery",
                        previous_state=previous_state,
                    )

            # Transition to DISCOVERED for re-loading
            # The loader will pick this up and attempt to load
            success = self.registry.update_state(
                model_id,
                version,
                LoadState.DISCOVERED,
                error=None,  # Clear previous error
            )

            if not success:
                # Revert circuit breaker state
                self.circuit_breaker.abort_recovery(
                    model_id,
                    version,
                    "Failed to update registry state",
                )
                return RecoveryResult(
                    success=False,
                    model_id=model_id,
                    version=version,
                    message="Failed to transition model to DISCOVERED state",
                    previous_state=previous_state,
                )

            # Record operation
            cb_state = self.circuit_breaker.get_state(model_id, version)
            recovery_attempts = cb_state.recovery_attempts if cb_state else 0

            self._record_operation(
                "enable",
                model_id,
                version,
                force=force,
                previous_state=previous_state.value,
                recovery_attempts=recovery_attempts,
            )

        logger.info(
            "Model re-enabled",
            extra={
                "model_id": model_id,
                "version": version,
                "force": force,
                "recovery_attempts": recovery_attempts,
            },
        )

        # Trigger callback outside lock
        if self._on_enable:
            try:
                self._on_enable(model_id, version)
            except Exception as e:
                logger.warning(
                    "Enable callback failed",
                    extra={
                        "model_id": model_id,
                        "version": version,
                        "error": str(e),
                    },
                )

        return RecoveryResult(
            success=True,
            model_id=model_id,
            version=version,
            message=f"Model re-enabled (recovery attempt #{recovery_attempts})",
            previous_state=previous_state,
            new_state=LoadState.DISCOVERED,
            recovery_attempts=recovery_attempts,
        )

    def get_disabled_models(self) -> list[tuple[str, str, str]]:
        """
        Get all disabled model versions.

        Returns:
            List of (model_id, version, reason) tuples
        """
        disabled = []

        for model_id in self.registry.get_model_ids():
            for version_desc in self.registry.get_versions(model_id):
                if version_desc.state == LoadState.DISABLED:
                    reason = version_desc.error or "Unknown"
                    disabled.append((model_id, version_desc.version, reason))

        return disabled

    def can_recover(self, model_id: str, version: str) -> tuple[bool, str]:
        """
        Check if a model can be recovered.

        Returns:
            Tuple of (can_recover, reason_if_not)
        """
        descriptor = self.registry.get_version(model_id, version)
        if descriptor is None:
            return False, "Model not found"

        if descriptor.state != LoadState.DISABLED:
            return False, f"Model is not disabled (state: {descriptor.state.value})"

        if self.circuit_breaker.can_attempt_recovery(model_id, version):
            return True, "Recovery allowed"

        cb_state = self.circuit_breaker.get_state(model_id, version)
        if cb_state is None:
            return True, "No circuit breaker state, recovery allowed"

        if cb_state.recovery_attempts >= self.circuit_breaker.policy.max_recovery_attempts:
            return False, f"Max recovery attempts ({self.circuit_breaker.policy.max_recovery_attempts}) exceeded"

        return False, "Recovery cooldown not elapsed"

    def notify_load_success(self, model_id: str, version: str) -> None:
        """
        Notify that a model has been successfully loaded.

        Called by the loader after a recovery load succeeds.
        This can transition circuit from HALF_OPEN to CLOSED.
        """
        # Record a success in circuit breaker
        if self.circuit_breaker.record_success(model_id, version):
            logger.info(
                "Model recovery confirmed",
                extra={
                    "model_id": model_id,
                    "version": version,
                },
            )

    def notify_load_failure(self, model_id: str, version: str, error: str) -> None:
        """
        Notify that a model load has failed.

        Called by the loader when a recovery load fails.
        This aborts the recovery and re-opens the circuit.
        """
        self.circuit_breaker.abort_recovery(model_id, version, error)

        # Re-disable the model
        self.disable_model(
            model_id,
            version,
            f"Recovery load failed: {error}",
            is_manual=False,
        )

    def _record_operation(
        self,
        operation: str,
        model_id: str,
        version: str,
        **kwargs: Any,
    ) -> None:
        """Record an operation for audit purposes."""
        record = {
            "operation": operation,
            "model_id": model_id,
            "version": version,
            "timestamp": datetime.utcnow().isoformat(),
            **kwargs,
        }
        self._operations.append(record)

        # Prune old operations
        if len(self._operations) > self._max_operations:
            self._operations = self._operations[-self._max_operations:]

    def get_operation_history(
        self,
        model_id: Optional[str] = None,
        version: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get operation history, optionally filtered.

        Args:
            model_id: Filter by model ID
            version: Filter by version
            limit: Maximum number of records

        Returns:
            List of operation records (newest first)
        """
        with self._lock:
            records = self._operations.copy()

        # Filter if requested
        if model_id is not None:
            records = [r for r in records if r["model_id"] == model_id]
        if version is not None:
            records = [r for r in records if r["version"] == version]

        # Return newest first, limited
        return list(reversed(records[-limit:]))


# =============================================================================
# FACTORY FUNCTION - Create configured recovery stack
# =============================================================================


def create_recovery_stack(
    registry: Any,
    lifecycle_manager: Any,
    policy: Optional[FailurePolicy] = None,
    on_disable: Optional[RecoveryManager.DisableCallback] = None,
    on_enable: Optional[RecoveryManager.EnableCallback] = None,
) -> dict[str, Any]:
    """
    Create a configured recovery stack with all components wired together.

    Args:
        registry: ModelRegistry instance
        lifecycle_manager: VersionLifecycleManager instance
        policy: Optional failure policy (defaults to FailurePolicy())
        on_disable: Optional callback when model is disabled
        on_enable: Optional callback when model is enabled

    Returns:
        Dictionary with:
        - circuit_breaker: CircuitBreaker instance
        - recovery_manager: RecoveryManager instance
        - policy: FailurePolicy used
    """
    policy = policy or FailurePolicy()
    circuit_breaker = CircuitBreaker(policy=policy)

    recovery_manager = RecoveryManager(
        registry=registry,
        lifecycle_manager=lifecycle_manager,
        circuit_breaker=circuit_breaker,
        on_disable=on_disable,
        on_enable=on_enable,
    )

    # Wire circuit breaker to auto-disable through recovery manager
    def on_should_disable(
        model_id: str,
        version: str,
        reason: DisablementReason,
    ) -> None:
        recovery_manager.disable_model(
            model_id,
            version,
            reason.value.replace("_", " ").title(),
            is_manual=False,
        )

    circuit_breaker.set_disable_callback(on_should_disable)

    logger.info(
        "Recovery stack created",
        extra={
            "failure_threshold": policy.failure_threshold,
            "unhealthy_threshold": policy.unhealthy_threshold,
            "cooldown_seconds": policy.cooldown_seconds,
            "max_recovery_attempts": policy.max_recovery_attempts,
        },
    )

    return {
        "circuit_breaker": circuit_breaker,
        "recovery_manager": recovery_manager,
        "policy": policy,
    }
