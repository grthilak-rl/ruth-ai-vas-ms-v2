"""
Ruth AI Runtime - Data Models

This module defines the core data structures used throughout the runtime
for representing models, their states, capabilities, and metadata.

All models are immutable where possible to ensure thread safety.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# =============================================================================
# PATTERNS - Naming validation patterns from directory standard
# =============================================================================

MODEL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[a-zA-Z0-9]+(\.[a-zA-Z0-9]+)*)?$"
)


def is_valid_model_id(model_id: str) -> bool:
    """Check if model_id matches the required pattern."""
    return bool(MODEL_ID_PATTERN.match(model_id))


def is_valid_version(version: str) -> bool:
    """Check if version matches SemVer pattern."""
    return bool(VERSION_PATTERN.match(version))


# =============================================================================
# ENUMS - State and status enumerations
# =============================================================================


class LoadState(Enum):
    """
    Model version lifecycle states.

    State Transitions:
        DISCOVERED -> VALIDATING -> LOADING -> READY
                   -> INVALID (terminal)
                              -> FAILED
                                        -> ERROR -> UNLOADING -> UNLOADED
                                                    UNLOADING -> UNLOADED
    """

    # Initial state when directory is found
    DISCOVERED = "discovered"

    # Contract validation in progress
    VALIDATING = "validating"

    # Contract valid, loading weights/code
    LOADING = "loading"

    # Model loaded and ready for inference
    READY = "ready"

    # Contract validation failed (terminal state for this version)
    INVALID = "invalid"

    # Loading failed (OOM, missing deps, etc.)
    FAILED = "failed"

    # Runtime error occurred during inference
    ERROR = "error"

    # Model being unloaded from memory
    UNLOADING = "unloading"

    # Model unloaded, directory may still exist
    UNLOADED = "unloaded"

    # Explicitly disabled by configuration
    DISABLED = "disabled"

    def is_terminal(self) -> bool:
        """Check if this is a terminal state that cannot transition."""
        return self in (LoadState.INVALID,)

    def is_available(self) -> bool:
        """Check if model is available for inference requests."""
        return self == LoadState.READY

    def is_loading_complete(self) -> bool:
        """Check if loading phase has completed (success or failure)."""
        return self in (
            LoadState.READY,
            LoadState.INVALID,
            LoadState.FAILED,
            LoadState.ERROR,
            LoadState.DISABLED,
        )


class HealthStatus(Enum):
    """
    Model health status for reporting.

    Health is independent of LoadState - a model can be READY but DEGRADED.
    """

    # Model operating normally
    HEALTHY = "healthy"

    # Model operational but with elevated errors or latency
    DEGRADED = "degraded"

    # Model not responding or in error state
    UNHEALTHY = "unhealthy"

    # Health status unknown (e.g., not yet loaded)
    UNKNOWN = "unknown"


class InputType(Enum):
    """Input data type supported by a model."""

    FRAME = "frame"  # Single image per inference
    BATCH = "batch"  # Multiple images per inference
    TEMPORAL = "temporal"  # Sequence of images (video clip)


class InputFormat(Enum):
    """Input data format."""

    JPEG = "jpeg"
    PNG = "png"
    RAW_RGB = "raw_rgb"
    RAW_BGR = "raw_bgr"
    RAW_GRAYSCALE = "raw_grayscale"


# =============================================================================
# DATA CLASSES - Model descriptors and specifications
# =============================================================================


@dataclass(frozen=True)
class HardwareCompatibility:
    """Hardware compatibility declaration from model.yaml."""

    supports_cpu: bool = True
    supports_gpu: bool = False
    supports_jetson: bool = False
    min_gpu_memory_mb: Optional[int] = None
    min_cpu_cores: Optional[int] = None
    min_ram_mb: Optional[int] = None

    def is_compatible_with(
        self,
        has_gpu: bool = False,
        is_jetson: bool = False,
        gpu_memory_mb: Optional[int] = None,
    ) -> bool:
        """Check if model is compatible with given hardware configuration."""
        # Must support at least one available hardware type
        if is_jetson and not self.supports_jetson:
            return False
        if has_gpu and not self.supports_gpu and not self.supports_cpu:
            return False
        if not has_gpu and not is_jetson and not self.supports_cpu:
            return False

        # Check GPU memory requirement if specified
        if self.min_gpu_memory_mb and gpu_memory_mb:
            if gpu_memory_mb < self.min_gpu_memory_mb:
                return False

        return True


@dataclass(frozen=True)
class PerformanceHints:
    """Performance hints from model.yaml."""

    inference_time_hint_ms: int = 100
    recommended_fps: int = 10
    max_fps: Optional[int] = None
    recommended_batch_size: int = 1
    warmup_iterations: int = 1


@dataclass(frozen=True)
class ResourceLimits:
    """Resource limits from model.yaml."""

    max_memory_mb: Optional[int] = None
    inference_timeout_ms: int = 5000
    preprocessing_timeout_ms: int = 1000
    postprocessing_timeout_ms: int = 1000
    max_concurrent_inferences: int = 1


@dataclass(frozen=True)
class InputSpecification:
    """Input specification from model.yaml."""

    type: InputType = InputType.FRAME
    format: InputFormat = InputFormat.JPEG
    min_width: int = 320
    min_height: int = 240
    max_width: Optional[int] = None
    max_height: Optional[int] = None
    channels: int = 3

    # Batch-specific settings
    batch_min_size: Optional[int] = None
    batch_max_size: Optional[int] = None
    batch_recommended_size: Optional[int] = None

    # Temporal-specific settings
    temporal_min_frames: Optional[int] = None
    temporal_max_frames: Optional[int] = None
    temporal_recommended_frames: Optional[int] = None
    temporal_fps_requirement: Optional[float] = None


@dataclass(frozen=True)
class OutputField:
    """Single field in output schema."""

    name: str
    type: str
    required: bool = True
    description: str = ""
    enum: Optional[tuple[str, ...]] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None


@dataclass(frozen=True)
class OutputSpecification:
    """Output specification from model.yaml."""

    schema_version: str = "1.0"
    event_type_enum: tuple[str, ...] = ("detected", "not_detected")
    provides_bounding_boxes: bool = False
    provides_metadata: bool = False
    metadata_allowed_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelCapabilities:
    """Aggregated capabilities declared by a model."""

    supports_batching: bool = False
    supports_async: bool = False
    provides_tracking: bool = False
    confidence_calibrated: bool = False
    provides_bounding_boxes: bool = False
    provides_keypoints: bool = False


@dataclass(frozen=True)
class EntryPoints:
    """Entry point file paths (relative to version directory)."""

    inference: str = "inference.py"
    preprocess: Optional[str] = None
    postprocess: Optional[str] = None
    loader: Optional[str] = None


@dataclass
class ModelVersionDescriptor:
    """
    Complete descriptor for a single model version.

    This is the primary data structure representing a model version
    in the registry. It includes both static contract information
    and dynamic state.
    """

    # Identity (immutable)
    model_id: str
    version: str
    display_name: str
    description: str = ""
    author: str = "unknown"
    contract_schema_version: str = "1.0.0"

    # Path information
    directory_path: Path = field(default_factory=lambda: Path("."))

    # Contract specifications
    input_spec: InputSpecification = field(default_factory=InputSpecification)
    output_spec: OutputSpecification = field(default_factory=OutputSpecification)
    hardware: HardwareCompatibility = field(default_factory=HardwareCompatibility)
    performance: PerformanceHints = field(default_factory=PerformanceHints)
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    entry_points: EntryPoints = field(default_factory=EntryPoints)

    # Dynamic state (mutable)
    state: LoadState = LoadState.DISCOVERED
    health: HealthStatus = HealthStatus.UNKNOWN
    last_state_change: datetime = field(default_factory=datetime.utcnow)
    last_error: Optional[str] = None
    last_error_code: Optional[str] = None

    # Runtime metrics (mutable)
    load_time_ms: Optional[int] = None
    inference_count: int = 0
    error_count: int = 0

    @property
    def qualified_id(self) -> str:
        """Return fully qualified identifier: model_id:version."""
        return f"{self.model_id}:{self.version}"

    @property
    def weights_path(self) -> Path:
        """Return path to weights directory."""
        return self.directory_path / "weights"

    @property
    def inference_path(self) -> Path:
        """Return path to inference entry point."""
        return self.directory_path / self.entry_points.inference

    def transition_to(
        self,
        new_state: LoadState,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> None:
        """
        Transition to a new state.

        Updates last_state_change timestamp and optionally records error.
        """
        self.state = new_state
        self.last_state_change = datetime.utcnow()
        if error:
            self.last_error = error
            self.last_error_code = error_code

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization/API responses."""
        return {
            "model_id": self.model_id,
            "version": self.version,
            "display_name": self.display_name,
            "description": self.description,
            "author": self.author,
            "state": self.state.value,
            "health": self.health.value,
            "directory_path": str(self.directory_path),
            "last_state_change": self.last_state_change.isoformat(),
            "last_error": self.last_error,
            "last_error_code": self.last_error_code,
            "input_type": self.input_spec.type.value,
            "hardware": {
                "supports_cpu": self.hardware.supports_cpu,
                "supports_gpu": self.hardware.supports_gpu,
                "supports_jetson": self.hardware.supports_jetson,
            },
            "performance": {
                "inference_time_hint_ms": self.performance.inference_time_hint_ms,
                "recommended_fps": self.performance.recommended_fps,
            },
            "metrics": {
                "load_time_ms": self.load_time_ms,
                "inference_count": self.inference_count,
                "error_count": self.error_count,
            },
        }


@dataclass
class ModelDescriptor:
    """
    Descriptor for a model (aggregates all versions).

    Used for model-level queries and to track all versions of a model.
    """

    model_id: str
    directory_path: Path
    versions: dict[str, ModelVersionDescriptor] = field(default_factory=dict)
    discovered_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def version_count(self) -> int:
        """Return number of discovered versions."""
        return len(self.versions)

    @property
    def ready_versions(self) -> list[str]:
        """Return list of versions in READY state."""
        return [
            v for v, desc in self.versions.items() if desc.state == LoadState.READY
        ]

    @property
    def latest_version(self) -> Optional[str]:
        """Return highest semantic version (not necessarily loaded)."""
        if not self.versions:
            return None
        return max(self.versions.keys(), key=_semver_key)

    def get_version(self, version: str) -> Optional[ModelVersionDescriptor]:
        """Get descriptor for a specific version."""
        return self.versions.get(version)

    def add_version(self, descriptor: ModelVersionDescriptor) -> None:
        """Add or update a version descriptor."""
        self.versions[descriptor.version] = descriptor

    def remove_version(self, version: str) -> Optional[ModelVersionDescriptor]:
        """Remove a version and return the removed descriptor."""
        return self.versions.pop(version, None)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization/API responses."""
        return {
            "model_id": self.model_id,
            "directory_path": str(self.directory_path),
            "version_count": self.version_count,
            "versions": list(self.versions.keys()),
            "ready_versions": self.ready_versions,
            "latest_version": self.latest_version,
            "discovered_at": self.discovered_at.isoformat(),
        }


def _semver_key(version: str) -> tuple[int, int, int, str]:
    """
    Generate a sortable key for semantic versions.

    Pre-release versions sort before their release counterpart.
    """
    # Split version and prerelease
    if "-" in version:
        main, prerelease = version.split("-", 1)
    else:
        main, prerelease = version, "~"  # ~ sorts after letters

    parts = main.split(".")
    major = int(parts[0]) if len(parts) > 0 else 0
    minor = int(parts[1]) if len(parts) > 1 else 0
    patch = int(parts[2]) if len(parts) > 2 else 0

    return (major, minor, patch, prerelease)
