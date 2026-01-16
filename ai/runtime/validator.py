"""
Ruth AI Runtime - Contract Validator

This module validates model.yaml contracts against the schema defined
in the Model Contract Specification (ai-model-contract.md).

Validation is performed in stages:
1. YAML parsing
2. Required field presence
3. Field type validation
4. Field value constraints
5. Conditional requirements
6. Directory-contract consistency
7. Entry point existence

All validation errors are collected to provide comprehensive feedback
rather than failing on the first error.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

import yaml

from ai.runtime.errors import (
    ContractError,
    ErrorCode,
    ValidationError,
    contract_error,
    validation_error,
)
from ai.runtime.models import (
    EntryPoints,
    HardwareCompatibility,
    InputFormat,
    InputSpecification,
    InputType,
    ModelCapabilities,
    ModelVersionDescriptor,
    OutputSpecification,
    PerformanceHints,
    ResourceLimits,
    is_valid_model_id,
    is_valid_version,
)

logger = logging.getLogger(__name__)

# Supported contract schema versions
SUPPORTED_SCHEMA_VERSIONS = {"1.0.0"}

# Required top-level fields
REQUIRED_FIELDS = {
    "model_id",
    "version",
    "display_name",
    "contract_schema_version",
    "input",
    "output",
    "hardware",
    "performance",
}

# Required nested fields
REQUIRED_INPUT_FIELDS = {"type", "format", "min_width", "min_height", "channels"}
REQUIRED_OUTPUT_FIELDS = {"schema_version", "schema"}
REQUIRED_HARDWARE_FIELDS = {"supports_cpu", "supports_gpu", "supports_jetson"}
REQUIRED_PERFORMANCE_FIELDS = {"inference_time_hint_ms", "recommended_fps"}


class ContractValidator:
    """
    Validates model.yaml contracts and builds ModelVersionDescriptor.

    Usage:
        validator = ContractValidator()
        result = validator.validate(version_path, expected_model_id, expected_version)

        if result.is_valid:
            descriptor = result.descriptor
        else:
            for error in result.errors:
                logger.error(error)
    """

    def __init__(self, strict: bool = True):
        """
        Initialize validator.

        Args:
            strict: If True, unknown fields cause warnings. If False, ignored.
        """
        self.strict = strict

    def validate(
        self,
        version_path: Path,
        expected_model_id: str,
        expected_version: str,
    ) -> ValidationResult:
        """
        Validate model contract and build descriptor.

        Args:
            version_path: Path to version directory (e.g., ai/models/fall_detection/1.0.0/)
            expected_model_id: Model ID from directory name
            expected_version: Version from directory name

        Returns:
            ValidationResult containing descriptor (if valid) and any errors
        """
        result = ValidationResult(model_id=expected_model_id, version=expected_version)

        # Stage 1: Load and parse YAML
        contract_path = version_path / "model.yaml"
        contract_data = self._parse_yaml(contract_path, result)
        if contract_data is None:
            return result

        # Stage 2: Validate required fields
        if not self._validate_required_fields(contract_data, contract_path, result):
            return result

        # Stage 3: Validate directory-contract consistency
        self._validate_consistency(
            contract_data, expected_model_id, expected_version, contract_path, result
        )

        # Stage 4: Validate schema version
        schema_version = contract_data.get("contract_schema_version", "1.0.0")
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            result.add_error(
                validation_error(
                    ErrorCode.VAL_UNSUPPORTED_SCHEMA_VERSION,
                    f"Unsupported contract schema version: {schema_version}",
                    model_id=expected_model_id,
                    version=expected_version,
                    path=contract_path,
                    field_name="contract_schema_version",
                    expected=str(SUPPORTED_SCHEMA_VERSIONS),
                    actual=schema_version,
                )
            )

        # Stage 5: Validate and parse sections
        input_spec = self._parse_input_spec(
            contract_data.get("input", {}), contract_path, result
        )
        output_spec = self._parse_output_spec(
            contract_data.get("output", {}), contract_path, result
        )
        hardware = self._parse_hardware(
            contract_data.get("hardware", {}), contract_path, result
        )
        performance = self._parse_performance(
            contract_data.get("performance", {}), contract_path, result
        )
        limits = self._parse_limits(contract_data.get("limits", {}))
        capabilities = self._parse_capabilities(contract_data.get("capabilities", {}))
        entry_points = self._parse_entry_points(contract_data.get("entry_points", {}))

        # Stage 6: Validate conditional requirements
        self._validate_conditional_requirements(
            contract_data, input_spec, contract_path, result
        )

        # Stage 7: Validate required files exist
        self._validate_required_files(
            version_path, entry_points, expected_model_id, expected_version, result
        )

        # Stage 8: Check for forbidden content
        self._validate_no_forbidden_content(
            version_path, expected_model_id, expected_version, result
        )

        # Build descriptor if valid
        if result.is_valid:
            result.descriptor = ModelVersionDescriptor(
                model_id=contract_data["model_id"],
                version=contract_data["version"],
                display_name=contract_data["display_name"],
                description=contract_data.get("description", ""),
                author=contract_data.get("author", "unknown"),
                contract_schema_version=schema_version,
                directory_path=version_path,
                input_spec=input_spec,
                output_spec=output_spec,
                hardware=hardware,
                performance=performance,
                limits=limits,
                capabilities=capabilities,
                entry_points=entry_points,
            )

        return result

    def _parse_yaml(
        self, contract_path: Path, result: ValidationResult
    ) -> Optional[dict[str, Any]]:
        """Parse model.yaml file."""
        if not contract_path.exists():
            result.add_error(
                validation_error(
                    ErrorCode.VAL_CONTRACT_NOT_FOUND,
                    f"model.yaml not found at {contract_path}",
                    model_id=result.model_id,
                    version=result.version,
                    path=contract_path,
                )
            )
            return None

        try:
            with open(contract_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if not isinstance(data, dict):
                    result.add_error(
                        contract_error(
                            ErrorCode.CONTRACT_PARSE_ERROR,
                            "model.yaml must contain a YAML mapping (dict)",
                            model_id=result.model_id,
                            version=result.version,
                            path=contract_path,
                        )
                    )
                    return None
                return data
        except yaml.YAMLError as e:
            result.add_error(
                contract_error(
                    ErrorCode.VAL_INVALID_YAML,
                    f"Invalid YAML syntax: {e}",
                    model_id=result.model_id,
                    version=result.version,
                    path=contract_path,
                    cause=e,
                )
            )
            return None

    def _validate_required_fields(
        self, data: dict[str, Any], path: Path, result: ValidationResult
    ) -> bool:
        """Validate all required top-level fields are present."""
        missing = REQUIRED_FIELDS - set(data.keys())
        if missing:
            for field in missing:
                result.add_error(
                    validation_error(
                        ErrorCode.VAL_MISSING_REQUIRED_FIELD,
                        f"Required field '{field}' is missing",
                        model_id=result.model_id,
                        version=result.version,
                        path=path,
                        field_name=field,
                    )
                )
            return False
        return True

    def _validate_consistency(
        self,
        data: dict[str, Any],
        expected_model_id: str,
        expected_version: str,
        path: Path,
        result: ValidationResult,
    ) -> None:
        """Validate directory names match contract values."""
        actual_model_id = data.get("model_id", "")
        actual_version = data.get("version", "")

        if actual_model_id != expected_model_id:
            result.add_error(
                validation_error(
                    ErrorCode.VAL_MODEL_ID_MISMATCH,
                    f"model_id in contract does not match directory name",
                    model_id=expected_model_id,
                    version=expected_version,
                    path=path,
                    field_name="model_id",
                    expected=expected_model_id,
                    actual=actual_model_id,
                )
            )

        if actual_version != expected_version:
            result.add_error(
                validation_error(
                    ErrorCode.VAL_VERSION_MISMATCH,
                    f"version in contract does not match directory name",
                    model_id=expected_model_id,
                    version=expected_version,
                    path=path,
                    field_name="version",
                    expected=expected_version,
                    actual=actual_version,
                )
            )

        # Validate model_id format
        if not is_valid_model_id(actual_model_id):
            result.add_error(
                validation_error(
                    ErrorCode.DISC_INVALID_MODEL_ID,
                    f"model_id '{actual_model_id}' does not match required pattern",
                    model_id=expected_model_id,
                    version=expected_version,
                    path=path,
                    field_name="model_id",
                    expected="^[a-z][a-z0-9_]{2,63}$",
                    actual=actual_model_id,
                )
            )

        # Validate version format
        if not is_valid_version(actual_version):
            result.add_error(
                validation_error(
                    ErrorCode.DISC_INVALID_VERSION,
                    f"version '{actual_version}' does not match SemVer pattern",
                    model_id=expected_model_id,
                    version=expected_version,
                    path=path,
                    field_name="version",
                    expected="X.Y.Z or X.Y.Z-prerelease",
                    actual=actual_version,
                )
            )

    def _parse_input_spec(
        self, data: dict[str, Any], path: Path, result: ValidationResult
    ) -> InputSpecification:
        """Parse and validate input specification."""
        # Check required fields
        missing = REQUIRED_INPUT_FIELDS - set(data.keys())
        for field in missing:
            result.add_error(
                validation_error(
                    ErrorCode.VAL_MISSING_REQUIRED_FIELD,
                    f"Required field 'input.{field}' is missing",
                    model_id=result.model_id,
                    version=result.version,
                    path=path,
                    field_name=f"input.{field}",
                )
            )

        # Parse input type
        input_type_str = data.get("type", "frame")
        try:
            input_type = InputType(input_type_str)
        except ValueError:
            result.add_error(
                validation_error(
                    ErrorCode.VAL_INVALID_INPUT_TYPE,
                    f"Invalid input type: {input_type_str}",
                    model_id=result.model_id,
                    version=result.version,
                    path=path,
                    field_name="input.type",
                    expected="frame, batch, or temporal",
                    actual=input_type_str,
                )
            )
            input_type = InputType.FRAME

        # Parse input format
        input_format_str = data.get("format", "jpeg")
        try:
            input_format = InputFormat(input_format_str)
        except ValueError:
            result.add_warning(
                f"Unknown input format '{input_format_str}', defaulting to jpeg"
            )
            input_format = InputFormat.JPEG

        # Parse batch settings if applicable
        batch_data = data.get("batch", {})
        temporal_data = data.get("temporal", {})

        return InputSpecification(
            type=input_type,
            format=input_format,
            min_width=data.get("min_width", 320),
            min_height=data.get("min_height", 240),
            max_width=data.get("max_width"),
            max_height=data.get("max_height"),
            channels=data.get("channels", 3),
            batch_min_size=batch_data.get("min_size"),
            batch_max_size=batch_data.get("max_size"),
            batch_recommended_size=batch_data.get("recommended_size"),
            temporal_min_frames=temporal_data.get("min_frames"),
            temporal_max_frames=temporal_data.get("max_frames"),
            temporal_recommended_frames=temporal_data.get("recommended_frames"),
            temporal_fps_requirement=temporal_data.get("fps_requirement"),
        )

    def _parse_output_spec(
        self, data: dict[str, Any], path: Path, result: ValidationResult
    ) -> OutputSpecification:
        """Parse and validate output specification."""
        missing = REQUIRED_OUTPUT_FIELDS - set(data.keys())
        for field in missing:
            result.add_error(
                validation_error(
                    ErrorCode.VAL_MISSING_REQUIRED_FIELD,
                    f"Required field 'output.{field}' is missing",
                    model_id=result.model_id,
                    version=result.version,
                    path=path,
                    field_name=f"output.{field}",
                )
            )

        schema = data.get("schema", {})
        event_type = schema.get("event_type", {})
        event_enum = event_type.get("enum", ["detected", "not_detected"])

        metadata = schema.get("metadata", {})
        metadata_keys = metadata.get("allowed_keys", [])

        return OutputSpecification(
            schema_version=data.get("schema_version", "1.0"),
            event_type_enum=tuple(event_enum),
            provides_bounding_boxes="bounding_boxes" in schema,
            provides_metadata="metadata" in schema,
            metadata_allowed_keys=tuple(metadata_keys),
        )

    def _parse_hardware(
        self, data: dict[str, Any], path: Path, result: ValidationResult
    ) -> HardwareCompatibility:
        """Parse and validate hardware compatibility."""
        missing = REQUIRED_HARDWARE_FIELDS - set(data.keys())
        for field in missing:
            result.add_error(
                validation_error(
                    ErrorCode.VAL_MISSING_REQUIRED_FIELD,
                    f"Required field 'hardware.{field}' is missing",
                    model_id=result.model_id,
                    version=result.version,
                    path=path,
                    field_name=f"hardware.{field}",
                )
            )

        return HardwareCompatibility(
            supports_cpu=data.get("supports_cpu", True),
            supports_gpu=data.get("supports_gpu", False),
            supports_jetson=data.get("supports_jetson", False),
            min_gpu_memory_mb=data.get("min_gpu_memory_mb"),
            min_cpu_cores=data.get("min_cpu_cores"),
            min_ram_mb=data.get("min_ram_mb"),
        )

    def _parse_performance(
        self, data: dict[str, Any], path: Path, result: ValidationResult
    ) -> PerformanceHints:
        """Parse and validate performance hints."""
        missing = REQUIRED_PERFORMANCE_FIELDS - set(data.keys())
        for field in missing:
            result.add_error(
                validation_error(
                    ErrorCode.VAL_MISSING_REQUIRED_FIELD,
                    f"Required field 'performance.{field}' is missing",
                    model_id=result.model_id,
                    version=result.version,
                    path=path,
                    field_name=f"performance.{field}",
                )
            )

        return PerformanceHints(
            inference_time_hint_ms=data.get("inference_time_hint_ms", 100),
            recommended_fps=data.get("recommended_fps", 10),
            max_fps=data.get("max_fps"),
            recommended_batch_size=data.get("recommended_batch_size", 1),
            warmup_iterations=data.get("warmup_iterations", 1),
        )

    def _parse_limits(self, data: dict[str, Any]) -> ResourceLimits:
        """Parse resource limits (all optional)."""
        return ResourceLimits(
            max_memory_mb=data.get("max_memory_mb"),
            inference_timeout_ms=data.get("inference_timeout_ms", 5000),
            preprocessing_timeout_ms=data.get("preprocessing_timeout_ms", 1000),
            postprocessing_timeout_ms=data.get("postprocessing_timeout_ms", 1000),
            max_concurrent_inferences=data.get("max_concurrent_inferences", 1),
        )

    def _parse_capabilities(self, data: dict[str, Any]) -> ModelCapabilities:
        """Parse model capabilities (all optional)."""
        return ModelCapabilities(
            supports_batching=data.get("supports_batching", False),
            supports_async=data.get("supports_async", False),
            provides_tracking=data.get("provides_tracking", False),
            confidence_calibrated=data.get("confidence_calibrated", False),
            provides_bounding_boxes=data.get("provides_bounding_boxes", False),
            provides_keypoints=data.get("provides_keypoints", False),
        )

    def _parse_entry_points(self, data: dict[str, Any]) -> EntryPoints:
        """Parse entry points (all have defaults)."""
        return EntryPoints(
            inference=data.get("inference", "inference.py"),
            preprocess=data.get("preprocess"),
            postprocess=data.get("postprocess"),
            loader=data.get("loader"),
        )

    def _validate_conditional_requirements(
        self,
        data: dict[str, Any],
        input_spec: InputSpecification,
        path: Path,
        result: ValidationResult,
    ) -> None:
        """Validate conditional requirements based on input type."""
        input_data = data.get("input", {})

        # Batch type requires batch settings
        if input_spec.type == InputType.BATCH:
            if "batch" not in input_data:
                result.add_error(
                    contract_error(
                        ErrorCode.CONTRACT_CONDITIONAL_ERROR,
                        "input.batch is required when input.type is 'batch'",
                        model_id=result.model_id,
                        version=result.version,
                        path=path,
                        field_name="input.batch",
                    )
                )

        # Temporal type requires temporal settings
        if input_spec.type == InputType.TEMPORAL:
            if "temporal" not in input_data:
                result.add_error(
                    contract_error(
                        ErrorCode.CONTRACT_CONDITIONAL_ERROR,
                        "input.temporal is required when input.type is 'temporal'",
                        model_id=result.model_id,
                        version=result.version,
                        path=path,
                        field_name="input.temporal",
                    )
                )

    def _validate_required_files(
        self,
        version_path: Path,
        entry_points: EntryPoints,
        model_id: str,
        version: str,
        result: ValidationResult,
    ) -> None:
        """Validate required files exist."""
        # Check weights directory
        weights_path = version_path / "weights"
        if not weights_path.exists():
            result.add_error(
                validation_error(
                    ErrorCode.VAL_REQUIRED_FILE_MISSING,
                    "Required directory 'weights/' not found",
                    model_id=model_id,
                    version=version,
                    path=weights_path,
                )
            )
        elif not weights_path.is_dir():
            result.add_error(
                validation_error(
                    ErrorCode.VAL_REQUIRED_FILE_MISSING,
                    "'weights' must be a directory",
                    model_id=model_id,
                    version=version,
                    path=weights_path,
                )
            )

        # Check inference entry point
        inference_path = version_path / entry_points.inference
        if not inference_path.exists():
            result.add_error(
                validation_error(
                    ErrorCode.VAL_REQUIRED_FILE_MISSING,
                    f"Required file '{entry_points.inference}' not found",
                    model_id=model_id,
                    version=version,
                    path=inference_path,
                )
            )

        # Check optional entry points if specified
        if entry_points.preprocess:
            preprocess_path = version_path / entry_points.preprocess
            if not preprocess_path.exists():
                result.add_error(
                    validation_error(
                        ErrorCode.VAL_REQUIRED_FILE_MISSING,
                        f"Declared preprocessing file '{entry_points.preprocess}' not found",
                        model_id=model_id,
                        version=version,
                        path=preprocess_path,
                    )
                )

        if entry_points.postprocess:
            postprocess_path = version_path / entry_points.postprocess
            if not postprocess_path.exists():
                result.add_error(
                    validation_error(
                        ErrorCode.VAL_REQUIRED_FILE_MISSING,
                        f"Declared postprocessing file '{entry_points.postprocess}' not found",
                        model_id=model_id,
                        version=version,
                        path=postprocess_path,
                    )
                )

    def _validate_no_forbidden_content(
        self,
        version_path: Path,
        model_id: str,
        version: str,
        result: ValidationResult,
    ) -> None:
        """Check for forbidden content in model directory."""
        forbidden_extensions = {".sh", ".bash", ".exe", ".dll", ".dylib"}

        for item in version_path.rglob("*"):
            # Skip weights directory for .so files (allowed for compiled models)
            if item.is_file():
                suffix = item.suffix.lower()
                if suffix in forbidden_extensions:
                    result.add_error(
                        validation_error(
                            ErrorCode.VAL_FORBIDDEN_CONTENT,
                            f"Forbidden file type detected: {item.name}",
                            model_id=model_id,
                            version=version,
                            path=item,
                            file_type=suffix,
                        )
                    )

            # Check symlinks
            if item.is_symlink():
                try:
                    target = item.resolve()
                    # Check if target is outside version directory
                    try:
                        target.relative_to(version_path)
                    except ValueError:
                        result.add_error(
                            validation_error(
                                ErrorCode.DISC_FORBIDDEN_SYMLINK,
                                f"Symlink points outside model directory: {item} -> {target}",
                                model_id=model_id,
                                version=version,
                                path=item,
                                target=str(target),
                            )
                        )
                except OSError:
                    # Broken symlink
                    result.add_warning(f"Broken symlink detected: {item}")


class ValidationResult:
    """
    Result of contract validation.

    Collects all errors and warnings encountered during validation.
    """

    def __init__(self, model_id: str, version: str):
        self.model_id = model_id
        self.version = version
        self.errors: list[ValidationError | ContractError] = []
        self.warnings: list[str] = []
        self.descriptor: Optional[ModelVersionDescriptor] = None

    @property
    def is_valid(self) -> bool:
        """Return True if no validation errors occurred."""
        return len(self.errors) == 0

    def add_error(self, error: ValidationError | ContractError) -> None:
        """Add a validation error."""
        self.errors.append(error)

    def add_warning(self, message: str) -> None:
        """Add a validation warning."""
        self.warnings.append(message)

    def __str__(self) -> str:
        if self.is_valid:
            return f"ValidationResult({self.model_id}:{self.version}) - VALID"
        return (
            f"ValidationResult({self.model_id}:{self.version}) - "
            f"INVALID ({len(self.errors)} errors, {len(self.warnings)} warnings)"
        )
