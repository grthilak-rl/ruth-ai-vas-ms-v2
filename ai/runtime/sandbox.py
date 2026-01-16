"""
Ruth AI Runtime - Model Execution Sandbox

This module provides a strict execution boundary for running model code.
All model execution (preprocess, infer, postprocess) happens inside
the sandbox, ensuring failures cannot crash, block, or corrupt the runtime.

Design Principles:
- Complete exception containment
- Timeout enforcement per stage
- Health state management based on failures
- Structured logging per execution
- Zero shared mutable state across models

The sandbox treats all model code as UNTRUSTED. A model cannot:
- Crash the runtime
- Affect other models
- Corrupt shared state
- Block indefinitely

Usage:
    sandbox = ExecutionSandbox(loaded_model, descriptor)
    result = sandbox.execute(frame)

    if result.success:
        output = result.output
    else:
        error = result.error
"""

from __future__ import annotations

import concurrent.futures
import functools
import logging
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

from ai.runtime.errors import (
    ErrorCode,
    ExecutionError,
    execution_error,
)
from ai.runtime.loader import LoadedModel
from ai.runtime.models import (
    HealthStatus,
    LoadState,
    ModelVersionDescriptor,
    ResourceLimits,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# ENUMS - Execution stages and outcomes
# =============================================================================


class ExecutionStage(Enum):
    """Stages of the execution pipeline."""

    PREPROCESS = "preprocess"
    INFERENCE = "inference"
    POSTPROCESS = "postprocess"


class ExecutionOutcome(Enum):
    """Possible outcomes of an execution attempt."""

    SUCCESS = "success"
    TIMEOUT = "timeout"
    EXCEPTION = "exception"
    CANCELLED = "cancelled"
    INVALID_INPUT = "invalid_input"
    INVALID_OUTPUT = "invalid_output"


# =============================================================================
# DATA CLASSES - Execution results and metrics
# =============================================================================


@dataclass
class StageResult:
    """Result of a single execution stage."""

    stage: ExecutionStage
    outcome: ExecutionOutcome
    duration_ms: int
    output: Any = None
    error: Optional[ExecutionError] = None

    @property
    def success(self) -> bool:
        return self.outcome == ExecutionOutcome.SUCCESS


@dataclass
class ExecutionResult:
    """
    Complete result of an execution request.

    Includes timing for each stage and final output/error.
    """

    success: bool
    output: Optional[dict[str, Any]] = None
    error: Optional[ExecutionError] = None

    # Timing breakdown
    preprocess_ms: int = 0
    inference_ms: int = 0
    postprocess_ms: int = 0
    total_ms: int = 0

    # Execution metadata
    model_id: str = ""
    version: str = ""
    request_id: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Stage results for detailed analysis
    stage_results: list[StageResult] = field(default_factory=list)

    @classmethod
    def success_result(
        cls,
        output: dict[str, Any],
        model_id: str,
        version: str,
        request_id: str,
        preprocess_ms: int,
        inference_ms: int,
        postprocess_ms: int,
        stage_results: list[StageResult],
    ) -> "ExecutionResult":
        """Create a successful execution result."""
        return cls(
            success=True,
            output=output,
            model_id=model_id,
            version=version,
            request_id=request_id,
            preprocess_ms=preprocess_ms,
            inference_ms=inference_ms,
            postprocess_ms=postprocess_ms,
            total_ms=preprocess_ms + inference_ms + postprocess_ms,
            stage_results=stage_results,
        )

    @classmethod
    def failure_result(
        cls,
        error: ExecutionError,
        model_id: str,
        version: str,
        request_id: str,
        preprocess_ms: int = 0,
        inference_ms: int = 0,
        postprocess_ms: int = 0,
        stage_results: Optional[list[StageResult]] = None,
    ) -> "ExecutionResult":
        """Create a failed execution result."""
        return cls(
            success=False,
            error=error,
            model_id=model_id,
            version=version,
            request_id=request_id,
            preprocess_ms=preprocess_ms,
            inference_ms=inference_ms,
            postprocess_ms=postprocess_ms,
            total_ms=preprocess_ms + inference_ms + postprocess_ms,
            stage_results=stage_results or [],
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        result = {
            "success": self.success,
            "model_id": self.model_id,
            "version": self.version,
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
            "timing": {
                "preprocess_ms": self.preprocess_ms,
                "inference_ms": self.inference_ms,
                "postprocess_ms": self.postprocess_ms,
                "total_ms": self.total_ms,
            },
        }
        if self.success:
            result["output"] = self.output
        else:
            result["error"] = self.error.to_dict() if self.error else None
        return result


@dataclass
class ExecutionMetrics:
    """
    Accumulated metrics for a sandbox instance.

    Used to track health and performance over time.
    """

    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    timeout_count: int = 0
    exception_count: int = 0

    # Timing statistics
    total_execution_time_ms: int = 0
    min_execution_time_ms: Optional[int] = None
    max_execution_time_ms: Optional[int] = None

    # Consecutive failure tracking for health transitions
    consecutive_failures: int = 0
    consecutive_successes: int = 0

    def record_success(self, duration_ms: int) -> None:
        """Record a successful execution."""
        self.total_executions += 1
        self.successful_executions += 1
        self.total_execution_time_ms += duration_ms
        self.consecutive_successes += 1
        self.consecutive_failures = 0

        if self.min_execution_time_ms is None or duration_ms < self.min_execution_time_ms:
            self.min_execution_time_ms = duration_ms
        if self.max_execution_time_ms is None or duration_ms > self.max_execution_time_ms:
            self.max_execution_time_ms = duration_ms

    def record_failure(self, is_timeout: bool = False) -> None:
        """Record a failed execution."""
        self.total_executions += 1
        self.failed_executions += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0

        if is_timeout:
            self.timeout_count += 1
        else:
            self.exception_count += 1

    @property
    def success_rate(self) -> float:
        """Calculate success rate as a percentage."""
        if self.total_executions == 0:
            return 100.0
        return (self.successful_executions / self.total_executions) * 100

    @property
    def average_execution_time_ms(self) -> Optional[float]:
        """Calculate average execution time."""
        if self.successful_executions == 0:
            return None
        return self.total_execution_time_ms / self.successful_executions


# =============================================================================
# HEALTH MANAGER - Determines health state from execution outcomes
# =============================================================================


class HealthManager:
    """
    Manages health state transitions based on execution outcomes.

    Health transitions are deterministic based on:
    - Consecutive failures
    - Error types (timeout vs exception)
    - Recovery (consecutive successes)
    """

    # Thresholds for health transitions
    DEGRADED_THRESHOLD = 3  # Consecutive failures to become DEGRADED
    UNHEALTHY_THRESHOLD = 5  # Consecutive failures to become UNHEALTHY
    RECOVERY_THRESHOLD = 5  # Consecutive successes to recover to HEALTHY

    def __init__(
        self,
        degraded_threshold: int = DEGRADED_THRESHOLD,
        unhealthy_threshold: int = UNHEALTHY_THRESHOLD,
        recovery_threshold: int = RECOVERY_THRESHOLD,
    ):
        self.degraded_threshold = degraded_threshold
        self.unhealthy_threshold = unhealthy_threshold
        self.recovery_threshold = recovery_threshold

    def determine_health(
        self,
        current_health: HealthStatus,
        metrics: ExecutionMetrics,
    ) -> HealthStatus:
        """
        Determine new health status based on metrics.

        Transitions:
        - HEALTHY → DEGRADED: consecutive_failures >= degraded_threshold
        - DEGRADED → UNHEALTHY: consecutive_failures >= unhealthy_threshold
        - DEGRADED → HEALTHY: consecutive_successes >= recovery_threshold
        - UNHEALTHY → DEGRADED: consecutive_successes >= recovery_threshold // 2
        - UNHEALTHY → HEALTHY: consecutive_successes >= recovery_threshold
        """
        consecutive_failures = metrics.consecutive_failures
        consecutive_successes = metrics.consecutive_successes

        # Check for degradation
        if consecutive_failures >= self.unhealthy_threshold:
            return HealthStatus.UNHEALTHY

        if consecutive_failures >= self.degraded_threshold:
            return HealthStatus.DEGRADED

        # Check for recovery
        if current_health == HealthStatus.UNHEALTHY:
            if consecutive_successes >= self.recovery_threshold:
                return HealthStatus.HEALTHY
            elif consecutive_successes >= self.recovery_threshold // 2:
                return HealthStatus.DEGRADED

        if current_health == HealthStatus.DEGRADED:
            if consecutive_successes >= self.recovery_threshold:
                return HealthStatus.HEALTHY

        # No change
        return current_health


# =============================================================================
# TIMEOUT EXECUTOR - Runs functions with timeout enforcement
# =============================================================================


class TimeoutExecutor:
    """
    Executes functions with strict timeout enforcement.

    Uses a thread pool to run functions and cancel them
    if they exceed the timeout.
    """

    def __init__(self, max_workers: int = 4):
        """
        Initialize the timeout executor.

        Args:
            max_workers: Maximum concurrent executions
        """
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="sandbox_exec_",
        )
        self._shutdown = False

    def execute_with_timeout(
        self,
        func: Callable[..., T],
        timeout_ms: int,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[Optional[T], Optional[Exception], int]:
        """
        Execute a function with timeout.

        Args:
            func: Function to execute
            timeout_ms: Timeout in milliseconds
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Tuple of (result, exception, duration_ms)
            - On success: (result, None, duration_ms)
            - On timeout: (None, TimeoutError, duration_ms)
            - On exception: (None, exception, duration_ms)
        """
        if self._shutdown:
            raise RuntimeError("Executor has been shut down")

        timeout_seconds = timeout_ms / 1000.0
        start_time = time.monotonic()

        try:
            future = self._executor.submit(func, *args, **kwargs)

            try:
                result = future.result(timeout=timeout_seconds)
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return result, None, duration_ms

            except concurrent.futures.TimeoutError:
                # Attempt to cancel the future (may not actually stop execution)
                future.cancel()
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return None, TimeoutError(f"Execution exceeded {timeout_ms}ms"), duration_ms

        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return None, e, duration_ms

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the executor."""
        self._shutdown = True
        self._executor.shutdown(wait=wait)


# =============================================================================
# EXECUTION SANDBOX - Main sandbox implementation
# =============================================================================


class ExecutionSandbox:
    """
    Isolated execution environment for a single model version.

    The sandbox wraps all model code execution (preprocess, infer, postprocess)
    with timeout enforcement, exception containment, and health tracking.

    Each model version gets its own sandbox instance. Sandboxes do not
    share state with each other.

    Usage:
        # Create sandbox for a loaded model
        sandbox = ExecutionSandbox(loaded_model, descriptor)

        # Execute inference
        result = sandbox.execute(frame, request_id="req-123")

        # Check health
        health = sandbox.current_health

        # Get metrics
        metrics = sandbox.metrics
    """

    # Type alias for health change callback
    # Signature: (model_id, version, old_health, new_health) -> None
    HealthChangeCallback = Callable[[str, str, HealthStatus, HealthStatus], None]

    def __init__(
        self,
        loaded_model: LoadedModel,
        descriptor: ModelVersionDescriptor,
        executor: Optional[TimeoutExecutor] = None,
        health_manager: Optional[HealthManager] = None,
        on_health_change: Optional["ExecutionSandbox.HealthChangeCallback"] = None,
    ):
        """
        Initialize the execution sandbox.

        Args:
            loaded_model: The loaded model with callable functions
            descriptor: Model version descriptor with limits/config
            executor: Optional timeout executor (created if not provided)
            health_manager: Optional health manager (created if not provided)
            on_health_change: Optional callback when health changes
        """
        self.loaded_model = loaded_model
        self.descriptor = descriptor
        self.model_id = loaded_model.model_id
        self.version = loaded_model.version
        self.qualified_id = f"{self.model_id}:{self.version}"

        # Extract timeout limits from descriptor
        self.limits = descriptor.limits
        self.preprocess_timeout_ms = self.limits.preprocessing_timeout_ms
        self.inference_timeout_ms = self.limits.inference_timeout_ms
        self.postprocess_timeout_ms = self.limits.postprocessing_timeout_ms

        # Execution infrastructure
        self._executor = executor or TimeoutExecutor(max_workers=2)
        self._owns_executor = executor is None
        self._health_manager = health_manager or HealthManager()

        # State tracking
        self._metrics = ExecutionMetrics()
        self._current_health = HealthStatus.HEALTHY
        self._lock = threading.Lock()

        # Health change callback
        self._on_health_change = on_health_change

        # Logging context
        self._log_context = {
            "model_id": self.model_id,
            "version": self.version,
        }

        logger.info(
            "Execution sandbox created",
            extra={
                **self._log_context,
                "preprocess_timeout_ms": self.preprocess_timeout_ms,
                "inference_timeout_ms": self.inference_timeout_ms,
                "postprocess_timeout_ms": self.postprocess_timeout_ms,
            },
        )

    @property
    def metrics(self) -> ExecutionMetrics:
        """Get current execution metrics."""
        with self._lock:
            return self._metrics

    @property
    def current_health(self) -> HealthStatus:
        """Get current health status."""
        with self._lock:
            return self._current_health

    def execute(
        self,
        frame: Any,
        request_id: Optional[str] = None,
        model_instance: Optional[Any] = None,
    ) -> ExecutionResult:
        """
        Execute the full inference pipeline on a frame.

        Pipeline: preprocess → infer → postprocess

        Each stage runs with its own timeout. If any stage fails,
        the pipeline aborts and returns the error.

        Args:
            frame: Input frame (numpy array, bytes, etc.)
            request_id: Optional request ID for tracing
            model_instance: Optional model instance override

        Returns:
            ExecutionResult with output or error
        """
        request_id = request_id or self._generate_request_id()
        start_time = time.monotonic()

        log_context = {
            **self._log_context,
            "request_id": request_id,
        }

        logger.debug("Starting execution", extra=log_context)

        stage_results: list[StageResult] = []
        preprocess_ms = 0
        inference_ms = 0
        postprocess_ms = 0

        try:
            # Stage 1: Preprocessing (optional)
            processed_input = frame
            if self.loaded_model.preprocess:
                preprocess_result = self._execute_stage(
                    ExecutionStage.PREPROCESS,
                    self.loaded_model.preprocess,
                    self.preprocess_timeout_ms,
                    frame,
                )
                stage_results.append(preprocess_result)

                if not preprocess_result.success:
                    return self._handle_failure(
                        preprocess_result.error,
                        request_id,
                        preprocess_ms=preprocess_result.duration_ms,
                        stage_results=stage_results,
                    )

                processed_input = preprocess_result.output
                preprocess_ms = preprocess_result.duration_ms

            # Stage 2: Inference (required)
            model = model_instance or self.loaded_model.model_instance
            if model is not None:
                infer_func = functools.partial(
                    self.loaded_model.infer,
                    model=model,
                )
            else:
                infer_func = self.loaded_model.infer

            inference_result = self._execute_stage(
                ExecutionStage.INFERENCE,
                infer_func,
                self.inference_timeout_ms,
                processed_input,
            )
            stage_results.append(inference_result)

            if not inference_result.success:
                return self._handle_failure(
                    inference_result.error,
                    request_id,
                    preprocess_ms=preprocess_ms,
                    inference_ms=inference_result.duration_ms,
                    stage_results=stage_results,
                )

            raw_output = inference_result.output
            inference_ms = inference_result.duration_ms

            # Validate inference output
            output_error = self._validate_output(raw_output)
            if output_error:
                return self._handle_failure(
                    output_error,
                    request_id,
                    preprocess_ms=preprocess_ms,
                    inference_ms=inference_ms,
                    stage_results=stage_results,
                )

            # Stage 3: Postprocessing (optional)
            final_output = raw_output
            if self.loaded_model.postprocess:
                postprocess_result = self._execute_stage(
                    ExecutionStage.POSTPROCESS,
                    self.loaded_model.postprocess,
                    self.postprocess_timeout_ms,
                    raw_output,
                )
                stage_results.append(postprocess_result)

                if not postprocess_result.success:
                    # Postprocess failed - discard result safely
                    logger.warning(
                        "Postprocessing failed, discarding result",
                        extra={
                            **log_context,
                            "error": str(postprocess_result.error),
                        },
                    )
                    return self._handle_failure(
                        postprocess_result.error,
                        request_id,
                        preprocess_ms=preprocess_ms,
                        inference_ms=inference_ms,
                        postprocess_ms=postprocess_result.duration_ms,
                        stage_results=stage_results,
                    )

                final_output = postprocess_result.output
                postprocess_ms = postprocess_result.duration_ms

            # Success!
            total_ms = preprocess_ms + inference_ms + postprocess_ms
            self._record_success(total_ms)

            logger.debug(
                "Execution completed successfully",
                extra={
                    **log_context,
                    "preprocess_ms": preprocess_ms,
                    "inference_ms": inference_ms,
                    "postprocess_ms": postprocess_ms,
                    "total_ms": total_ms,
                },
            )

            return ExecutionResult.success_result(
                output=final_output,
                model_id=self.model_id,
                version=self.version,
                request_id=request_id,
                preprocess_ms=preprocess_ms,
                inference_ms=inference_ms,
                postprocess_ms=postprocess_ms,
                stage_results=stage_results,
            )

        except Exception as e:
            # Catch-all for any unexpected errors
            error = execution_error(
                code=ErrorCode.EXEC_GENERIC_ERROR,
                message=f"Unexpected sandbox error: {e}",
                model_id=self.model_id,
                version=self.version,
                cause=e,
                traceback=traceback.format_exc(),
            )
            return self._handle_failure(
                error,
                request_id,
                preprocess_ms=preprocess_ms,
                inference_ms=inference_ms,
                postprocess_ms=postprocess_ms,
                stage_results=stage_results,
            )

    def _execute_stage(
        self,
        stage: ExecutionStage,
        func: Callable[..., Any],
        timeout_ms: int,
        input_data: Any,
    ) -> StageResult:
        """
        Execute a single pipeline stage with timeout.

        Args:
            stage: Which stage is being executed
            func: The function to call
            timeout_ms: Maximum time allowed
            input_data: Input to pass to the function

        Returns:
            StageResult with outcome and timing
        """
        result, exception, duration_ms = self._executor.execute_with_timeout(
            func,
            timeout_ms,
            input_data,
        )

        if exception is None:
            return StageResult(
                stage=stage,
                outcome=ExecutionOutcome.SUCCESS,
                duration_ms=duration_ms,
                output=result,
            )

        # Classify the exception
        if isinstance(exception, TimeoutError):
            error = self._create_timeout_error(stage, timeout_ms, duration_ms)
            return StageResult(
                stage=stage,
                outcome=ExecutionOutcome.TIMEOUT,
                duration_ms=duration_ms,
                error=error,
            )

        if isinstance(exception, MemoryError):
            error = execution_error(
                code=ErrorCode.EXEC_OUT_OF_MEMORY,
                message=f"Out of memory during {stage.value}",
                model_id=self.model_id,
                version=self.version,
                stage=stage.value,
                duration_ms=duration_ms,
                cause=exception,
            )
            return StageResult(
                stage=stage,
                outcome=ExecutionOutcome.EXCEPTION,
                duration_ms=duration_ms,
                error=error,
            )

        # Generic exception
        error = self._create_stage_error(stage, exception, duration_ms)
        return StageResult(
            stage=stage,
            outcome=ExecutionOutcome.EXCEPTION,
            duration_ms=duration_ms,
            error=error,
        )

    def _create_timeout_error(
        self,
        stage: ExecutionStage,
        timeout_ms: int,
        duration_ms: int,
    ) -> ExecutionError:
        """Create appropriate timeout error for stage."""
        code_map = {
            ExecutionStage.PREPROCESS: ErrorCode.EXEC_PREPROCESS_TIMEOUT,
            ExecutionStage.INFERENCE: ErrorCode.EXEC_INFERENCE_TIMEOUT,
            ExecutionStage.POSTPROCESS: ErrorCode.EXEC_POSTPROCESS_TIMEOUT,
        }

        return execution_error(
            code=code_map[stage],
            message=f"{stage.value.capitalize()} timed out after {timeout_ms}ms",
            model_id=self.model_id,
            version=self.version,
            stage=stage.value,
            duration_ms=duration_ms,
            timeout_limit_ms=timeout_ms,
        )

    def _create_stage_error(
        self,
        stage: ExecutionStage,
        exception: Exception,
        duration_ms: int,
    ) -> ExecutionError:
        """Create appropriate error for stage exception."""
        code_map = {
            ExecutionStage.PREPROCESS: ErrorCode.EXEC_PREPROCESS_FAILED,
            ExecutionStage.INFERENCE: ErrorCode.EXEC_INFERENCE_FAILED,
            ExecutionStage.POSTPROCESS: ErrorCode.EXEC_POSTPROCESS_FAILED,
        }

        return execution_error(
            code=code_map[stage],
            message=f"{stage.value.capitalize()} failed: {exception}",
            model_id=self.model_id,
            version=self.version,
            stage=stage.value,
            duration_ms=duration_ms,
            cause=exception,
            traceback=traceback.format_exc(),
        )

    def _validate_output(self, output: Any) -> Optional[ExecutionError]:
        """
        Validate inference output against expected schema.

        Returns None if valid, ExecutionError if invalid.
        """
        if output is None:
            return execution_error(
                code=ErrorCode.EXEC_INVALID_OUTPUT,
                message="Inference returned None",
                model_id=self.model_id,
                version=self.version,
                stage="inference",
            )

        if not isinstance(output, dict):
            return execution_error(
                code=ErrorCode.EXEC_INVALID_OUTPUT,
                message=f"Inference must return dict, got {type(output).__name__}",
                model_id=self.model_id,
                version=self.version,
                stage="inference",
            )

        return None

    def _handle_failure(
        self,
        error: ExecutionError,
        request_id: str,
        preprocess_ms: int = 0,
        inference_ms: int = 0,
        postprocess_ms: int = 0,
        stage_results: Optional[list[StageResult]] = None,
    ) -> ExecutionResult:
        """Handle execution failure and update health."""
        is_timeout = error.code in {
            ErrorCode.EXEC_PREPROCESS_TIMEOUT,
            ErrorCode.EXEC_INFERENCE_TIMEOUT,
            ErrorCode.EXEC_POSTPROCESS_TIMEOUT,
        }

        self._record_failure(is_timeout)

        logger.warning(
            "Execution failed",
            extra={
                **self._log_context,
                "request_id": request_id,
                "error_code": error.code.value,
                "error_message": error.message,
                "is_timeout": is_timeout,
            },
        )

        return ExecutionResult.failure_result(
            error=error,
            model_id=self.model_id,
            version=self.version,
            request_id=request_id,
            preprocess_ms=preprocess_ms,
            inference_ms=inference_ms,
            postprocess_ms=postprocess_ms,
            stage_results=stage_results,
        )

    def _record_success(self, duration_ms: int) -> None:
        """Record successful execution and update health."""
        old_health = None
        new_health = None

        with self._lock:
            old_health = self._current_health
            self._metrics.record_success(duration_ms)
            new_health = self._health_manager.determine_health(
                self._current_health,
                self._metrics,
            )
            self._current_health = new_health

        # Notify callback if health changed
        if old_health != new_health and self._on_health_change:
            try:
                self._on_health_change(
                    self.model_id,
                    self.version,
                    old_health,
                    new_health,
                )
            except Exception as e:
                logger.warning(
                    "Health change callback failed",
                    extra={
                        **self._log_context,
                        "error": str(e),
                    },
                )

    def _record_failure(self, is_timeout: bool) -> None:
        """Record failed execution and update health."""
        old_health = None
        new_health = None

        with self._lock:
            old_health = self._current_health
            self._metrics.record_failure(is_timeout)
            new_health = self._health_manager.determine_health(
                self._current_health,
                self._metrics,
            )
            self._current_health = new_health

        # Notify callback if health changed
        if old_health != new_health and self._on_health_change:
            try:
                self._on_health_change(
                    self.model_id,
                    self.version,
                    old_health,
                    new_health,
                )
            except Exception as e:
                logger.warning(
                    "Health change callback failed",
                    extra={
                        **self._log_context,
                        "error": str(e),
                    },
                )

    def _generate_request_id(self) -> str:
        """Generate a unique request ID."""
        import uuid
        return f"exec-{uuid.uuid4().hex[:12]}"

    def reset_metrics(self) -> None:
        """Reset execution metrics (for testing)."""
        with self._lock:
            self._metrics = ExecutionMetrics()
            self._current_health = HealthStatus.HEALTHY

    def shutdown(self) -> None:
        """Shutdown the sandbox and release resources."""
        if self._owns_executor:
            self._executor.shutdown(wait=False)

        logger.info(
            "Execution sandbox shutdown",
            extra={
                **self._log_context,
                "total_executions": self._metrics.total_executions,
                "success_rate": f"{self._metrics.success_rate:.1f}%",
            },
        )


# =============================================================================
# SANDBOX MANAGER - Manages sandboxes for all loaded models
# =============================================================================


class SandboxManager:
    """
    Manages execution sandboxes for all loaded models.

    Provides a centralized way to create, access, and destroy sandboxes
    while maintaining isolation between models.

    Usage:
        manager = SandboxManager()

        # Create sandbox for a model
        sandbox = manager.create_sandbox(loaded_model, descriptor)

        # Get existing sandbox
        sandbox = manager.get_sandbox("model_id", "1.0.0")

        # Execute through manager
        result = manager.execute("model_id", "1.0.0", frame)

        # Remove sandbox
        manager.remove_sandbox("model_id", "1.0.0")
    """

    def __init__(
        self,
        shared_executor: Optional[TimeoutExecutor] = None,
        health_manager: Optional[HealthManager] = None,
        on_health_change: Optional[ExecutionSandbox.HealthChangeCallback] = None,
    ):
        """
        Initialize the sandbox manager.

        Args:
            shared_executor: Optional shared executor for all sandboxes
            health_manager: Optional shared health manager
            on_health_change: Optional callback when any sandbox health changes
        """
        self._sandboxes: dict[str, ExecutionSandbox] = {}
        self._lock = threading.Lock()
        self._shared_executor = shared_executor
        self._health_manager = health_manager
        self._on_health_change = on_health_change

    def set_health_change_callback(
        self,
        callback: Optional[ExecutionSandbox.HealthChangeCallback],
    ) -> None:
        """
        Set or update the health change callback.

        This callback will be applied to all future sandboxes.
        Existing sandboxes are not affected.
        """
        self._on_health_change = callback

    def create_sandbox(
        self,
        loaded_model: LoadedModel,
        descriptor: ModelVersionDescriptor,
    ) -> ExecutionSandbox:
        """
        Create a new sandbox for a loaded model.

        Args:
            loaded_model: The loaded model
            descriptor: Model version descriptor

        Returns:
            New ExecutionSandbox instance
        """
        qualified_id = f"{loaded_model.model_id}:{loaded_model.version}"

        with self._lock:
            if qualified_id in self._sandboxes:
                logger.warning(
                    "Sandbox already exists, replacing",
                    extra={
                        "model_id": loaded_model.model_id,
                        "version": loaded_model.version,
                    },
                )
                old_sandbox = self._sandboxes[qualified_id]
                old_sandbox.shutdown()

            sandbox = ExecutionSandbox(
                loaded_model=loaded_model,
                descriptor=descriptor,
                executor=self._shared_executor,
                health_manager=self._health_manager,
                on_health_change=self._on_health_change,
            )
            self._sandboxes[qualified_id] = sandbox

        return sandbox

    def get_sandbox(
        self,
        model_id: str,
        version: str,
    ) -> Optional[ExecutionSandbox]:
        """
        Get sandbox for a specific model version.

        Args:
            model_id: Model identifier
            version: Model version

        Returns:
            ExecutionSandbox or None if not found
        """
        qualified_id = f"{model_id}:{version}"

        with self._lock:
            return self._sandboxes.get(qualified_id)

    def remove_sandbox(self, model_id: str, version: str) -> bool:
        """
        Remove and shutdown a sandbox.

        Args:
            model_id: Model identifier
            version: Model version

        Returns:
            True if removed, False if not found
        """
        qualified_id = f"{model_id}:{version}"

        with self._lock:
            sandbox = self._sandboxes.pop(qualified_id, None)

        if sandbox:
            sandbox.shutdown()
            return True
        return False

    def execute(
        self,
        model_id: str,
        version: str,
        frame: Any,
        request_id: Optional[str] = None,
    ) -> ExecutionResult:
        """
        Execute inference through the appropriate sandbox.

        Args:
            model_id: Model identifier
            version: Model version
            frame: Input frame
            request_id: Optional request ID

        Returns:
            ExecutionResult
        """
        sandbox = self.get_sandbox(model_id, version)

        if sandbox is None:
            error = execution_error(
                code=ErrorCode.EXEC_MODEL_NOT_READY,
                message=f"No sandbox found for {model_id}:{version}",
                model_id=model_id,
                version=version,
            )
            return ExecutionResult.failure_result(
                error=error,
                model_id=model_id,
                version=version,
                request_id=request_id or "",
            )

        return sandbox.execute(frame, request_id)

    def get_all_health(self) -> dict[str, HealthStatus]:
        """
        Get health status for all sandboxes.

        Returns:
            Dictionary mapping qualified_id to health status
        """
        with self._lock:
            return {
                qid: sandbox.current_health
                for qid, sandbox in self._sandboxes.items()
            }

    def get_all_metrics(self) -> dict[str, ExecutionMetrics]:
        """
        Get metrics for all sandboxes.

        Returns:
            Dictionary mapping qualified_id to metrics
        """
        with self._lock:
            return {
                qid: sandbox.metrics
                for qid, sandbox in self._sandboxes.items()
            }

    @property
    def sandbox_count(self) -> int:
        """Get number of active sandboxes."""
        with self._lock:
            return len(self._sandboxes)

    def shutdown_all(self) -> None:
        """Shutdown all sandboxes."""
        with self._lock:
            sandboxes = list(self._sandboxes.values())
            self._sandboxes.clear()

        for sandbox in sandboxes:
            sandbox.shutdown()

        if self._shared_executor:
            self._shared_executor.shutdown(wait=False)

        logger.info(
            "All sandboxes shutdown",
            extra={"count": len(sandboxes)},
        )
