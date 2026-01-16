"""
Ruth AI Runtime - Model Versioning & Routing

This module provides deterministic, explicit, and safe model version
resolution and routing logic.

Design Principles:
- Resolution is DETERMINISTIC (same input = same output)
- Resolution is TESTABLE in isolation
- Resolution does NOT depend on load order
- Resolution does NOT mutate registry state
- No implicit behavior or silent fallbacks

Version Resolution Rules:
1. If version is explicit → validate and return
2. If version is omitted:
   - Find highest SemVer version that is:
     • State = READY
     • Health = HEALTHY or DEGRADED (configurable)
   - Pre-release versions excluded by default
   - No "latest" alias in requests

Usage:
    resolver = VersionResolver(registry)

    # Explicit version
    result = resolver.resolve("fall_detection", "1.2.0")

    # Automatic (highest eligible)
    result = resolver.resolve("fall_detection")

    if result.success:
        descriptor = result.descriptor
    else:
        error = result.error
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from ai.runtime.errors import (
    ErrorCode,
    PipelineError,
    pipeline_error,
)
from ai.runtime.models import (
    HealthStatus,
    LoadState,
    ModelDescriptor,
    ModelVersionDescriptor,
)
from ai.runtime.registry import ModelRegistry

logger = logging.getLogger(__name__)


# =============================================================================
# SEMANTIC VERSIONING - Parsing and comparison
# =============================================================================


@dataclass(frozen=True, eq=False)
class SemVer:
    """
    Parsed semantic version for comparison.

    Implements SemVer 2.0.0 ordering rules:
    - Major.Minor.Patch compared numerically
    - Pre-release versions sort BEFORE release
    - Pre-release identifiers compared lexically/numerically
    """

    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: str = ""

    # Original string (not used in comparison)
    original: str = ""

    @property
    def is_prerelease(self) -> bool:
        """Check if this is a pre-release version."""
        return len(self.prerelease) > 0

    @property
    def is_stable(self) -> bool:
        """Check if this is a stable (non-prerelease) version."""
        return not self.is_prerelease

    def __str__(self) -> str:
        result = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            result += f"-{'.'.join(self.prerelease)}"
        if self.build:
            result += f"+{self.build}"
        return result

    def __eq__(self, other: object) -> bool:
        """Check equality based on SemVer identity (ignores build metadata)."""
        if not isinstance(other, SemVer):
            return NotImplemented
        return (
            self.major == other.major
            and self.minor == other.minor
            and self.patch == other.patch
            and self.prerelease == other.prerelease
        )

    def __hash__(self) -> int:
        """Hash based on SemVer identity (ignores build metadata)."""
        return hash((self.major, self.minor, self.patch, self.prerelease))

    def __lt__(self, other: "SemVer") -> bool:
        """
        Compare versions according to SemVer spec.

        Pre-release versions have lower precedence than normal versions.
        """
        if not isinstance(other, SemVer):
            return NotImplemented

        # Compare major.minor.patch
        self_tuple = (self.major, self.minor, self.patch)
        other_tuple = (other.major, other.minor, other.patch)

        if self_tuple != other_tuple:
            return self_tuple < other_tuple

        # Same base version - compare prerelease
        # A version without prerelease has HIGHER precedence
        if self.is_prerelease and not other.is_prerelease:
            return True
        if not self.is_prerelease and other.is_prerelease:
            return False
        if not self.is_prerelease and not other.is_prerelease:
            return False

        # Both have prerelease - compare identifiers
        return self._compare_prerelease(other) < 0

    def __le__(self, other: "SemVer") -> bool:
        """Less than or equal comparison."""
        if not isinstance(other, SemVer):
            return NotImplemented
        return self == other or self < other

    def __gt__(self, other: "SemVer") -> bool:
        """Greater than comparison."""
        if not isinstance(other, SemVer):
            return NotImplemented
        return not (self == other or self < other)

    def __ge__(self, other: "SemVer") -> bool:
        """Greater than or equal comparison."""
        if not isinstance(other, SemVer):
            return NotImplemented
        return not self < other

    def _compare_prerelease(self, other: "SemVer") -> int:
        """
        Compare prerelease identifiers.

        Returns: -1 if self < other, 0 if equal, 1 if self > other
        """
        for self_id, other_id in zip(self.prerelease, other.prerelease):
            # Numeric identifiers have lower precedence than alphanumeric
            self_numeric = self_id.isdigit()
            other_numeric = other_id.isdigit()

            if self_numeric and other_numeric:
                # Both numeric - compare as integers
                self_num = int(self_id)
                other_num = int(other_id)
                if self_num != other_num:
                    return -1 if self_num < other_num else 1
            elif self_numeric:
                # Numeric has lower precedence
                return -1
            elif other_numeric:
                return 1
            else:
                # Both alphanumeric - lexical comparison
                if self_id != other_id:
                    return -1 if self_id < other_id else 1

        # All compared identifiers equal - shorter has lower precedence
        if len(self.prerelease) != len(other.prerelease):
            return -1 if len(self.prerelease) < len(other.prerelease) else 1

        return 0


# SemVer regex pattern
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


def parse_semver(version: str) -> Optional[SemVer]:
    """
    Parse a version string into SemVer.

    Returns None if the version string is not valid SemVer.
    """
    match = SEMVER_PATTERN.match(version)
    if not match:
        return None

    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3))
    prerelease_str = match.group(4) or ""
    build = match.group(5) or ""

    prerelease = tuple(prerelease_str.split(".")) if prerelease_str else ()

    return SemVer(
        major=major,
        minor=minor,
        patch=patch,
        prerelease=prerelease,
        build=build,
        original=version,
    )


def compare_versions(v1: str, v2: str) -> int:
    """
    Compare two version strings.

    Returns:
        -1 if v1 < v2
        0 if v1 == v2
        1 if v1 > v2

    Raises:
        ValueError if either version is invalid
    """
    semver1 = parse_semver(v1)
    semver2 = parse_semver(v2)

    if semver1 is None:
        raise ValueError(f"Invalid version: {v1}")
    if semver2 is None:
        raise ValueError(f"Invalid version: {v2}")

    if semver1 < semver2:
        return -1
    if semver1 == semver2:
        return 0
    return 1


# =============================================================================
# RESOLUTION RESULT - Result of version resolution
# =============================================================================


class ResolutionStrategy(Enum):
    """How the version was resolved."""

    EXPLICIT = "explicit"  # Version was explicitly specified
    HIGHEST_STABLE = "highest_stable"  # Resolved to highest stable version
    HIGHEST_ANY = "highest_any"  # Resolved to highest including prerelease


@dataclass
class ResolutionResult:
    """
    Result of version resolution.

    Contains either a resolved descriptor or an error.
    """

    success: bool
    descriptor: Optional[ModelVersionDescriptor] = None
    error: Optional[PipelineError] = None
    strategy: Optional[ResolutionStrategy] = None

    # Resolution metadata
    model_id: str = ""
    requested_version: Optional[str] = None
    resolved_version: Optional[str] = None
    candidates_considered: int = 0
    candidates_eligible: int = 0

    @classmethod
    def resolved(
        cls,
        descriptor: ModelVersionDescriptor,
        strategy: ResolutionStrategy,
        requested_version: Optional[str] = None,
        candidates_considered: int = 0,
        candidates_eligible: int = 0,
    ) -> "ResolutionResult":
        """Create successful resolution result."""
        return cls(
            success=True,
            descriptor=descriptor,
            strategy=strategy,
            model_id=descriptor.model_id,
            requested_version=requested_version,
            resolved_version=descriptor.version,
            candidates_considered=candidates_considered,
            candidates_eligible=candidates_eligible,
        )

    @classmethod
    def failed(
        cls,
        error: PipelineError,
        model_id: str,
        requested_version: Optional[str] = None,
        candidates_considered: int = 0,
    ) -> "ResolutionResult":
        """Create failed resolution result."""
        return cls(
            success=False,
            error=error,
            model_id=model_id,
            requested_version=requested_version,
            candidates_considered=candidates_considered,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging."""
        result = {
            "success": self.success,
            "model_id": self.model_id,
            "requested_version": self.requested_version,
            "resolved_version": self.resolved_version,
            "strategy": self.strategy.value if self.strategy else None,
            "candidates_considered": self.candidates_considered,
            "candidates_eligible": self.candidates_eligible,
        }
        if self.error:
            result["error_code"] = self.error.code.value
        return result


# =============================================================================
# ELIGIBILITY FILTER - Defines which versions are eligible
# =============================================================================


@dataclass
class EligibilityConfig:
    """
    Configuration for version eligibility.

    Controls which versions are considered during resolution.
    """

    # Required load state (usually READY)
    required_state: LoadState = LoadState.READY

    # Acceptable health statuses
    acceptable_health: frozenset[HealthStatus] = frozenset({
        HealthStatus.HEALTHY,
        HealthStatus.DEGRADED,
    })

    # Whether to include pre-release versions
    include_prerelease: bool = False

    # Minimum version constraint (optional)
    min_version: Optional[str] = None

    # Maximum version constraint (optional)
    max_version: Optional[str] = None

    def is_eligible(self, descriptor: ModelVersionDescriptor) -> bool:
        """
        Check if a version descriptor is eligible.

        A version is eligible if it meets ALL constraints.
        """
        # Check load state
        if descriptor.state != self.required_state:
            return False

        # Check health status
        if descriptor.health not in self.acceptable_health:
            return False

        # Check prerelease constraint
        semver = parse_semver(descriptor.version)
        if semver and semver.is_prerelease and not self.include_prerelease:
            return False

        # Check minimum version
        if self.min_version and semver:
            min_semver = parse_semver(self.min_version)
            if min_semver and semver < min_semver:
                return False

        # Check maximum version
        if self.max_version and semver:
            max_semver = parse_semver(self.max_version)
            if max_semver and semver > max_semver:
                return False

        return True


# Default eligibility for production use
DEFAULT_ELIGIBILITY = EligibilityConfig()

# Strict eligibility - healthy only
STRICT_ELIGIBILITY = EligibilityConfig(
    acceptable_health=frozenset({HealthStatus.HEALTHY}),
)

# Permissive eligibility - includes prerelease
PERMISSIVE_ELIGIBILITY = EligibilityConfig(
    include_prerelease=True,
)


# =============================================================================
# VERSION RESOLVER - Main resolution logic
# =============================================================================


class VersionResolver:
    """
    Resolves model versions with deterministic, explicit rules.

    Resolution is:
    - Deterministic: same input = same output
    - Testable: no side effects
    - Read-only: does not mutate registry

    Usage:
        resolver = VersionResolver(registry)

        # Explicit version
        result = resolver.resolve("fall_detection", "1.2.0")

        # Automatic resolution
        result = resolver.resolve("fall_detection")

        # With custom eligibility
        result = resolver.resolve(
            "fall_detection",
            eligibility=STRICT_ELIGIBILITY,
        )
    """

    def __init__(
        self,
        registry: ModelRegistry,
        default_eligibility: EligibilityConfig = DEFAULT_ELIGIBILITY,
    ):
        """
        Initialize the version resolver.

        Args:
            registry: Model registry (read-only access)
            default_eligibility: Default eligibility configuration
        """
        self.registry = registry
        self.default_eligibility = default_eligibility

    def resolve(
        self,
        model_id: str,
        version: Optional[str] = None,
        eligibility: Optional[EligibilityConfig] = None,
        request_id: Optional[str] = None,
    ) -> ResolutionResult:
        """
        Resolve a model version.

        Args:
            model_id: Model identifier
            version: Explicit version (None = auto-resolve)
            eligibility: Eligibility constraints (uses default if not provided)
            request_id: Optional request ID for error context

        Returns:
            ResolutionResult with descriptor or error
        """
        eligibility = eligibility or self.default_eligibility

        logger.debug(
            "Resolving version",
            extra={
                "model_id": model_id,
                "requested_version": version,
                "include_prerelease": eligibility.include_prerelease,
            },
        )

        # Get model from registry
        model = self.registry.get_model(model_id)
        if model is None:
            error = pipeline_error(
                code=ErrorCode.PIPE_MODEL_NOT_FOUND,
                message=f"Model not found: {model_id}",
                model_id=model_id,
                request_id=request_id,
            )
            return ResolutionResult.failed(
                error=error,
                model_id=model_id,
                requested_version=version,
            )

        if version:
            # Explicit version requested
            return self._resolve_explicit(
                model=model,
                version=version,
                eligibility=eligibility,
                request_id=request_id,
            )
        else:
            # Auto-resolve to highest eligible
            return self._resolve_automatic(
                model=model,
                eligibility=eligibility,
                request_id=request_id,
            )

    def _resolve_explicit(
        self,
        model: ModelDescriptor,
        version: str,
        eligibility: EligibilityConfig,
        request_id: Optional[str],
    ) -> ResolutionResult:
        """
        Resolve an explicitly specified version.

        Validates that the version exists, is ready, and healthy.
        """
        model_id = model.model_id
        descriptor = model.get_version(version)

        if descriptor is None:
            error = pipeline_error(
                code=ErrorCode.PIPE_VERSION_NOT_FOUND,
                message=f"Version not found: {model_id}:{version}",
                model_id=model_id,
                version=version,
                request_id=request_id,
                available_versions=list(model.versions.keys()),
            )
            return ResolutionResult.failed(
                error=error,
                model_id=model_id,
                requested_version=version,
                candidates_considered=len(model.versions),
            )

        # Check load state
        if descriptor.state != eligibility.required_state:
            error = pipeline_error(
                code=ErrorCode.PIPE_VERSION_NOT_READY,
                message=(
                    f"Version {model_id}:{version} is not ready "
                    f"(state: {descriptor.state.value})"
                ),
                model_id=model_id,
                version=version,
                request_id=request_id,
                current_state=descriptor.state.value,
                required_state=eligibility.required_state.value,
            )
            return ResolutionResult.failed(
                error=error,
                model_id=model_id,
                requested_version=version,
                candidates_considered=1,
            )

        # Check health
        if descriptor.health not in eligibility.acceptable_health:
            error = pipeline_error(
                code=ErrorCode.PIPE_VERSION_UNHEALTHY,
                message=(
                    f"Version {model_id}:{version} is unhealthy "
                    f"(health: {descriptor.health.value})"
                ),
                model_id=model_id,
                version=version,
                request_id=request_id,
                current_health=descriptor.health.value,
                acceptable_health=[h.value for h in eligibility.acceptable_health],
            )
            return ResolutionResult.failed(
                error=error,
                model_id=model_id,
                requested_version=version,
                candidates_considered=1,
            )

        logger.debug(
            "Explicit version resolved",
            extra={
                "model_id": model_id,
                "version": version,
            },
        )

        return ResolutionResult.resolved(
            descriptor=descriptor,
            strategy=ResolutionStrategy.EXPLICIT,
            requested_version=version,
            candidates_considered=1,
            candidates_eligible=1,
        )

    def _resolve_automatic(
        self,
        model: ModelDescriptor,
        eligibility: EligibilityConfig,
        request_id: Optional[str],
    ) -> ResolutionResult:
        """
        Automatically resolve to the highest eligible version.

        Filters versions by eligibility and selects the highest SemVer.
        """
        model_id = model.model_id
        versions = model.versions

        if not versions:
            error = pipeline_error(
                code=ErrorCode.PIPE_NO_ELIGIBLE_VERSION,
                message=f"No versions available for model: {model_id}",
                model_id=model_id,
                request_id=request_id,
            )
            return ResolutionResult.failed(
                error=error,
                model_id=model_id,
                candidates_considered=0,
            )

        # Filter eligible versions
        eligible: list[tuple[SemVer, ModelVersionDescriptor]] = []

        for version_str, descriptor in versions.items():
            semver = parse_semver(version_str)
            if semver is None:
                # Skip invalid version strings
                logger.warning(
                    "Invalid version string, skipping",
                    extra={
                        "model_id": model_id,
                        "version": version_str,
                    },
                )
                continue

            if eligibility.is_eligible(descriptor):
                eligible.append((semver, descriptor))

        if not eligible:
            # Provide helpful error context
            states = {v.state.value for v in versions.values()}
            healths = {v.health.value for v in versions.values()}

            error = pipeline_error(
                code=ErrorCode.PIPE_NO_ELIGIBLE_VERSION,
                message=(
                    f"No eligible versions for model: {model_id}. "
                    f"Available states: {states}, healths: {healths}"
                ),
                model_id=model_id,
                request_id=request_id,
                available_versions=list(versions.keys()),
                available_states=list(states),
                available_healths=list(healths),
                required_state=eligibility.required_state.value,
                acceptable_health=[h.value for h in eligibility.acceptable_health],
                include_prerelease=eligibility.include_prerelease,
            )
            return ResolutionResult.failed(
                error=error,
                model_id=model_id,
                candidates_considered=len(versions),
            )

        # Sort by SemVer (highest first)
        eligible.sort(key=lambda x: x[0], reverse=True)

        # Select highest
        _, best_descriptor = eligible[0]

        strategy = (
            ResolutionStrategy.HIGHEST_ANY
            if eligibility.include_prerelease
            else ResolutionStrategy.HIGHEST_STABLE
        )

        logger.debug(
            "Automatic version resolved",
            extra={
                "model_id": model_id,
                "resolved_version": best_descriptor.version,
                "candidates_considered": len(versions),
                "candidates_eligible": len(eligible),
            },
        )

        return ResolutionResult.resolved(
            descriptor=best_descriptor,
            strategy=strategy,
            candidates_considered=len(versions),
            candidates_eligible=len(eligible),
        )

    def get_eligible_versions(
        self,
        model_id: str,
        eligibility: Optional[EligibilityConfig] = None,
    ) -> list[ModelVersionDescriptor]:
        """
        Get all eligible versions for a model, sorted by SemVer descending.

        Useful for listing available versions or debugging.
        """
        eligibility = eligibility or self.default_eligibility

        model = self.registry.get_model(model_id)
        if model is None:
            return []

        eligible: list[tuple[SemVer, ModelVersionDescriptor]] = []

        for version_str, descriptor in model.versions.items():
            semver = parse_semver(version_str)
            if semver and eligibility.is_eligible(descriptor):
                eligible.append((semver, descriptor))

        # Sort descending
        eligible.sort(key=lambda x: x[0], reverse=True)

        return [desc for _, desc in eligible]

    def get_version_status(
        self,
        model_id: str,
        version: str,
    ) -> Optional[dict[str, Any]]:
        """
        Get detailed status for a specific version.

        Returns None if model or version not found.
        """
        model = self.registry.get_model(model_id)
        if model is None:
            return None

        descriptor = model.get_version(version)
        if descriptor is None:
            return None

        semver = parse_semver(version)

        return {
            "model_id": model_id,
            "version": version,
            "state": descriptor.state.value,
            "health": descriptor.health.value,
            "is_prerelease": semver.is_prerelease if semver else None,
            "is_eligible_default": DEFAULT_ELIGIBILITY.is_eligible(descriptor),
            "is_eligible_strict": STRICT_ELIGIBILITY.is_eligible(descriptor),
            "last_state_change": descriptor.last_state_change.isoformat(),
            "inference_count": descriptor.inference_count,
            "error_count": descriptor.error_count,
        }


# =============================================================================
# VERSION LIFECYCLE MANAGER - State transitions
# =============================================================================


class VersionLifecycleManager:
    """
    Manages version lifecycle transitions.

    Provides safe operations for:
    - Marking versions ready/failed/unloaded
    - Enabling/disabling versions
    - Tracking state history
    """

    def __init__(self, registry: ModelRegistry):
        """
        Initialize the lifecycle manager.

        Args:
            registry: Model registry for state updates
        """
        self.registry = registry

    def mark_ready(
        self,
        model_id: str,
        version: str,
        load_time_ms: Optional[int] = None,
    ) -> bool:
        """
        Mark a version as READY after successful loading.

        Returns True if state was updated.
        """
        descriptor = self.registry.get_version(model_id, version)
        if descriptor is None:
            return False

        # Only transition from LOADING
        if descriptor.state != LoadState.LOADING:
            logger.warning(
                "Cannot mark ready from current state",
                extra={
                    "model_id": model_id,
                    "version": version,
                    "current_state": descriptor.state.value,
                },
            )
            return False

        success = self.registry.update_state(model_id, version, LoadState.READY)

        if success and load_time_ms is not None:
            descriptor.load_time_ms = load_time_ms

        return success

    def mark_failed(
        self,
        model_id: str,
        version: str,
        error: str,
        error_code: Optional[str] = None,
    ) -> bool:
        """
        Mark a version as FAILED after loading failure.

        Returns True if state was updated.
        """
        return self.registry.update_state(
            model_id,
            version,
            LoadState.FAILED,
            error=error,
            error_code=error_code,
        )

    def mark_unloading(self, model_id: str, version: str) -> bool:
        """
        Mark a version as UNLOADING before cleanup.

        Returns True if state was updated.
        """
        descriptor = self.registry.get_version(model_id, version)
        if descriptor is None:
            return False

        # Can unload from READY, ERROR, or FAILED
        if descriptor.state not in (LoadState.READY, LoadState.ERROR, LoadState.FAILED):
            logger.warning(
                "Cannot unload from current state",
                extra={
                    "model_id": model_id,
                    "version": version,
                    "current_state": descriptor.state.value,
                },
            )
            return False

        return self.registry.update_state(model_id, version, LoadState.UNLOADING)

    def mark_unloaded(self, model_id: str, version: str) -> bool:
        """
        Mark a version as UNLOADED after cleanup.

        Returns True if state was updated.
        """
        return self.registry.update_state(model_id, version, LoadState.UNLOADED)

    def mark_disabled(self, model_id: str, version: str, reason: str) -> bool:
        """
        Disable a version (cannot be used for inference).

        Returns True if state was updated.
        """
        return self.registry.update_state(
            model_id,
            version,
            LoadState.DISABLED,
            error=f"Disabled: {reason}",
        )

    def mark_error(
        self,
        model_id: str,
        version: str,
        error: str,
        error_code: Optional[str] = None,
    ) -> bool:
        """
        Mark a version as ERROR after runtime failure.

        Returns True if state was updated.
        """
        return self.registry.update_state(
            model_id,
            version,
            LoadState.ERROR,
            error=error,
            error_code=error_code,
        )

    def can_reload(self, model_id: str, version: str) -> bool:
        """
        Check if a version can be reloaded.

        A version can be reloaded if it's in FAILED, ERROR, or UNLOADED state.
        """
        descriptor = self.registry.get_version(model_id, version)
        if descriptor is None:
            return False

        return descriptor.state in (
            LoadState.FAILED,
            LoadState.ERROR,
            LoadState.UNLOADED,
        )

    def prepare_reload(self, model_id: str, version: str) -> bool:
        """
        Prepare a version for reloading by transitioning to DISCOVERED.

        Returns True if ready for reload.
        """
        if not self.can_reload(model_id, version):
            return False

        return self.registry.update_state(model_id, version, LoadState.DISCOVERED)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def highest_version(versions: list[str]) -> Optional[str]:
    """
    Get the highest version from a list of version strings.

    Invalid versions are ignored.
    """
    parsed = []
    for v in versions:
        semver = parse_semver(v)
        if semver:
            parsed.append((semver, v))

    if not parsed:
        return None

    parsed.sort(key=lambda x: x[0], reverse=True)
    return parsed[0][1]


def highest_stable_version(versions: list[str]) -> Optional[str]:
    """
    Get the highest stable (non-prerelease) version from a list.

    Invalid and prerelease versions are ignored.
    """
    parsed = []
    for v in versions:
        semver = parse_semver(v)
        if semver and semver.is_stable:
            parsed.append((semver, v))

    if not parsed:
        return None

    parsed.sort(key=lambda x: x[0], reverse=True)
    return parsed[0][1]


def is_version_compatible(
    version: str,
    min_version: Optional[str] = None,
    max_version: Optional[str] = None,
) -> bool:
    """
    Check if a version is within the specified range.

    Both bounds are inclusive.
    """
    semver = parse_semver(version)
    if semver is None:
        return False

    if min_version:
        min_semver = parse_semver(min_version)
        if min_semver and semver < min_semver:
            return False

    if max_version:
        max_semver = parse_semver(max_version)
        if max_semver and semver > max_semver:
            return False

    return True
