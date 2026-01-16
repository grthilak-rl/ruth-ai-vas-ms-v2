"""
Ruth AI Runtime - Model Loading and Registry Module

This package provides the core runtime infrastructure for discovering,
validating, loading, and managing AI models as opaque plugins.

Key components:
- ModelRegistry: In-memory registry of all discovered/loaded models
- ModelLoader: Validates and loads models from filesystem
- DiscoveryScanner: Scans ai/models/ directory for model plugins
- ContractValidator: Validates model.yaml contracts against schema

Design Principles:
- Model-agnostic: Runtime knows nothing about what models do
- Failure isolation: One model's failure cannot affect others
- Zero-disruption: Adding models requires no runtime changes
- Explicit contracts: All behavior is declared, never inferred

Usage:
    from ai.runtime import (
        DiscoveryScanner,
        ModelRegistry,
        ModelLoader,
        LoadState,
    )

    # Initialize components
    registry = ModelRegistry()
    scanner = DiscoveryScanner(models_root="ai/models")
    loader = ModelLoader()

    # Discover and register models
    result = scanner.scan_into_registry(registry)

    # Load ready models
    for version in registry.get_versions_by_state(LoadState.DISCOVERED):
        load_result = loader.load(version)
        if load_result.success:
            registry.update_state(
                version.model_id,
                version.version,
                LoadState.READY
            )
"""

from ai.runtime.models import (
    LoadState,
    HealthStatus,
    InputType,
    InputFormat,
    ModelDescriptor,
    ModelVersionDescriptor,
    ModelCapabilities,
    HardwareCompatibility,
    PerformanceHints,
    ResourceLimits,
    InputSpecification,
    OutputSpecification,
    OutputField,
    EntryPoints,
    is_valid_model_id,
    is_valid_version,
)
from ai.runtime.errors import (
    ModelError,
    DiscoveryError,
    ValidationError,
    LoadError,
    ContractError,
    ExecutionError,
    PipelineError,
    ErrorCode,
    ErrorContext,
    discovery_error,
    validation_error,
    load_error,
    contract_error,
    execution_error,
    pipeline_error,
)
from ai.runtime.registry import (
    ModelRegistry,
    RegistryEvent,
    RegistryEventType,
)
from ai.runtime.loader import (
    ModelLoader,
    LoadedModel,
    LoadResult,
)
from ai.runtime.discovery import (
    DiscoveryScanner,
    DiscoveryResult,
    DirectoryWatcher,
)
from ai.runtime.validator import (
    ContractValidator,
    ValidationResult,
)
from ai.runtime.sandbox import (
    ExecutionSandbox,
    SandboxManager,
    ExecutionResult,
    ExecutionMetrics,
    ExecutionStage,
    ExecutionOutcome,
    StageResult,
    HealthManager,
    TimeoutExecutor,
)
from ai.runtime.pipeline import (
    InferencePipeline,
    InferenceRequest,
    InferenceResponse,
    ResponseStatus,
    FrameReference,
    BatchFrameReference,
    TemporalFrameReference,
    RequestValidator,
)
from ai.runtime.versioning import (
    SemVer,
    parse_semver,
    compare_versions,
    highest_version,
    highest_stable_version,
    is_version_compatible,
    EligibilityConfig,
    DEFAULT_ELIGIBILITY,
    STRICT_ELIGIBILITY,
    PERMISSIVE_ELIGIBILITY,
    ResolutionStrategy,
    ResolutionResult,
    VersionResolver,
    VersionLifecycleManager,
)
from ai.runtime.reporting import (
    CapabilityPublisher,
    HealthAggregator,
    RuntimeCapacityTracker,
    HealthReporter,
    VersionCapability,
    ModelCapabilityReport,
    RuntimeCapacityReport,
    FullCapabilityReport,
    ModelStatus,
    PublishTrigger,
    NoOpBackendClient,
    create_reporting_stack,
)
from ai.runtime.concurrency import (
    ConcurrencyManager,
    AdmissionController,
    FairScheduler,
    ConcurrencySlot,
    ModelConcurrencyState,
    BackpressureLevel,
    RejectionReason,
    create_concurrency_stack,
)
from ai.runtime.recovery import (
    CircuitBreaker,
    CircuitBreakerState,
    CircuitState,
    RecoveryManager,
    RecoveryResult,
    FailurePolicy,
    FailureRecord,
    FailureType,
    DisablementReason,
    create_recovery_stack,
)

__all__ = [
    # Data models - Core
    "LoadState",
    "HealthStatus",
    "InputType",
    "InputFormat",
    "ModelDescriptor",
    "ModelVersionDescriptor",
    # Data models - Specifications
    "ModelCapabilities",
    "HardwareCompatibility",
    "PerformanceHints",
    "ResourceLimits",
    "InputSpecification",
    "OutputSpecification",
    "OutputField",
    "EntryPoints",
    # Data models - Validation helpers
    "is_valid_model_id",
    "is_valid_version",
    # Errors - Exceptions
    "ModelError",
    "DiscoveryError",
    "ValidationError",
    "LoadError",
    "ContractError",
    "ExecutionError",
    "PipelineError",
    "ErrorCode",
    "ErrorContext",
    # Errors - Factory functions
    "discovery_error",
    "validation_error",
    "load_error",
    "contract_error",
    "execution_error",
    "pipeline_error",
    # Registry
    "ModelRegistry",
    "RegistryEvent",
    "RegistryEventType",
    # Loader
    "ModelLoader",
    "LoadedModel",
    "LoadResult",
    # Discovery
    "DiscoveryScanner",
    "DiscoveryResult",
    "DirectoryWatcher",
    # Validator
    "ContractValidator",
    "ValidationResult",
    # Sandbox - Execution isolation
    "ExecutionSandbox",
    "SandboxManager",
    "ExecutionResult",
    "ExecutionMetrics",
    "ExecutionStage",
    "ExecutionOutcome",
    "StageResult",
    "HealthManager",
    "TimeoutExecutor",
    # Pipeline - Inference routing
    "InferencePipeline",
    "InferenceRequest",
    "InferenceResponse",
    "ResponseStatus",
    "FrameReference",
    "BatchFrameReference",
    "TemporalFrameReference",
    "RequestValidator",
    # Versioning - SemVer and resolution
    "SemVer",
    "parse_semver",
    "compare_versions",
    "highest_version",
    "highest_stable_version",
    "is_version_compatible",
    "EligibilityConfig",
    "DEFAULT_ELIGIBILITY",
    "STRICT_ELIGIBILITY",
    "PERMISSIVE_ELIGIBILITY",
    "ResolutionStrategy",
    "ResolutionResult",
    "VersionResolver",
    "VersionLifecycleManager",
    # Reporting - Health & Capability
    "CapabilityPublisher",
    "HealthAggregator",
    "RuntimeCapacityTracker",
    "HealthReporter",
    "VersionCapability",
    "ModelCapabilityReport",
    "RuntimeCapacityReport",
    "FullCapabilityReport",
    "ModelStatus",
    "PublishTrigger",
    "NoOpBackendClient",
    "create_reporting_stack",
    # Concurrency - Multi-model concurrency support
    "ConcurrencyManager",
    "AdmissionController",
    "FairScheduler",
    "ConcurrencySlot",
    "ModelConcurrencyState",
    "BackpressureLevel",
    "RejectionReason",
    "create_concurrency_stack",
    # Recovery - Failure isolation and recovery
    "CircuitBreaker",
    "CircuitBreakerState",
    "CircuitState",
    "RecoveryManager",
    "RecoveryResult",
    "FailurePolicy",
    "FailureRecord",
    "FailureType",
    "DisablementReason",
    "create_recovery_stack",
]

__version__ = "1.0.0"