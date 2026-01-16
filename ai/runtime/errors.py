"""
Ruth AI Runtime - Error Classification

This module defines the error taxonomy for the model loading and registry
subsystem. Errors are classified by source and severity to enable:

1. Proper error handling at each stage
2. Clear logging with structured error codes
3. Isolation of failures to prevent cascade effects
4. Actionable error messages for operators

Error Categories:
- DiscoveryError: Filesystem scanning failures
- ValidationError: Contract validation failures
- LoadError: Model loading failures
- ContractError: model.yaml parsing/schema failures
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class ErrorCode(Enum):
    """
    Enumeration of all error codes in the runtime.

    Error code format: CATEGORY_SPECIFIC_ERROR
    Categories:
    - DISC: Discovery errors
    - VAL: Validation errors
    - LOAD: Loading errors
    - CONTRACT: Contract parsing errors
    """

    # ==========================================================================
    # Discovery Errors (DISC_*)
    # ==========================================================================

    # Model root directory not found
    DISC_ROOT_NOT_FOUND = "DISC_ROOT_NOT_FOUND"

    # Model root is not a directory
    DISC_ROOT_NOT_DIRECTORY = "DISC_ROOT_NOT_DIRECTORY"

    # Permission denied reading model root
    DISC_PERMISSION_DENIED = "DISC_PERMISSION_DENIED"

    # Invalid model_id directory name
    DISC_INVALID_MODEL_ID = "DISC_INVALID_MODEL_ID"

    # Invalid version directory name
    DISC_INVALID_VERSION = "DISC_INVALID_VERSION"

    # No valid versions found for model
    DISC_NO_VERSIONS = "DISC_NO_VERSIONS"

    # Symlink points outside allowed directory
    DISC_FORBIDDEN_SYMLINK = "DISC_FORBIDDEN_SYMLINK"

    # ==========================================================================
    # Validation Errors (VAL_*)
    # ==========================================================================

    # model.yaml file not found
    VAL_CONTRACT_NOT_FOUND = "VAL_CONTRACT_NOT_FOUND"

    # model.yaml is not valid YAML
    VAL_INVALID_YAML = "VAL_INVALID_YAML"

    # Required field missing from model.yaml
    VAL_MISSING_REQUIRED_FIELD = "VAL_MISSING_REQUIRED_FIELD"

    # Field has invalid type
    VAL_INVALID_FIELD_TYPE = "VAL_INVALID_FIELD_TYPE"

    # Field value out of allowed range
    VAL_FIELD_OUT_OF_RANGE = "VAL_FIELD_OUT_OF_RANGE"

    # model_id in contract doesn't match directory
    VAL_MODEL_ID_MISMATCH = "VAL_MODEL_ID_MISMATCH"

    # version in contract doesn't match directory
    VAL_VERSION_MISMATCH = "VAL_VERSION_MISMATCH"

    # Required file missing (inference.py, weights/)
    VAL_REQUIRED_FILE_MISSING = "VAL_REQUIRED_FILE_MISSING"

    # Entry point file exists but invalid
    VAL_INVALID_ENTRY_POINT = "VAL_INVALID_ENTRY_POINT"

    # Schema version not supported
    VAL_UNSUPPORTED_SCHEMA_VERSION = "VAL_UNSUPPORTED_SCHEMA_VERSION"

    # Hardware compatibility check failed
    VAL_HARDWARE_INCOMPATIBLE = "VAL_HARDWARE_INCOMPATIBLE"

    # Input type not recognized
    VAL_INVALID_INPUT_TYPE = "VAL_INVALID_INPUT_TYPE"

    # Output schema invalid
    VAL_INVALID_OUTPUT_SCHEMA = "VAL_INVALID_OUTPUT_SCHEMA"

    # Forbidden content detected
    VAL_FORBIDDEN_CONTENT = "VAL_FORBIDDEN_CONTENT"

    # ==========================================================================
    # Loading Errors (LOAD_*)
    # ==========================================================================

    # Failed to import inference module
    LOAD_IMPORT_FAILED = "LOAD_IMPORT_FAILED"

    # infer() function not found in inference.py
    LOAD_INFER_NOT_FOUND = "LOAD_INFER_NOT_FOUND"

    # preprocess() function not found when preprocessing.py exists
    LOAD_PREPROCESS_NOT_FOUND = "LOAD_PREPROCESS_NOT_FOUND"

    # postprocess() function not found when postprocessing.py exists
    LOAD_POSTPROCESS_NOT_FOUND = "LOAD_POSTPROCESS_NOT_FOUND"

    # Python syntax error in model code
    LOAD_SYNTAX_ERROR = "LOAD_SYNTAX_ERROR"

    # Failed to load model weights
    LOAD_WEIGHTS_FAILED = "LOAD_WEIGHTS_FAILED"

    # Out of memory during loading
    LOAD_OUT_OF_MEMORY = "LOAD_OUT_OF_MEMORY"

    # Loading timed out
    LOAD_TIMEOUT = "LOAD_TIMEOUT"

    # Warmup inference failed
    LOAD_WARMUP_FAILED = "LOAD_WARMUP_FAILED"

    # Missing dependency
    LOAD_MISSING_DEPENDENCY = "LOAD_MISSING_DEPENDENCY"

    # Generic loading error
    LOAD_GENERIC_ERROR = "LOAD_GENERIC_ERROR"

    # ==========================================================================
    # Contract Errors (CONTRACT_*)
    # ==========================================================================

    # Cannot parse YAML
    CONTRACT_PARSE_ERROR = "CONTRACT_PARSE_ERROR"

    # Schema validation failed
    CONTRACT_SCHEMA_ERROR = "CONTRACT_SCHEMA_ERROR"

    # Conditional requirement not met
    CONTRACT_CONDITIONAL_ERROR = "CONTRACT_CONDITIONAL_ERROR"

    # ==========================================================================
    # Execution Errors (EXEC_*)
    # ==========================================================================

    # Preprocessing step failed with exception
    EXEC_PREPROCESS_FAILED = "EXEC_PREPROCESS_FAILED"

    # Preprocessing step timed out
    EXEC_PREPROCESS_TIMEOUT = "EXEC_PREPROCESS_TIMEOUT"

    # Inference step failed with exception
    EXEC_INFERENCE_FAILED = "EXEC_INFERENCE_FAILED"

    # Inference step timed out
    EXEC_INFERENCE_TIMEOUT = "EXEC_INFERENCE_TIMEOUT"

    # Postprocessing step failed with exception
    EXEC_POSTPROCESS_FAILED = "EXEC_POSTPROCESS_FAILED"

    # Postprocessing step timed out
    EXEC_POSTPROCESS_TIMEOUT = "EXEC_POSTPROCESS_TIMEOUT"

    # Out of memory during execution
    EXEC_OUT_OF_MEMORY = "EXEC_OUT_OF_MEMORY"

    # Invalid input to execution pipeline
    EXEC_INVALID_INPUT = "EXEC_INVALID_INPUT"

    # Invalid output from model (schema violation)
    EXEC_INVALID_OUTPUT = "EXEC_INVALID_OUTPUT"

    # Execution cancelled by caller
    EXEC_CANCELLED = "EXEC_CANCELLED"

    # Model not ready for execution
    EXEC_MODEL_NOT_READY = "EXEC_MODEL_NOT_READY"

    # Generic execution error
    EXEC_GENERIC_ERROR = "EXEC_GENERIC_ERROR"

    # ==========================================================================
    # Pipeline Errors (PIPE_*)
    # ==========================================================================

    # Model not found in registry
    PIPE_MODEL_NOT_FOUND = "PIPE_MODEL_NOT_FOUND"

    # Version not found for model
    PIPE_VERSION_NOT_FOUND = "PIPE_VERSION_NOT_FOUND"

    # Model exists but is not ready (loading, failed, etc.)
    PIPE_MODEL_NOT_READY = "PIPE_MODEL_NOT_READY"

    # Model health is UNHEALTHY
    PIPE_MODEL_UNHEALTHY = "PIPE_MODEL_UNHEALTHY"

    # Version exists but is not ready (loading, failed, etc.)
    PIPE_VERSION_NOT_READY = "PIPE_VERSION_NOT_READY"

    # Version health is UNHEALTHY
    PIPE_VERSION_UNHEALTHY = "PIPE_VERSION_UNHEALTHY"

    # No eligible versions available (all prerelease or invalid)
    PIPE_NO_ELIGIBLE_VERSION = "PIPE_NO_ELIGIBLE_VERSION"

    # Version resolution failed (ambiguous or constraint violation)
    PIPE_VERSION_RESOLUTION_FAILED = "PIPE_VERSION_RESOLUTION_FAILED"

    # Invalid frame reference structure
    PIPE_INVALID_FRAME_REF = "PIPE_INVALID_FRAME_REF"

    # Input type mismatch (e.g., batch sent to frame-only model)
    PIPE_INPUT_TYPE_MISMATCH = "PIPE_INPUT_TYPE_MISMATCH"

    # Batch size out of allowed range
    PIPE_BATCH_SIZE_INVALID = "PIPE_BATCH_SIZE_INVALID"

    # Temporal sequence length invalid
    PIPE_TEMPORAL_LENGTH_INVALID = "PIPE_TEMPORAL_LENGTH_INVALID"

    # No sandbox available for model
    PIPE_NO_SANDBOX = "PIPE_NO_SANDBOX"

    # Request validation failed
    PIPE_REQUEST_INVALID = "PIPE_REQUEST_INVALID"

    # ==========================================================================
    # Concurrency Errors (PIPE_CONCURRENCY_*)
    # ==========================================================================

    # Request rejected due to concurrency limits
    PIPE_CONCURRENCY_REJECTED = "PIPE_CONCURRENCY_REJECTED"

    # Global concurrency limit reached
    PIPE_CONCURRENCY_GLOBAL_LIMIT = "PIPE_CONCURRENCY_GLOBAL_LIMIT"

    # Per-model concurrency limit reached
    PIPE_CONCURRENCY_MODEL_LIMIT = "PIPE_CONCURRENCY_MODEL_LIMIT"

    # Per-version concurrency limit reached
    PIPE_CONCURRENCY_VERSION_LIMIT = "PIPE_CONCURRENCY_VERSION_LIMIT"

    # Hard backpressure active, rejecting all requests
    PIPE_CONCURRENCY_BACKPRESSURE = "PIPE_CONCURRENCY_BACKPRESSURE"

    # Generic pipeline error
    PIPE_GENERIC_ERROR = "PIPE_GENERIC_ERROR"

    def is_retryable(self) -> bool:
        """Check if error is potentially recoverable with retry."""
        retryable = {
            ErrorCode.DISC_PERMISSION_DENIED,
            ErrorCode.LOAD_OUT_OF_MEMORY,
            ErrorCode.LOAD_TIMEOUT,
            ErrorCode.LOAD_WARMUP_FAILED,
            # Execution timeouts are retryable (transient resource contention)
            ErrorCode.EXEC_PREPROCESS_TIMEOUT,
            ErrorCode.EXEC_INFERENCE_TIMEOUT,
            ErrorCode.EXEC_POSTPROCESS_TIMEOUT,
            # OOM during execution may be recoverable
            ErrorCode.EXEC_OUT_OF_MEMORY,
            # Concurrency rejections are retryable (transient capacity)
            ErrorCode.PIPE_CONCURRENCY_REJECTED,
            ErrorCode.PIPE_CONCURRENCY_GLOBAL_LIMIT,
            ErrorCode.PIPE_CONCURRENCY_MODEL_LIMIT,
            ErrorCode.PIPE_CONCURRENCY_VERSION_LIMIT,
            ErrorCode.PIPE_CONCURRENCY_BACKPRESSURE,
        }
        return self in retryable

    @property
    def category(self) -> str:
        """Return error category (DISC, VAL, LOAD, CONTRACT)."""
        return self.value.split("_")[0]


@dataclass
class ErrorContext:
    """
    Additional context for error reporting.

    Provides structured information for logging and debugging.
    """

    model_id: Optional[str] = None
    version: Optional[str] = None
    path: Optional[Path] = None
    field_name: Optional[str] = None
    expected: Optional[str] = None
    actual: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging."""
        result = {}
        if self.model_id:
            result["model_id"] = self.model_id
        if self.version:
            result["version"] = self.version
        if self.path:
            result["path"] = str(self.path)
        if self.field_name:
            result["field"] = self.field_name
        if self.expected:
            result["expected"] = self.expected
        if self.actual:
            result["actual"] = self.actual
        if self.details:
            result.update(self.details)
        return result


class ModelError(Exception):
    """
    Base exception for all model-related errors.

    All errors include:
    - Error code for programmatic handling
    - Human-readable message
    - Structured context for logging
    - Timestamp
    - Recoverable flag
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
        recoverable: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context or ErrorContext()
        self.cause = cause
        self.recoverable = recoverable
        self.timestamp = datetime.utcnow()

    def __str__(self) -> str:
        parts = [f"[{self.code.value}] {self.message}"]
        if self.context.model_id:
            parts.append(f"model={self.context.model_id}")
        if self.context.version:
            parts.append(f"version={self.context.version}")
        if self.context.path:
            parts.append(f"path={self.context.path}")
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for structured logging."""
        return {
            "error_code": self.code.value,
            "error_category": self.code.category,
            "message": self.message,
            "recoverable": self.recoverable,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context.to_dict(),
            "cause": str(self.cause) if self.cause else None,
        }

    def to_log_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary optimized for structured logging.

        Flattens context into top level for easier log querying.
        """
        result = {
            "error_code": self.code.value,
            "error_message": self.message,
            "recoverable": self.recoverable,
        }
        result.update(self.context.to_dict())
        if self.cause:
            result["cause"] = str(self.cause)
        return result


class DiscoveryError(ModelError):
    """
    Error during model discovery phase.

    Discovery errors occur when scanning the filesystem for models.
    These errors typically affect a single model/version but don't
    prevent other models from being discovered.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            code=code,
            message=message,
            context=context,
            cause=cause,
            recoverable=code.is_retryable(),
        )


class ValidationError(ModelError):
    """
    Error during contract validation phase.

    Validation errors occur when checking model.yaml and directory
    structure against the contract specification. These errors
    result in the model being marked INVALID.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            code=code,
            message=message,
            context=context,
            cause=cause,
            recoverable=False,  # Validation errors require human intervention
        )


class LoadError(ModelError):
    """
    Error during model loading phase.

    Load errors occur when importing model code or loading weights.
    Some load errors may be retryable (e.g., OOM after freeing memory).
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            code=code,
            message=message,
            context=context,
            cause=cause,
            recoverable=code.is_retryable(),
        )


class ContractError(ModelError):
    """
    Error parsing or validating model.yaml contract.

    Contract errors are a subset of validation errors specific to
    the model.yaml file itself.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            code=code,
            message=message,
            context=context,
            cause=cause,
            recoverable=False,
        )


class ExecutionError(ModelError):
    """
    Error during model execution (inference pipeline).

    Execution errors occur when running preprocess/infer/postprocess.
    These are the most common runtime errors and must be contained
    to prevent affecting other models.

    Execution errors include:
    - Exceptions raised by model code
    - Timeouts during any pipeline stage
    - Invalid input/output
    - Resource exhaustion
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
        stage: Optional[str] = None,  # preprocess, inference, postprocess
        duration_ms: Optional[int] = None,
    ):
        super().__init__(
            code=code,
            message=message,
            context=context,
            cause=cause,
            recoverable=code.is_retryable(),
        )
        self.stage = stage
        self.duration_ms = duration_ms

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for structured logging."""
        result = super().to_dict()
        if self.stage:
            result["stage"] = self.stage
        if self.duration_ms is not None:
            result["duration_ms"] = self.duration_ms
        return result

    def to_log_dict(self) -> dict[str, Any]:
        """Convert to dictionary optimized for structured logging."""
        result = super().to_log_dict()
        if self.stage:
            result["stage"] = self.stage
        if self.duration_ms is not None:
            result["duration_ms"] = self.duration_ms
        return result


class PipelineError(ModelError):
    """
    Error during inference pipeline routing and validation.

    Pipeline errors occur BEFORE execution, during:
    - Model/version resolution
    - Request validation
    - Input type checking
    - Health status checking

    These errors indicate the request cannot be processed,
    not that execution failed.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            code=code,
            message=message,
            context=context,
            cause=cause,
            recoverable=False,  # Pipeline errors require caller to fix request
        )
        self.request_id = request_id

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for structured logging."""
        result = super().to_dict()
        if self.request_id:
            result["request_id"] = self.request_id
        return result

    def to_log_dict(self) -> dict[str, Any]:
        """Convert to dictionary optimized for structured logging."""
        result = super().to_log_dict()
        if self.request_id:
            result["request_id"] = self.request_id
        return result


# =============================================================================
# Error Builder Functions
# =============================================================================


def discovery_error(
    code: ErrorCode,
    message: str,
    model_id: Optional[str] = None,
    version: Optional[str] = None,
    path: Optional[Path] = None,
    cause: Optional[Exception] = None,
    **details: Any,
) -> DiscoveryError:
    """Factory function for creating DiscoveryError with context."""
    return DiscoveryError(
        code=code,
        message=message,
        context=ErrorContext(
            model_id=model_id,
            version=version,
            path=path,
            details=details,
        ),
        cause=cause,
    )


def validation_error(
    code: ErrorCode,
    message: str,
    model_id: Optional[str] = None,
    version: Optional[str] = None,
    path: Optional[Path] = None,
    field_name: Optional[str] = None,
    expected: Optional[str] = None,
    actual: Optional[str] = None,
    cause: Optional[Exception] = None,
    **details: Any,
) -> ValidationError:
    """Factory function for creating ValidationError with context."""
    return ValidationError(
        code=code,
        message=message,
        context=ErrorContext(
            model_id=model_id,
            version=version,
            path=path,
            field_name=field_name,
            expected=expected,
            actual=actual,
            details=details,
        ),
        cause=cause,
    )


def load_error(
    code: ErrorCode,
    message: str,
    model_id: Optional[str] = None,
    version: Optional[str] = None,
    path: Optional[Path] = None,
    cause: Optional[Exception] = None,
    **details: Any,
) -> LoadError:
    """Factory function for creating LoadError with context."""
    return LoadError(
        code=code,
        message=message,
        context=ErrorContext(
            model_id=model_id,
            version=version,
            path=path,
            details=details,
        ),
        cause=cause,
    )


def contract_error(
    code: ErrorCode,
    message: str,
    model_id: Optional[str] = None,
    version: Optional[str] = None,
    path: Optional[Path] = None,
    field_name: Optional[str] = None,
    cause: Optional[Exception] = None,
    **details: Any,
) -> ContractError:
    """Factory function for creating ContractError with context."""
    return ContractError(
        code=code,
        message=message,
        context=ErrorContext(
            model_id=model_id,
            version=version,
            path=path,
            field_name=field_name,
            details=details,
        ),
        cause=cause,
    )


def execution_error(
    code: ErrorCode,
    message: str,
    model_id: Optional[str] = None,
    version: Optional[str] = None,
    stage: Optional[str] = None,
    duration_ms: Optional[int] = None,
    cause: Optional[Exception] = None,
    **details: Any,
) -> ExecutionError:
    """Factory function for creating ExecutionError with context."""
    return ExecutionError(
        code=code,
        message=message,
        context=ErrorContext(
            model_id=model_id,
            version=version,
            details=details,
        ),
        cause=cause,
        stage=stage,
        duration_ms=duration_ms,
    )


def pipeline_error(
    code: ErrorCode,
    message: str,
    model_id: Optional[str] = None,
    version: Optional[str] = None,
    request_id: Optional[str] = None,
    cause: Optional[Exception] = None,
    **details: Any,
) -> PipelineError:
    """Factory function for creating PipelineError with context."""
    return PipelineError(
        code=code,
        message=message,
        context=ErrorContext(
            model_id=model_id,
            version=version,
            details=details,
        ),
        cause=cause,
        request_id=request_id,
    )
