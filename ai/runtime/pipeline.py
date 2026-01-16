"""
Ruth AI Runtime - Frame Reference Ingestion Pipeline

This module provides the public inference API that connects the backend's
AI Runtime Client to the Model Execution Sandbox. It handles:

1. Accepting opaque frame references (no raw data)
2. Resolving model_id + version to sandbox instances
3. Validating requests against model contracts
4. Routing execution through sandboxes
5. Returning opaque inference results

CRITICAL RULES:
- Runtime MUST NOT accept raw frames
- Runtime MUST NOT decode video
- Runtime MUST NOT talk to VAS
- frame_reference is an opaque handle only
- No interpretation of model output semantics

Design Principles:
- Model-agnostic request handling
- Strict contract adherence
- No implicit conversions
- Deterministic error classification
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Union

from ai.runtime.errors import (
    ErrorCode,
    ExecutionError,
    ModelError,
    PipelineError,
    pipeline_error,
)
from ai.runtime.models import (
    HealthStatus,
    InputType,
    LoadState,
    ModelVersionDescriptor,
)
from ai.runtime.registry import ModelRegistry
from ai.runtime.sandbox import (
    ExecutionResult,
    ExecutionSandbox,
    SandboxManager,
)
from ai.runtime.versioning import (
    VersionResolver,
    EligibilityConfig,
    ResolutionResult,
    DEFAULT_ELIGIBILITY,
    STRICT_ELIGIBILITY,
)
from ai.runtime.concurrency import (
    AdmissionController,
    ConcurrencyManager,
    ConcurrencySlot,
    BackpressureLevel,
)

logger = logging.getLogger(__name__)


# =============================================================================
# FRAME REFERENCE - Opaque handle to frame data
# =============================================================================


@dataclass(frozen=True)
class FrameReference:
    """
    Opaque reference to a frame.

    The runtime does NOT access frame content through this reference.
    Actual frame retrieval is handled by the model's preprocessing
    or an external frame provider (out of scope).

    This is a handle containing only metadata needed for routing
    and validation.
    """

    # Unique identifier for this frame reference
    ref_id: str

    # Source camera identifier
    camera_id: str

    # Timestamp when frame was captured (ISO format)
    timestamp: str

    # Optional metadata (width, height, format hints)
    # This is advisory only - not enforced by pipeline
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "ref_id": self.ref_id,
            "camera_id": self.camera_id,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FrameReference":
        """Create from dictionary."""
        return cls(
            ref_id=data.get("ref_id", ""),
            camera_id=data.get("camera_id", ""),
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class BatchFrameReference:
    """
    Reference to a batch of frames for batch-capable models.

    Contains multiple frame references to be processed together.
    """

    frames: tuple[FrameReference, ...]
    batch_id: str = ""

    def __post_init__(self) -> None:
        if not self.batch_id:
            object.__setattr__(self, "batch_id", f"batch-{uuid.uuid4().hex[:8]}")

    @property
    def size(self) -> int:
        return len(self.frames)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "frames": [f.to_dict() for f in self.frames],
            "size": self.size,
        }


@dataclass(frozen=True)
class TemporalFrameReference:
    """
    Reference to a temporal sequence of frames for video analysis models.

    Contains ordered frame references representing a video clip.
    """

    frames: tuple[FrameReference, ...]
    sequence_id: str = ""
    fps: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.sequence_id:
            object.__setattr__(self, "sequence_id", f"seq-{uuid.uuid4().hex[:8]}")

    @property
    def length(self) -> int:
        return len(self.frames)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence_id": self.sequence_id,
            "frames": [f.to_dict() for f in self.frames],
            "length": self.length,
            "fps": self.fps,
        }


# Type alias for any frame reference type
AnyFrameReference = Union[FrameReference, BatchFrameReference, TemporalFrameReference]


# =============================================================================
# INFERENCE REQUEST - Request structure for inference
# =============================================================================


@dataclass
class InferenceRequest:
    """
    Request for model inference.

    Contains all information needed to route and execute inference:
    - Target model and version
    - Frame reference(s)
    - Optional request metadata
    """

    # Target model
    model_id: str
    version: Optional[str] = None  # None = use latest ready version

    # Frame reference (single, batch, or temporal)
    frame_ref: Optional[AnyFrameReference] = None

    # Request metadata
    request_id: str = ""
    priority: int = 0  # Reserved for future use
    timeout_ms: Optional[int] = None  # Override model timeout

    # Caller context (for logging)
    caller_id: Optional[str] = None
    camera_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.request_id:
            self.request_id = f"req-{uuid.uuid4().hex[:12]}"

    @property
    def input_type(self) -> InputType:
        """Determine input type from frame reference."""
        if isinstance(self.frame_ref, TemporalFrameReference):
            return InputType.TEMPORAL
        if isinstance(self.frame_ref, BatchFrameReference):
            return InputType.BATCH
        return InputType.FRAME

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging."""
        result = {
            "request_id": self.request_id,
            "model_id": self.model_id,
            "version": self.version,
            "input_type": self.input_type.value,
            "priority": self.priority,
        }
        if self.frame_ref:
            result["frame_ref"] = self.frame_ref.to_dict()
        if self.caller_id:
            result["caller_id"] = self.caller_id
        if self.camera_id:
            result["camera_id"] = self.camera_id
        return result


# =============================================================================
# INFERENCE RESPONSE - Response structure from inference
# =============================================================================


class ResponseStatus(Enum):
    """Status of inference response."""

    SUCCESS = "success"
    ERROR = "error"
    MODEL_NOT_FOUND = "model_not_found"
    MODEL_NOT_READY = "model_not_ready"
    INVALID_REQUEST = "invalid_request"
    EXECUTION_FAILED = "execution_failed"
    TIMEOUT = "timeout"


@dataclass
class InferenceResponse:
    """
    Response from model inference.

    Contains either:
    - Successful inference output (opaque payload)
    - Error information (code + message only, no internals)

    The response intentionally does NOT expose:
    - Stack traces
    - Internal model state
    - Raw exception details
    """

    # Response status
    status: ResponseStatus
    success: bool

    # Request context
    request_id: str
    model_id: str
    version: str

    # Timing
    total_ms: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Success payload (opaque - pipeline does not interpret)
    output: Optional[dict[str, Any]] = None

    # Error information (no internals)
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    # Execution metadata (for observability)
    preprocess_ms: int = 0
    inference_ms: int = 0
    postprocess_ms: int = 0

    @classmethod
    def success_response(
        cls,
        request: InferenceRequest,
        version: str,
        output: dict[str, Any],
        execution_result: ExecutionResult,
    ) -> "InferenceResponse":
        """Create successful response."""
        return cls(
            status=ResponseStatus.SUCCESS,
            success=True,
            request_id=request.request_id,
            model_id=request.model_id,
            version=version,
            output=output,
            total_ms=execution_result.total_ms,
            preprocess_ms=execution_result.preprocess_ms,
            inference_ms=execution_result.inference_ms,
            postprocess_ms=execution_result.postprocess_ms,
        )

    @classmethod
    def error_response(
        cls,
        request: InferenceRequest,
        version: str,
        status: ResponseStatus,
        error_code: str,
        error_message: str,
        total_ms: int = 0,
    ) -> "InferenceResponse":
        """Create error response."""
        return cls(
            status=status,
            success=False,
            request_id=request.request_id,
            model_id=request.model_id,
            version=version or "unknown",
            error_code=error_code,
            error_message=error_message,
            total_ms=total_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        result = {
            "status": self.status.value,
            "success": self.success,
            "request_id": self.request_id,
            "model_id": self.model_id,
            "version": self.version,
            "timestamp": self.timestamp.isoformat(),
            "timing": {
                "total_ms": self.total_ms,
                "preprocess_ms": self.preprocess_ms,
                "inference_ms": self.inference_ms,
                "postprocess_ms": self.postprocess_ms,
            },
        }

        if self.success:
            result["output"] = self.output
        else:
            result["error"] = {
                "code": self.error_code,
                "message": self.error_message,
            }

        return result


# =============================================================================
# REQUEST VALIDATOR - Validates requests against model contracts
# =============================================================================


class RequestValidator:
    """
    Validates inference requests against model contracts.

    Performs early rejection of invalid requests before execution.
    """

    def validate_frame_reference(
        self,
        frame_ref: Optional[AnyFrameReference],
        request_id: str,
    ) -> Optional[PipelineError]:
        """
        Validate frame reference structure.

        Returns None if valid, PipelineError if invalid.
        """
        if frame_ref is None:
            return pipeline_error(
                code=ErrorCode.PIPE_INVALID_FRAME_REF,
                message="Frame reference is required",
                request_id=request_id,
            )

        if isinstance(frame_ref, FrameReference):
            return self._validate_single_frame(frame_ref, request_id)
        elif isinstance(frame_ref, BatchFrameReference):
            return self._validate_batch_frame(frame_ref, request_id)
        elif isinstance(frame_ref, TemporalFrameReference):
            return self._validate_temporal_frame(frame_ref, request_id)
        else:
            return pipeline_error(
                code=ErrorCode.PIPE_INVALID_FRAME_REF,
                message=f"Unknown frame reference type: {type(frame_ref).__name__}",
                request_id=request_id,
            )

    def _validate_single_frame(
        self,
        frame_ref: FrameReference,
        request_id: str,
    ) -> Optional[PipelineError]:
        """Validate single frame reference."""
        if not frame_ref.ref_id:
            return pipeline_error(
                code=ErrorCode.PIPE_INVALID_FRAME_REF,
                message="Frame reference missing ref_id",
                request_id=request_id,
            )
        if not frame_ref.camera_id:
            return pipeline_error(
                code=ErrorCode.PIPE_INVALID_FRAME_REF,
                message="Frame reference missing camera_id",
                request_id=request_id,
            )
        return None

    def _validate_batch_frame(
        self,
        batch_ref: BatchFrameReference,
        request_id: str,
    ) -> Optional[PipelineError]:
        """Validate batch frame reference."""
        if not batch_ref.frames:
            return pipeline_error(
                code=ErrorCode.PIPE_INVALID_FRAME_REF,
                message="Batch frame reference contains no frames",
                request_id=request_id,
            )

        for i, frame in enumerate(batch_ref.frames):
            error = self._validate_single_frame(frame, request_id)
            if error:
                error.context.details["frame_index"] = i
                return error

        return None

    def _validate_temporal_frame(
        self,
        temporal_ref: TemporalFrameReference,
        request_id: str,
    ) -> Optional[PipelineError]:
        """Validate temporal frame reference."""
        if not temporal_ref.frames:
            return pipeline_error(
                code=ErrorCode.PIPE_INVALID_FRAME_REF,
                message="Temporal frame reference contains no frames",
                request_id=request_id,
            )

        for i, frame in enumerate(temporal_ref.frames):
            error = self._validate_single_frame(frame, request_id)
            if error:
                error.context.details["frame_index"] = i
                return error

        return None

    def validate_input_type(
        self,
        request: InferenceRequest,
        descriptor: ModelVersionDescriptor,
    ) -> Optional[PipelineError]:
        """
        Validate request input type matches model contract.

        Returns None if valid, PipelineError if mismatch.
        """
        model_input_type = descriptor.input_spec.type
        request_input_type = request.input_type

        if model_input_type != request_input_type:
            return pipeline_error(
                code=ErrorCode.PIPE_INPUT_TYPE_MISMATCH,
                message=(
                    f"Model expects {model_input_type.value} input, "
                    f"got {request_input_type.value}"
                ),
                model_id=request.model_id,
                version=descriptor.version,
                request_id=request.request_id,
                expected_type=model_input_type.value,
                actual_type=request_input_type.value,
            )

        return None

    def validate_batch_size(
        self,
        request: InferenceRequest,
        descriptor: ModelVersionDescriptor,
    ) -> Optional[PipelineError]:
        """Validate batch size is within model limits."""
        if not isinstance(request.frame_ref, BatchFrameReference):
            return None

        batch_size = request.frame_ref.size
        input_spec = descriptor.input_spec

        if input_spec.batch_min_size and batch_size < input_spec.batch_min_size:
            return pipeline_error(
                code=ErrorCode.PIPE_BATCH_SIZE_INVALID,
                message=(
                    f"Batch size {batch_size} below minimum {input_spec.batch_min_size}"
                ),
                model_id=request.model_id,
                version=descriptor.version,
                request_id=request.request_id,
                batch_size=batch_size,
                min_size=input_spec.batch_min_size,
            )

        if input_spec.batch_max_size and batch_size > input_spec.batch_max_size:
            return pipeline_error(
                code=ErrorCode.PIPE_BATCH_SIZE_INVALID,
                message=(
                    f"Batch size {batch_size} exceeds maximum {input_spec.batch_max_size}"
                ),
                model_id=request.model_id,
                version=descriptor.version,
                request_id=request.request_id,
                batch_size=batch_size,
                max_size=input_spec.batch_max_size,
            )

        return None

    def validate_temporal_length(
        self,
        request: InferenceRequest,
        descriptor: ModelVersionDescriptor,
    ) -> Optional[PipelineError]:
        """Validate temporal sequence length is within model limits."""
        if not isinstance(request.frame_ref, TemporalFrameReference):
            return None

        seq_length = request.frame_ref.length
        input_spec = descriptor.input_spec

        if input_spec.temporal_min_frames and seq_length < input_spec.temporal_min_frames:
            return pipeline_error(
                code=ErrorCode.PIPE_TEMPORAL_LENGTH_INVALID,
                message=(
                    f"Sequence length {seq_length} below minimum "
                    f"{input_spec.temporal_min_frames}"
                ),
                model_id=request.model_id,
                version=descriptor.version,
                request_id=request.request_id,
                sequence_length=seq_length,
                min_length=input_spec.temporal_min_frames,
            )

        if input_spec.temporal_max_frames and seq_length > input_spec.temporal_max_frames:
            return pipeline_error(
                code=ErrorCode.PIPE_TEMPORAL_LENGTH_INVALID,
                message=(
                    f"Sequence length {seq_length} exceeds maximum "
                    f"{input_spec.temporal_max_frames}"
                ),
                model_id=request.model_id,
                version=descriptor.version,
                request_id=request.request_id,
                sequence_length=seq_length,
                max_length=input_spec.temporal_max_frames,
            )

        return None


# =============================================================================
# INFERENCE PIPELINE - Main pipeline implementation
# =============================================================================


class InferencePipeline:
    """
    Main inference pipeline for routing and executing model inference.

    This is the public API for inference requests. It:
    1. Validates incoming requests
    2. Resolves model + version to sandbox
    3. Checks model health
    4. Delegates execution to sandbox
    5. Returns opaque results

    Usage:
        pipeline = InferencePipeline(registry, sandbox_manager)

        request = InferenceRequest(
            model_id="fall_detection",
            frame_ref=FrameReference(
                ref_id="frame-123",
                camera_id="cam-1",
                timestamp="2024-01-01T00:00:00Z",
            ),
        )

        response = pipeline.infer(request)

        if response.success:
            output = response.output
        else:
            print(f"Error: {response.error_code}")
    """

    def __init__(
        self,
        registry: ModelRegistry,
        sandbox_manager: SandboxManager,
        validator: Optional[RequestValidator] = None,
        version_resolver: Optional[VersionResolver] = None,
        admission_controller: Optional[AdmissionController] = None,
        allow_degraded: bool = True,
        include_prerelease: bool = False,
    ):
        """
        Initialize the inference pipeline.

        Args:
            registry: Model registry for model/version lookup
            sandbox_manager: Manager for execution sandboxes
            validator: Request validator (created if not provided)
            version_resolver: Version resolver (created if not provided)
            admission_controller: Concurrency admission controller (optional)
            allow_degraded: Whether to allow inference on DEGRADED models
            include_prerelease: Whether to include prerelease versions in auto-resolution
        """
        self.registry = registry
        self.sandbox_manager = sandbox_manager
        self.validator = validator or RequestValidator()
        self.allow_degraded = allow_degraded
        self.include_prerelease = include_prerelease

        # Concurrency control (optional but recommended)
        self.admission_controller = admission_controller

        # Configure version eligibility based on settings
        acceptable_health = frozenset({HealthStatus.HEALTHY, HealthStatus.DEGRADED}) \
            if allow_degraded else frozenset({HealthStatus.HEALTHY})

        self._eligibility = EligibilityConfig(
            required_state=LoadState.READY,
            acceptable_health=acceptable_health,
            include_prerelease=include_prerelease,
        )

        # Create or use provided version resolver
        self.version_resolver = version_resolver or VersionResolver(
            registry=registry,
            default_eligibility=self._eligibility,
        )

        # Metrics
        self._request_count = 0
        self._success_count = 0
        self._error_count = 0
        self._rejected_count = 0
        self._lock = threading.Lock()

        logger.info(
            "Inference pipeline initialized",
            extra={
                "allow_degraded": allow_degraded,
                "include_prerelease": include_prerelease,
                "concurrency_enabled": admission_controller is not None,
            },
        )

    def infer(self, request: InferenceRequest) -> InferenceResponse:
        """
        Execute inference for a request.

        This is the main entry point for inference.

        Args:
            request: Inference request

        Returns:
            InferenceResponse with output or error
        """
        start_time = time.monotonic()

        log_context = {
            "request_id": request.request_id,
            "model_id": request.model_id,
            "version": request.version,
        }

        logger.debug("Processing inference request", extra=log_context)

        with self._lock:
            self._request_count += 1

        try:
            # Step 1: Validate frame reference
            frame_error = self.validator.validate_frame_reference(
                request.frame_ref,
                request.request_id,
            )
            if frame_error:
                return self._error_from_pipeline_error(request, frame_error, start_time)

            # Step 2: Resolve model and version
            descriptor, resolve_error = self._resolve_model_version(request)
            if resolve_error:
                return self._error_from_pipeline_error(request, resolve_error, start_time)

            version = descriptor.version

            # Step 3: Check model state and health
            state_error = self._check_model_state(request, descriptor)
            if state_error:
                return self._error_from_pipeline_error(request, state_error, start_time)

            # Step 4: Validate input against model contract
            contract_error = self._validate_against_contract(request, descriptor)
            if contract_error:
                return self._error_from_pipeline_error(request, contract_error, start_time)

            # Step 5: Acquire concurrency slot (if admission control enabled)
            slot: Optional[ConcurrencySlot] = None
            if self.admission_controller is not None:
                slot = self.admission_controller.try_acquire(
                    model_id=request.model_id,
                    version=version,
                    request_id=request.request_id,
                )
                if not slot.acquired:
                    with self._lock:
                        self._rejected_count += 1

                    logger.debug(
                        "Request rejected by admission control",
                        extra={
                            **log_context,
                            "version": version,
                            "rejection_reason": slot.rejection_reason.value if slot.rejection_reason else None,
                        },
                    )
                    return self._error_from_pipeline_error(
                        request, slot.rejection_error, start_time
                    )

            try:
                # Step 6: Get sandbox for execution
                sandbox = self.sandbox_manager.get_sandbox(request.model_id, version)
                if sandbox is None:
                    error = pipeline_error(
                        code=ErrorCode.PIPE_NO_SANDBOX,
                        message=f"No sandbox available for {request.model_id}:{version}",
                        model_id=request.model_id,
                        version=version,
                        request_id=request.request_id,
                    )
                    return self._error_from_pipeline_error(request, error, start_time)

                # Step 7: Execute inference through sandbox
                # Pass frame reference as input - model's preprocess handles actual retrieval
                execution_result = sandbox.execute(
                    frame=request.frame_ref,
                    request_id=request.request_id,
                )
            finally:
                # Always release slot after execution (if acquired)
                if slot is not None:
                    slot.release()

            # Step 8: Build response
            if execution_result.success:
                with self._lock:
                    self._success_count += 1

                response = InferenceResponse.success_response(
                    request=request,
                    version=version,
                    output=execution_result.output,
                    execution_result=execution_result,
                )

                logger.debug(
                    "Inference completed successfully",
                    extra={
                        **log_context,
                        "version": version,
                        "total_ms": execution_result.total_ms,
                    },
                )

                return response
            else:
                # Execution failed - map to response
                return self._error_from_execution_result(
                    request, version, execution_result, start_time
                )

        except Exception as e:
            # Catch-all for unexpected errors
            logger.error(
                "Unexpected pipeline error",
                extra={**log_context, "error": str(e)},
                exc_info=True,
            )

            with self._lock:
                self._error_count += 1

            total_ms = int((time.monotonic() - start_time) * 1000)
            return InferenceResponse.error_response(
                request=request,
                version=request.version or "unknown",
                status=ResponseStatus.ERROR,
                error_code=ErrorCode.PIPE_GENERIC_ERROR.value,
                error_message="Internal pipeline error",
                total_ms=total_ms,
            )

    def _resolve_model_version(
        self,
        request: InferenceRequest,
    ) -> tuple[Optional[ModelVersionDescriptor], Optional[PipelineError]]:
        """
        Resolve model and version from request using VersionResolver.

        Delegates to the VersionResolver for deterministic resolution:
        - Explicit version: validates existence, state, and health
        - No version: resolves to highest eligible stable version

        Returns:
            Tuple of (descriptor, error) - one will be None
        """
        # Use the version resolver for deterministic resolution
        result = self.version_resolver.resolve(
            model_id=request.model_id,
            version=request.version,
            eligibility=self._eligibility,
            request_id=request.request_id,
        )

        if result.success:
            logger.debug(
                "Version resolved",
                extra={
                    "model_id": request.model_id,
                    "requested_version": request.version,
                    "resolved_version": result.resolved_version,
                    "strategy": result.strategy.value if result.strategy else None,
                },
            )
            return result.descriptor, None
        else:
            return None, result.error

    def _check_model_state(
        self,
        request: InferenceRequest,
        descriptor: ModelVersionDescriptor,
    ) -> Optional[PipelineError]:
        """
        Check model state and health (defensive validation).

        Note: The VersionResolver already validates state and health during
        resolution. This method provides additional safety for edge cases
        where state might change between resolution and execution.

        Returns None if model is usable, PipelineError if not.
        """
        # Check load state
        if descriptor.state != LoadState.READY:
            return pipeline_error(
                code=ErrorCode.PIPE_VERSION_NOT_READY,
                message=(
                    f"Version {descriptor.qualified_id} is not ready "
                    f"(state: {descriptor.state.value})"
                ),
                model_id=request.model_id,
                version=descriptor.version,
                request_id=request.request_id,
                current_state=descriptor.state.value,
            )

        # Check health status
        if descriptor.health == HealthStatus.UNHEALTHY:
            return pipeline_error(
                code=ErrorCode.PIPE_VERSION_UNHEALTHY,
                message=f"Version {descriptor.qualified_id} is unhealthy",
                model_id=request.model_id,
                version=descriptor.version,
                request_id=request.request_id,
                health_status=descriptor.health.value,
            )

        # Check degraded (if not allowed)
        if descriptor.health == HealthStatus.DEGRADED and not self.allow_degraded:
            return pipeline_error(
                code=ErrorCode.PIPE_VERSION_UNHEALTHY,
                message=f"Version {descriptor.qualified_id} is degraded",
                model_id=request.model_id,
                version=descriptor.version,
                request_id=request.request_id,
                health_status=descriptor.health.value,
            )

        return None

    def _validate_against_contract(
        self,
        request: InferenceRequest,
        descriptor: ModelVersionDescriptor,
    ) -> Optional[PipelineError]:
        """
        Validate request against model contract.

        Returns None if valid, PipelineError if invalid.
        """
        # Check input type
        type_error = self.validator.validate_input_type(request, descriptor)
        if type_error:
            return type_error

        # Check batch size
        batch_error = self.validator.validate_batch_size(request, descriptor)
        if batch_error:
            return batch_error

        # Check temporal length
        temporal_error = self.validator.validate_temporal_length(request, descriptor)
        if temporal_error:
            return temporal_error

        return None

    def _error_from_pipeline_error(
        self,
        request: InferenceRequest,
        error: PipelineError,
        start_time: float,
    ) -> InferenceResponse:
        """Convert PipelineError to InferenceResponse."""
        with self._lock:
            self._error_count += 1

        total_ms = int((time.monotonic() - start_time) * 1000)

        # Map error code to response status
        status = self._map_error_to_status(error.code)

        logger.warning(
            "Pipeline error",
            extra={
                "request_id": request.request_id,
                "error_code": error.code.value,
                "error_message": error.message,
            },
        )

        return InferenceResponse.error_response(
            request=request,
            version=request.version or "unknown",
            status=status,
            error_code=error.code.value,
            error_message=error.message,
            total_ms=total_ms,
        )

    def _error_from_execution_result(
        self,
        request: InferenceRequest,
        version: str,
        result: ExecutionResult,
        start_time: float,
    ) -> InferenceResponse:
        """Convert failed ExecutionResult to InferenceResponse."""
        with self._lock:
            self._error_count += 1

        # Map execution error to response status
        if result.error:
            error_code = result.error.code.value
            # Sanitize error message (no internals)
            error_message = self._sanitize_error_message(result.error)
            status = self._map_error_to_status(result.error.code)
        else:
            error_code = ErrorCode.EXEC_GENERIC_ERROR.value
            error_message = "Execution failed"
            status = ResponseStatus.EXECUTION_FAILED

        logger.warning(
            "Execution failed",
            extra={
                "request_id": request.request_id,
                "model_id": request.model_id,
                "version": version,
                "error_code": error_code,
            },
        )

        return InferenceResponse.error_response(
            request=request,
            version=version,
            status=status,
            error_code=error_code,
            error_message=error_message,
            total_ms=result.total_ms,
        )

    def _map_error_to_status(self, code: ErrorCode) -> ResponseStatus:
        """Map error code to response status."""
        if code == ErrorCode.PIPE_MODEL_NOT_FOUND:
            return ResponseStatus.MODEL_NOT_FOUND
        if code == ErrorCode.PIPE_VERSION_NOT_FOUND:
            return ResponseStatus.MODEL_NOT_FOUND
        if code in (
            ErrorCode.PIPE_MODEL_NOT_READY,
            ErrorCode.PIPE_MODEL_UNHEALTHY,
            ErrorCode.PIPE_NO_SANDBOX,
        ):
            return ResponseStatus.MODEL_NOT_READY
        if code in (
            ErrorCode.PIPE_INVALID_FRAME_REF,
            ErrorCode.PIPE_INPUT_TYPE_MISMATCH,
            ErrorCode.PIPE_BATCH_SIZE_INVALID,
            ErrorCode.PIPE_TEMPORAL_LENGTH_INVALID,
            ErrorCode.PIPE_REQUEST_INVALID,
        ):
            return ResponseStatus.INVALID_REQUEST
        if code in (
            ErrorCode.EXEC_PREPROCESS_TIMEOUT,
            ErrorCode.EXEC_INFERENCE_TIMEOUT,
            ErrorCode.EXEC_POSTPROCESS_TIMEOUT,
        ):
            return ResponseStatus.TIMEOUT
        if code.value.startswith("EXEC_"):
            return ResponseStatus.EXECUTION_FAILED
        return ResponseStatus.ERROR

    def _sanitize_error_message(self, error: ModelError) -> str:
        """
        Sanitize error message for external response.

        Removes internal details, stack traces, file paths.
        """
        # Use the base message without cause details
        message = error.message

        # Remove any file path references
        import re
        message = re.sub(r"/[^\s]+\.py", "[internal]", message)
        message = re.sub(r"line \d+", "", message)

        # Truncate if too long
        if len(message) > 200:
            message = message[:197] + "..."

        return message

    # =========================================================================
    # Metrics and Status
    # =========================================================================

    @property
    def metrics(self) -> dict[str, Any]:
        """Get pipeline metrics."""
        with self._lock:
            metrics = {
                "total_requests": self._request_count,
                "successful": self._success_count,
                "errors": self._error_count,
                "rejected": self._rejected_count,
            }

        # Add concurrency stats if available
        if self.admission_controller is not None:
            concurrency_stats = self.admission_controller.manager.get_global_stats()
            metrics["concurrency"] = {
                "active": concurrency_stats["global_active"],
                "limit": concurrency_stats["global_limit"],
                "backpressure": concurrency_stats["backpressure"],
            }

        return metrics

    def get_available_models(self) -> list[dict[str, Any]]:
        """
        Get list of available models for inference.

        Returns models that have at least one READY version.
        """
        result = []
        for model in self.registry.get_all_models():
            ready_versions = model.ready_versions
            if ready_versions:
                result.append({
                    "model_id": model.model_id,
                    "versions": ready_versions,
                    "latest_version": max(ready_versions),
                })
        return result

    def get_model_health(
        self,
        model_id: str,
        version: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Get health status for a model version.

        Args:
            model_id: Model identifier
            version: Specific version (or None for latest)

        Returns:
            Health info dict or None if not found
        """
        model = self.registry.get_model(model_id)
        if model is None:
            return None

        if version:
            descriptor = model.get_version(version)
        else:
            ready = model.ready_versions
            if ready:
                descriptor = model.get_version(max(ready))
            else:
                return None

        if descriptor is None:
            return None

        sandbox = self.sandbox_manager.get_sandbox(model_id, descriptor.version)
        sandbox_metrics = sandbox.metrics if sandbox else None

        return {
            "model_id": model_id,
            "version": descriptor.version,
            "state": descriptor.state.value,
            "health": descriptor.health.value,
            "metrics": {
                "inference_count": descriptor.inference_count,
                "error_count": descriptor.error_count,
            },
            "sandbox_metrics": {
                "total_executions": sandbox_metrics.total_executions,
                "success_rate": f"{sandbox_metrics.success_rate:.1f}%",
                "consecutive_failures": sandbox_metrics.consecutive_failures,
            } if sandbox_metrics else None,
        }
