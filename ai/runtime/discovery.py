"""
Ruth AI Runtime - Discovery Scanner

This module handles filesystem scanning to discover model plugins
in the ai/models/ directory according to the directory standard.

The scanner is intentionally conservative:
- Invalid directories are skipped, not fatal errors
- Symlinks are validated for security
- Discovery errors are logged but don't stop scanning

Design Principles:
- Fail gracefully (skip invalid, continue scanning)
- Security-conscious (validate symlinks, forbidden content)
- Observable (emits discovery results for logging)
- Idempotent (can be run multiple times safely)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from ai.runtime.errors import (
    DiscoveryError,
    ErrorCode,
    discovery_error,
)
from ai.runtime.models import (
    LoadState,
    ModelDescriptor,
    ModelVersionDescriptor,
    is_valid_model_id,
    is_valid_version,
)
from ai.runtime.validator import ContractValidator, ValidationResult
from ai.runtime.registry import ModelRegistry

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class DiscoveryResult:
    """Result of a discovery scan."""

    # Counts
    models_found: int = 0
    versions_found: int = 0
    versions_valid: int = 0
    versions_invalid: int = 0

    # Detailed results
    discovered_models: list[ModelDescriptor] = field(default_factory=list)
    discovered_versions: list[ModelVersionDescriptor] = field(default_factory=list)
    errors: list[DiscoveryError] = field(default_factory=list)

    # Timing
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_ms: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for logging."""
        return {
            "models_found": self.models_found,
            "versions_found": self.versions_found,
            "versions_valid": self.versions_valid,
            "versions_invalid": self.versions_invalid,
            "error_count": len(self.errors),
            "duration_ms": self.duration_ms,
        }


# =============================================================================
# DISCOVERY SCANNER
# =============================================================================


class DiscoveryScanner:
    """
    Scans filesystem for model plugins according to directory standard.

    Expected directory structure:
        ai/models/
        ├── model_id_1/
        │   ├── 1.0.0/
        │   │   ├── model.yaml
        │   │   ├── inference.py
        │   │   └── weights/
        │   └── 1.1.0/
        │       └── ...
        └── model_id_2/
            └── ...

    Usage:
        scanner = DiscoveryScanner(models_root="/path/to/ai/models")
        result = scanner.scan()

        # Or scan directly into registry
        scanner.scan_into_registry(registry)
    """

    def __init__(
        self,
        models_root: Path | str,
        validator: Optional[ContractValidator] = None,
        follow_symlinks: bool = False,
        allowed_symlink_roots: Optional[list[Path]] = None,
    ):
        """
        Initialize the discovery scanner.

        Args:
            models_root: Root directory containing model directories
            validator: Contract validator (created if not provided)
            follow_symlinks: Whether to follow symlinks
            allowed_symlink_roots: Allowed target directories for symlinks
        """
        self.models_root = Path(models_root)
        self.validator = validator or ContractValidator()
        self.follow_symlinks = follow_symlinks
        self.allowed_symlink_roots = allowed_symlink_roots or []

    def scan(self) -> DiscoveryResult:
        """
        Scan the models directory and return discovery results.

        Returns:
            DiscoveryResult with all discovered models and versions
        """
        result = DiscoveryResult()
        start_time = datetime.utcnow()

        logger.info(
            "Starting model discovery scan",
            extra={"models_root": str(self.models_root)},
        )

        # Validate root directory
        root_error = self._validate_root()
        if root_error:
            result.errors.append(root_error)
            result.completed_at = datetime.utcnow()
            result.duration_ms = int(
                (result.completed_at - start_time).total_seconds() * 1000
            )
            return result

        # Scan for models
        for model_path in self._iter_model_dirs():
            model_id = model_path.name

            # Validate model_id
            if not is_valid_model_id(model_id):
                error = discovery_error(
                    code=ErrorCode.DISC_INVALID_MODEL_ID,
                    message=f"Invalid model_id: {model_id}",
                    model_id=model_id,
                    path=model_path,
                )
                result.errors.append(error)
                logger.warning(
                    "Skipping invalid model_id",
                    extra=error.to_log_dict(),
                )
                continue

            # Create model descriptor
            model = ModelDescriptor(
                model_id=model_id,
                directory_path=model_path,
            )
            result.models_found += 1

            # Scan for versions
            versions_found = False
            for version_path in self._iter_version_dirs(model_path):
                version = version_path.name

                # Validate version format
                if not is_valid_version(version):
                    error = discovery_error(
                        code=ErrorCode.DISC_INVALID_VERSION,
                        message=f"Invalid version format: {version}",
                        model_id=model_id,
                        version=version,
                        path=version_path,
                    )
                    result.errors.append(error)
                    logger.warning(
                        "Skipping invalid version",
                        extra=error.to_log_dict(),
                    )
                    continue

                result.versions_found += 1
                versions_found = True

                # Validate contract
                validation = self.validator.validate(
                    version_path=version_path,
                    expected_model_id=model_id,
                    expected_version=version,
                )

                if validation.is_valid:
                    descriptor = validation.descriptor
                    if descriptor:
                        model.add_version(descriptor)
                        result.discovered_versions.append(descriptor)
                        result.versions_valid += 1

                        logger.info(
                            "Version discovered and validated",
                            extra={
                                "model_id": model_id,
                                "version": version,
                                "display_name": descriptor.display_name,
                            },
                        )
                else:
                    # Create descriptor in INVALID state
                    descriptor = ModelVersionDescriptor(
                        model_id=model_id,
                        version=version,
                        display_name=f"{model_id} (invalid)",
                        directory_path=version_path,
                        state=LoadState.INVALID,
                        last_error="; ".join(
                            e.message for e in validation.errors[:3]
                        ),
                        last_error_code=(
                            validation.errors[0].code.value
                            if validation.errors
                            else None
                        ),
                    )
                    model.add_version(descriptor)
                    result.discovered_versions.append(descriptor)
                    result.versions_invalid += 1

                    logger.warning(
                        "Version discovered but invalid",
                        extra={
                            "model_id": model_id,
                            "version": version,
                            "errors": [e.message for e in validation.errors],
                        },
                    )

            # Check if any versions were found
            if not versions_found:
                error = discovery_error(
                    code=ErrorCode.DISC_NO_VERSIONS,
                    message=f"No valid version directories found for model: {model_id}",
                    model_id=model_id,
                    path=model_path,
                )
                result.errors.append(error)
                logger.warning(
                    "Model has no versions",
                    extra=error.to_log_dict(),
                )

            # Add model to results
            result.discovered_models.append(model)

        # Complete
        result.completed_at = datetime.utcnow()
        result.duration_ms = int(
            (result.completed_at - start_time).total_seconds() * 1000
        )

        logger.info(
            "Model discovery scan completed",
            extra=result.to_dict(),
        )

        return result

    def scan_into_registry(self, registry: ModelRegistry) -> DiscoveryResult:
        """
        Scan and register discovered models directly into registry.

        This is the primary method for initializing the registry
        at runtime startup.

        Args:
            registry: Registry to populate

        Returns:
            DiscoveryResult with scan statistics
        """
        result = self.scan()

        # Register all discovered models and versions
        for model in result.discovered_models:
            registry.register_model(model)

        logger.info(
            "Models registered into registry",
            extra={
                "models": result.models_found,
                "versions_valid": result.versions_valid,
                "versions_invalid": result.versions_invalid,
            },
        )

        return result

    def _validate_root(self) -> Optional[DiscoveryError]:
        """
        Validate the models root directory.

        Returns:
            DiscoveryError if invalid, None if valid
        """
        if not self.models_root.exists():
            return discovery_error(
                code=ErrorCode.DISC_ROOT_NOT_FOUND,
                message=f"Models root directory not found: {self.models_root}",
                path=self.models_root,
            )

        if not self.models_root.is_dir():
            return discovery_error(
                code=ErrorCode.DISC_ROOT_NOT_DIRECTORY,
                message=f"Models root is not a directory: {self.models_root}",
                path=self.models_root,
            )

        try:
            # Test read permission
            list(self.models_root.iterdir())
        except PermissionError as e:
            return discovery_error(
                code=ErrorCode.DISC_PERMISSION_DENIED,
                message=f"Permission denied reading models root: {self.models_root}",
                path=self.models_root,
                cause=e,
            )

        return None

    def _iter_model_dirs(self) -> Iterator[Path]:
        """
        Iterate over model directories in models_root.

        Yields directories that could be model roots (skips files).
        """
        try:
            for entry in sorted(self.models_root.iterdir()):
                # Skip files
                if not entry.is_dir():
                    continue

                # Skip hidden directories
                if entry.name.startswith("."):
                    continue

                # Skip common non-model directories
                if entry.name in ("__pycache__", "node_modules", ".git"):
                    continue

                # Validate symlinks if present
                if entry.is_symlink():
                    if not self.follow_symlinks:
                        logger.debug(
                            "Skipping symlink (follow_symlinks=False)",
                            extra={"path": str(entry)},
                        )
                        continue

                    if not self._is_valid_symlink(entry):
                        logger.warning(
                            "Skipping forbidden symlink",
                            extra={"path": str(entry)},
                        )
                        continue

                yield entry

        except PermissionError as e:
            logger.error(
                "Permission denied iterating models root",
                extra={"path": str(self.models_root), "error": str(e)},
            )

    def _iter_version_dirs(self, model_path: Path) -> Iterator[Path]:
        """
        Iterate over version directories within a model.

        Yields directories that could be version roots.
        """
        try:
            for entry in sorted(model_path.iterdir()):
                # Skip files
                if not entry.is_dir():
                    continue

                # Skip hidden directories
                if entry.name.startswith("."):
                    continue

                # Skip non-version directories
                if entry.name in ("__pycache__", "common", "shared"):
                    continue

                # Validate symlinks
                if entry.is_symlink():
                    if not self.follow_symlinks:
                        continue
                    if not self._is_valid_symlink(entry):
                        continue

                yield entry

        except PermissionError as e:
            logger.error(
                "Permission denied iterating model directory",
                extra={"path": str(model_path), "error": str(e)},
            )

    def _is_valid_symlink(self, path: Path) -> bool:
        """
        Validate that a symlink points to an allowed location.

        Security measure to prevent symlinks escaping the models directory.
        """
        try:
            target = path.resolve()
        except (OSError, RuntimeError):
            return False

        # If no allowed roots specified, only allow within models_root
        if not self.allowed_symlink_roots:
            allowed = [self.models_root.resolve()]
        else:
            allowed = [r.resolve() for r in self.allowed_symlink_roots]

        # Check if target is within any allowed root
        for allowed_root in allowed:
            try:
                target.relative_to(allowed_root)
                return True
            except ValueError:
                continue

        logger.warning(
            "Symlink points outside allowed directories",
            extra={
                "symlink": str(path),
                "target": str(target),
                "allowed_roots": [str(r) for r in allowed],
            },
        )

        return False


# =============================================================================
# WATCH MODE (OPTIONAL)
# =============================================================================


class DirectoryWatcher:
    """
    Optional filesystem watcher for hot-reloading models.

    This is a placeholder for future implementation.
    Production use would integrate with watchdog or inotify.
    """

    def __init__(
        self,
        scanner: DiscoveryScanner,
        registry: ModelRegistry,
        poll_interval_seconds: float = 30.0,
    ):
        """
        Initialize the directory watcher.

        Args:
            scanner: Scanner to use for re-scanning
            registry: Registry to update
            poll_interval_seconds: How often to check for changes
        """
        self.scanner = scanner
        self.registry = registry
        self.poll_interval_seconds = poll_interval_seconds
        self._running = False
        self._thread: Optional[object] = None

    def start(self) -> None:
        """Start watching for changes."""
        import threading

        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

        logger.info(
            "Directory watcher started",
            extra={
                "models_root": str(self.scanner.models_root),
                "poll_interval": self.poll_interval_seconds,
            },
        )

    def stop(self) -> None:
        """Stop watching."""
        self._running = False

        logger.info("Directory watcher stopped")

    def _watch_loop(self) -> None:
        """Main watch loop - polls for changes."""
        import time

        while self._running:
            time.sleep(self.poll_interval_seconds)

            if not self._running:
                break

            try:
                self._check_for_changes()
            except Exception as e:
                logger.error(
                    "Error checking for model changes",
                    extra={"error": str(e)},
                )

    def _check_for_changes(self) -> None:
        """
        Check for new, removed, or modified models.

        This is a simple implementation that re-scans everything.
        A production implementation would use proper file watching.
        """
        # Get current state
        current_versions = {
            v.qualified_id for v in self.registry.get_all_versions()
        }

        # Re-scan
        result = self.scanner.scan()

        # Find new versions
        discovered_ids = {
            v.qualified_id for v in result.discovered_versions
        }

        new_versions = discovered_ids - current_versions
        removed_versions = current_versions - discovered_ids

        # Register new versions
        for version in result.discovered_versions:
            if version.qualified_id in new_versions:
                self.registry.register_version(version)
                logger.info(
                    "New model version detected",
                    extra={
                        "model_id": version.model_id,
                        "version": version.version,
                    },
                )

        # Log removed (but don't auto-unregister - that requires explicit action)
        for qualified_id in removed_versions:
            model_id, version = qualified_id.split(":")
            logger.warning(
                "Model version directory removed",
                extra={
                    "model_id": model_id,
                    "version": version,
                },
            )
