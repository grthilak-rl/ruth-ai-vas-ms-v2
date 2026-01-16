"""
Ruth AI Runtime - Model Loader

This module handles the loading of validated models into memory.
It imports model code, loads weights, and performs warmup inferences.

The loader is intentionally separate from validation to maintain
clear separation of concerns:
- Validator: Checks if model CAN be loaded (contract compliance)
- Loader: Actually loads the model into memory

Design Principles:
- Fail-fast on import errors
- Capture all exceptions to prevent cascade failures
- Timeout protection for long-running loads
- Memory-aware loading with checks
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from ai.runtime.errors import (
    ErrorCode,
    LoadError,
    load_error,
)
from ai.runtime.models import (
    LoadState,
    ModelVersionDescriptor,
)

logger = logging.getLogger(__name__)


# =============================================================================
# PROTOCOLS - Define expected interfaces
# =============================================================================


class InferenceFunction(Protocol):
    """Protocol for the required infer() function."""

    def __call__(self, frame: Any, **kwargs: Any) -> dict[str, Any]: ...


class PreprocessFunction(Protocol):
    """Protocol for optional preprocess() function."""

    def __call__(self, raw_input: Any, **kwargs: Any) -> Any: ...


class PostprocessFunction(Protocol):
    """Protocol for optional postprocess() function."""

    def __call__(self, raw_output: dict[str, Any], **kwargs: Any) -> dict[str, Any]: ...


class LoaderFunction(Protocol):
    """Protocol for optional custom loader() function."""

    def __call__(self, weights_path: Path, **kwargs: Any) -> Any: ...


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class LoadedModel:
    """
    Container for a loaded model's callable functions.

    This is what the runtime uses to invoke the model.
    """

    model_id: str
    version: str
    infer: InferenceFunction
    preprocess: Optional[PreprocessFunction] = None
    postprocess: Optional[PostprocessFunction] = None
    model_instance: Any = None  # For models that need persistent state
    load_time_ms: int = 0

    def __repr__(self) -> str:
        return f"LoadedModel({self.model_id}:{self.version})"


@dataclass
class LoadResult:
    """Result of a model load attempt."""

    success: bool
    loaded_model: Optional[LoadedModel] = None
    error: Optional[LoadError] = None
    load_time_ms: int = 0

    @classmethod
    def ok(cls, model: LoadedModel, load_time_ms: int) -> "LoadResult":
        """Create successful result."""
        return cls(success=True, loaded_model=model, load_time_ms=load_time_ms)

    @classmethod
    def fail(cls, error: LoadError) -> "LoadResult":
        """Create failed result."""
        return cls(success=False, error=error)


# =============================================================================
# MODEL LOADER
# =============================================================================


class ModelLoader:
    """
    Loads validated models into memory.

    The loader imports Python modules, locates required functions,
    optionally loads weights, and performs warmup inferences.

    Usage:
        loader = ModelLoader()
        result = loader.load(descriptor)
        if result.success:
            model = result.loaded_model
            output = model.infer(frame)
    """

    def __init__(
        self,
        load_timeout_ms: int = 60000,
        warmup_enabled: bool = True,
        warmup_timeout_ms: int = 30000,
    ):
        """
        Initialize the model loader.

        Args:
            load_timeout_ms: Maximum time for loading (default 60s)
            warmup_enabled: Whether to run warmup inference after loading
            warmup_timeout_ms: Maximum time for warmup (default 30s)
        """
        self.load_timeout_ms = load_timeout_ms
        self.warmup_enabled = warmup_enabled
        self.warmup_timeout_ms = warmup_timeout_ms

        # Track loaded modules for cleanup
        self._loaded_modules: dict[str, list[str]] = {}

    def load(self, descriptor: ModelVersionDescriptor) -> LoadResult:
        """
        Load a model from its descriptor.

        This is the main entry point for loading models.

        Args:
            descriptor: Validated model version descriptor

        Returns:
            LoadResult with loaded model or error
        """
        start_time = time.monotonic()
        model_id = descriptor.model_id
        version = descriptor.version
        qualified_id = descriptor.qualified_id

        logger.info(
            "Loading model",
            extra={
                "model_id": model_id,
                "version": version,
                "path": str(descriptor.directory_path),
            },
        )

        try:
            # Step 1: Import inference module
            infer_func = self._import_inference(descriptor)

            # Step 2: Import optional preprocessing
            preprocess_func = self._import_preprocess(descriptor)

            # Step 3: Import optional postprocessing
            postprocess_func = self._import_postprocess(descriptor)

            # Step 4: Load model instance if custom loader exists
            model_instance = self._load_model_instance(descriptor)

            # Calculate load time
            load_time_ms = int((time.monotonic() - start_time) * 1000)

            # Create loaded model container
            loaded = LoadedModel(
                model_id=model_id,
                version=version,
                infer=infer_func,
                preprocess=preprocess_func,
                postprocess=postprocess_func,
                model_instance=model_instance,
                load_time_ms=load_time_ms,
            )

            # Step 5: Warmup if enabled
            if self.warmup_enabled:
                warmup_error = self._run_warmup(loaded, descriptor)
                if warmup_error:
                    return LoadResult.fail(warmup_error)

            total_time_ms = int((time.monotonic() - start_time) * 1000)

            logger.info(
                "Model loaded successfully",
                extra={
                    "model_id": model_id,
                    "version": version,
                    "load_time_ms": total_time_ms,
                },
            )

            return LoadResult.ok(loaded, total_time_ms)

        except LoadError as e:
            logger.error(
                "Model load failed",
                extra=e.to_log_dict(),
            )
            return LoadResult.fail(e)

        except Exception as e:
            error = load_error(
                code=ErrorCode.LOAD_GENERIC_ERROR,
                message=f"Unexpected error during load: {e}",
                model_id=model_id,
                version=version,
                path=descriptor.directory_path,
                cause=e,
                traceback=traceback.format_exc(),
            )
            logger.error(
                "Model load failed with unexpected error",
                extra=error.to_log_dict(),
            )
            return LoadResult.fail(error)

    def unload(self, model_id: str, version: str) -> bool:
        """
        Unload a model and clean up its modules.

        Args:
            model_id: Model identifier
            version: Model version

        Returns:
            True if unloaded successfully
        """
        qualified_id = f"{model_id}:{version}"

        if qualified_id not in self._loaded_modules:
            logger.warning(
                "Model not found for unload",
                extra={"model_id": model_id, "version": version},
            )
            return False

        # Remove imported modules from sys.modules
        module_names = self._loaded_modules.pop(qualified_id, [])
        for module_name in module_names:
            if module_name in sys.modules:
                del sys.modules[module_name]

        logger.info(
            "Model unloaded",
            extra={
                "model_id": model_id,
                "version": version,
                "modules_removed": len(module_names),
            },
        )

        return True

    def _import_inference(
        self, descriptor: ModelVersionDescriptor
    ) -> InferenceFunction:
        """
        Import the inference module and extract infer() function.

        Raises:
            LoadError: If import fails or infer() not found
        """
        inference_path = descriptor.inference_path

        if not inference_path.exists():
            raise load_error(
                code=ErrorCode.LOAD_IMPORT_FAILED,
                message=f"Inference module not found: {inference_path}",
                model_id=descriptor.model_id,
                version=descriptor.version,
                path=inference_path,
            )

        try:
            module = self._import_module(
                descriptor, inference_path, "inference"
            )
        except SyntaxError as e:
            raise load_error(
                code=ErrorCode.LOAD_SYNTAX_ERROR,
                message=f"Syntax error in inference module: {e}",
                model_id=descriptor.model_id,
                version=descriptor.version,
                path=inference_path,
                cause=e,
                line=e.lineno,
                offset=e.offset,
            )
        except ImportError as e:
            raise load_error(
                code=ErrorCode.LOAD_MISSING_DEPENDENCY,
                message=f"Missing dependency in inference module: {e}",
                model_id=descriptor.model_id,
                version=descriptor.version,
                path=inference_path,
                cause=e,
            )
        except Exception as e:
            raise load_error(
                code=ErrorCode.LOAD_IMPORT_FAILED,
                message=f"Failed to import inference module: {e}",
                model_id=descriptor.model_id,
                version=descriptor.version,
                path=inference_path,
                cause=e,
            )

        # Extract infer() function
        if not hasattr(module, "infer"):
            raise load_error(
                code=ErrorCode.LOAD_INFER_NOT_FOUND,
                message="infer() function not found in inference module",
                model_id=descriptor.model_id,
                version=descriptor.version,
                path=inference_path,
            )

        infer_func = getattr(module, "infer")
        if not callable(infer_func):
            raise load_error(
                code=ErrorCode.LOAD_INFER_NOT_FOUND,
                message="infer attribute exists but is not callable",
                model_id=descriptor.model_id,
                version=descriptor.version,
                path=inference_path,
            )

        return infer_func

    def _import_preprocess(
        self, descriptor: ModelVersionDescriptor
    ) -> Optional[PreprocessFunction]:
        """
        Import optional preprocessing module.

        Returns None if no preprocessing.py exists.
        Raises LoadError if module exists but preprocess() not found.
        """
        if not descriptor.entry_points.preprocess:
            return None

        preprocess_path = descriptor.directory_path / descriptor.entry_points.preprocess

        if not preprocess_path.exists():
            # Optional file doesn't exist - that's fine
            return None

        try:
            module = self._import_module(
                descriptor, preprocess_path, "preprocess"
            )
        except Exception as e:
            raise load_error(
                code=ErrorCode.LOAD_IMPORT_FAILED,
                message=f"Failed to import preprocessing module: {e}",
                model_id=descriptor.model_id,
                version=descriptor.version,
                path=preprocess_path,
                cause=e,
            )

        if not hasattr(module, "preprocess"):
            raise load_error(
                code=ErrorCode.LOAD_PREPROCESS_NOT_FOUND,
                message="preprocess() function not found in preprocessing module",
                model_id=descriptor.model_id,
                version=descriptor.version,
                path=preprocess_path,
            )

        return getattr(module, "preprocess")

    def _import_postprocess(
        self, descriptor: ModelVersionDescriptor
    ) -> Optional[PostprocessFunction]:
        """
        Import optional postprocessing module.

        Returns None if no postprocessing.py exists.
        Raises LoadError if module exists but postprocess() not found.
        """
        if not descriptor.entry_points.postprocess:
            return None

        postprocess_path = (
            descriptor.directory_path / descriptor.entry_points.postprocess
        )

        if not postprocess_path.exists():
            return None

        try:
            module = self._import_module(
                descriptor, postprocess_path, "postprocess"
            )
        except Exception as e:
            raise load_error(
                code=ErrorCode.LOAD_IMPORT_FAILED,
                message=f"Failed to import postprocessing module: {e}",
                model_id=descriptor.model_id,
                version=descriptor.version,
                path=postprocess_path,
                cause=e,
            )

        if not hasattr(module, "postprocess"):
            raise load_error(
                code=ErrorCode.LOAD_POSTPROCESS_NOT_FOUND,
                message="postprocess() function not found in postprocessing module",
                model_id=descriptor.model_id,
                version=descriptor.version,
                path=postprocess_path,
            )

        return getattr(module, "postprocess")

    def _load_model_instance(
        self, descriptor: ModelVersionDescriptor
    ) -> Optional[Any]:
        """
        Load model instance using custom loader if provided.

        Some models need to load weights into a persistent object
        that is passed to infer() calls. This method handles that case.
        """
        if not descriptor.entry_points.loader:
            return None

        loader_path = descriptor.directory_path / descriptor.entry_points.loader

        if not loader_path.exists():
            return None

        try:
            module = self._import_module(
                descriptor, loader_path, "loader"
            )
        except Exception as e:
            raise load_error(
                code=ErrorCode.LOAD_WEIGHTS_FAILED,
                message=f"Failed to import loader module: {e}",
                model_id=descriptor.model_id,
                version=descriptor.version,
                path=loader_path,
                cause=e,
            )

        if not hasattr(module, "load"):
            logger.warning(
                "loader.py exists but load() function not found",
                extra={
                    "model_id": descriptor.model_id,
                    "version": descriptor.version,
                },
            )
            return None

        load_func = getattr(module, "load")

        try:
            # Call the loader with weights path
            model_instance = load_func(descriptor.weights_path)
            return model_instance
        except MemoryError as e:
            raise load_error(
                code=ErrorCode.LOAD_OUT_OF_MEMORY,
                message="Out of memory while loading model weights",
                model_id=descriptor.model_id,
                version=descriptor.version,
                path=descriptor.weights_path,
                cause=e,
            )
        except Exception as e:
            raise load_error(
                code=ErrorCode.LOAD_WEIGHTS_FAILED,
                message=f"Failed to load model weights: {e}",
                model_id=descriptor.model_id,
                version=descriptor.version,
                path=descriptor.weights_path,
                cause=e,
            )

    def _import_module(
        self,
        descriptor: ModelVersionDescriptor,
        path: Path,
        module_type: str,
    ) -> Any:
        """
        Import a Python module from file path.

        Uses importlib to load modules without affecting the global
        namespace. Tracks loaded modules for later cleanup.
        """
        qualified_id = descriptor.qualified_id

        # Create unique module name to avoid conflicts
        module_name = f"ruth_model_{descriptor.model_id}_{descriptor.version}_{module_type}"

        # Track for cleanup
        if qualified_id not in self._loaded_modules:
            self._loaded_modules[qualified_id] = []
        self._loaded_modules[qualified_id].append(module_name)

        # Load module from file
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        # Add model directory to path temporarily for relative imports
        model_dir = str(descriptor.directory_path)
        sys.path.insert(0, model_dir)

        try:
            spec.loader.exec_module(module)
        finally:
            # Remove from path
            if model_dir in sys.path:
                sys.path.remove(model_dir)

        return module

    def _run_warmup(
        self,
        loaded: LoadedModel,
        descriptor: ModelVersionDescriptor,
    ) -> Optional[LoadError]:
        """
        Run warmup inference to ensure model is ready.

        Returns None on success, LoadError on failure.
        """
        warmup_iterations = descriptor.performance.warmup_iterations

        if warmup_iterations <= 0:
            return None

        logger.debug(
            "Running warmup inference",
            extra={
                "model_id": loaded.model_id,
                "version": loaded.version,
                "iterations": warmup_iterations,
            },
        )

        # Create dummy input for warmup
        # Models should handle warmup gracefully with any valid input
        import numpy as np

        dummy_frame = np.zeros(
            (
                descriptor.input_spec.min_height,
                descriptor.input_spec.min_width,
                descriptor.input_spec.channels,
            ),
            dtype=np.uint8,
        )

        try:
            for i in range(warmup_iterations):
                # Apply preprocessing if available
                processed = dummy_frame
                if loaded.preprocess:
                    processed = loaded.preprocess(dummy_frame)

                # Run inference
                if loaded.model_instance is not None:
                    result = loaded.infer(processed, model=loaded.model_instance)
                else:
                    result = loaded.infer(processed)

                # Apply postprocessing if available
                if loaded.postprocess:
                    loaded.postprocess(result)

            logger.debug(
                "Warmup completed successfully",
                extra={
                    "model_id": loaded.model_id,
                    "version": loaded.version,
                },
            )
            return None

        except Exception as e:
            return load_error(
                code=ErrorCode.LOAD_WARMUP_FAILED,
                message=f"Warmup inference failed: {e}",
                model_id=loaded.model_id,
                version=loaded.version,
                cause=e,
                traceback=traceback.format_exc(),
            )
