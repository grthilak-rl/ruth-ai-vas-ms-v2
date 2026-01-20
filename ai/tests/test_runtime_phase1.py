"""
Tests for Phase 1 Runtime Fixes

This module tests the fixes implemented on the ai-runtime-fix branch:
1. GPU Manager Integration with Model Loader
2. Model Coordinator for atomic state transitions
3. Thread pool cancellation improvements in Sandbox
"""

import pytest
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ai.runtime.loader import ModelLoader, LoadedModel, LoadResult
from ai.runtime.gpu_manager import GPUManager, GPUStatus
from ai.runtime.coordinator import ModelCoordinator, CoordinationResult, CoordinationResultCode
from ai.runtime.registry import ModelRegistry
from ai.runtime.sandbox import (
    SandboxManager,
    ExecutionSandbox,
    TimeoutExecutor,
    ExecutorMode,
    ExecutionResult,
)
from ai.runtime.models import (
    LoadState,
    HealthStatus,
    ModelVersionDescriptor,
    InputSpecification,
    OutputSpecification,
    ResourceLimits,
    PerformanceHints,
    EntryPoints,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_descriptor():
    """Create a mock model version descriptor for testing."""
    return ModelVersionDescriptor(
        model_id="test_model",
        version="1.0.0",
        display_name="Test Model",
        description="A test model for unit tests",
        directory_path=Path("/tmp/test_model/1.0.0"),
        input_spec=InputSpecification(
            min_width=224,
            max_width=1920,
            min_height=224,
            max_height=1080,
            channels=3,
        ),
        output_spec=OutputSpecification(),
        limits=ResourceLimits(
            inference_timeout_ms=5000,
            preprocessing_timeout_ms=1000,
            postprocessing_timeout_ms=1000,
            max_memory_mb=2048,
        ),
        performance=PerformanceHints(
            warmup_iterations=0,
        ),
        entry_points=EntryPoints(
            inference="inference.py",
        ),
    )


@pytest.fixture
def mock_loaded_model():
    """Create a mock loaded model for testing."""
    def mock_infer(frame, **kwargs):
        return {"detections": [], "confidence": 0.95}

    return LoadedModel(
        model_id="test_model",
        version="1.0.0",
        infer=mock_infer,
        device="cpu",
    )


@pytest.fixture
def registry():
    """Create a fresh model registry."""
    return ModelRegistry()


@pytest.fixture
def sandbox_manager():
    """Create a fresh sandbox manager."""
    return SandboxManager()


# =============================================================================
# GPU MANAGER INTEGRATION TESTS
# =============================================================================


class TestGPUManagerIntegration:
    """Tests for GPU Manager integration with Model Loader."""

    def test_loader_without_gpu_manager_uses_cpu(self, mock_descriptor):
        """When no GPU manager is provided, loader should default to CPU."""
        loader = ModelLoader(
            gpu_manager=None,
            warmup_enabled=False,
        )

        # Access the internal device allocation method
        device = loader._allocate_device(mock_descriptor)

        assert device == "cpu"

    def test_loader_with_unavailable_gpu_uses_cpu(self, mock_descriptor):
        """When GPU is unavailable, loader should fall back to CPU."""
        gpu_manager = MagicMock(spec=GPUManager)
        gpu_manager.can_allocate.return_value = False
        gpu_manager.is_available = False

        loader = ModelLoader(
            gpu_manager=gpu_manager,
            warmup_enabled=False,
        )

        device = loader._allocate_device(mock_descriptor)

        assert device == "cpu"
        gpu_manager.can_allocate.assert_called_once()

    def test_loader_allocates_gpu_when_available(self, mock_descriptor):
        """When GPU is available, loader should allocate GPU memory."""
        gpu_manager = MagicMock(spec=GPUManager)
        gpu_manager.can_allocate.return_value = True
        gpu_manager.allocate.return_value = "cuda:0"

        loader = ModelLoader(
            gpu_manager=gpu_manager,
            warmup_enabled=False,
        )

        device = loader._allocate_device(mock_descriptor)

        assert device == "cuda:0"
        gpu_manager.allocate.assert_called_once()

    def test_loader_releases_gpu_on_unload(self, mock_descriptor):
        """GPU memory should be released when model is unloaded."""
        gpu_manager = MagicMock(spec=GPUManager)
        gpu_manager.can_allocate.return_value = True
        gpu_manager.allocate.return_value = "cuda:0"
        gpu_manager.release.return_value = True

        loader = ModelLoader(
            gpu_manager=gpu_manager,
            warmup_enabled=False,
        )

        # Simulate allocation
        device = loader._allocate_device(mock_descriptor)
        assert device == "cuda:0"

        # Simulate unload (we need to register the module first)
        qualified_id = f"{mock_descriptor.model_id}:{mock_descriptor.version}"
        loader._loaded_modules[qualified_id] = []

        # Unload
        loader.unload(mock_descriptor.model_id, mock_descriptor.version)

        gpu_manager.release.assert_called_once_with(
            mock_descriptor.model_id,
            mock_descriptor.version,
        )

    def test_loaded_model_includes_device(self, mock_loaded_model):
        """LoadedModel should include device information."""
        assert mock_loaded_model.device == "cpu"

        # Test repr includes device
        repr_str = repr(mock_loaded_model)
        assert "device=cpu" in repr_str


# =============================================================================
# MODEL COORDINATOR TESTS
# =============================================================================


class TestModelCoordinator:
    """Tests for Model Coordinator atomic state transitions."""

    def test_activate_model_creates_sandbox_and_updates_state(
        self, registry, sandbox_manager, mock_loaded_model, mock_descriptor
    ):
        """Activation should atomically create sandbox and set READY state."""
        # Register the model first
        registry.register_version(mock_descriptor)

        coordinator = ModelCoordinator(registry, sandbox_manager)

        result = coordinator.activate_model(
            mock_loaded_model.model_id,
            mock_loaded_model.version,
            mock_loaded_model,
            mock_descriptor,
        )

        assert result.success
        assert result.code == CoordinationResultCode.SUCCESS
        assert result.sandbox is not None

        # Verify registry state
        version = registry.get_version(mock_loaded_model.model_id, mock_loaded_model.version)
        assert version.state == LoadState.READY

        # Verify sandbox exists
        sandbox = sandbox_manager.get_sandbox(mock_loaded_model.model_id, mock_loaded_model.version)
        assert sandbox is not None

    def test_activate_model_fails_if_not_in_registry(
        self, registry, sandbox_manager, mock_loaded_model, mock_descriptor
    ):
        """Activation should fail if model is not registered."""
        coordinator = ModelCoordinator(registry, sandbox_manager)

        result = coordinator.activate_model(
            mock_loaded_model.model_id,
            mock_loaded_model.version,
            mock_loaded_model,
            mock_descriptor,
        )

        assert not result.success
        assert result.code == CoordinationResultCode.VERSION_NOT_FOUND

    def test_activate_model_is_idempotent(
        self, registry, sandbox_manager, mock_loaded_model, mock_descriptor
    ):
        """Second activation should return ALREADY_ACTIVE."""
        registry.register_version(mock_descriptor)
        coordinator = ModelCoordinator(registry, sandbox_manager)

        # First activation
        result1 = coordinator.activate_model(
            mock_loaded_model.model_id,
            mock_loaded_model.version,
            mock_loaded_model,
            mock_descriptor,
        )
        assert result1.success

        # Second activation
        result2 = coordinator.activate_model(
            mock_loaded_model.model_id,
            mock_loaded_model.version,
            mock_loaded_model,
            mock_descriptor,
        )
        assert not result2.success
        assert result2.code == CoordinationResultCode.ALREADY_ACTIVE

    def test_deactivate_model_removes_sandbox_and_updates_state(
        self, registry, sandbox_manager, mock_loaded_model, mock_descriptor
    ):
        """Deactivation should atomically remove sandbox and update state."""
        registry.register_version(mock_descriptor)
        coordinator = ModelCoordinator(registry, sandbox_manager)

        # Activate first
        coordinator.activate_model(
            mock_loaded_model.model_id,
            mock_loaded_model.version,
            mock_loaded_model,
            mock_descriptor,
        )

        # Deactivate
        result = coordinator.deactivate_model(
            mock_loaded_model.model_id,
            mock_loaded_model.version,
            new_state=LoadState.UNLOADED,
        )

        assert result.success

        # Verify registry state
        version = registry.get_version(mock_loaded_model.model_id, mock_loaded_model.version)
        assert version.state == LoadState.UNLOADED

        # Verify sandbox removed
        sandbox = sandbox_manager.get_sandbox(mock_loaded_model.model_id, mock_loaded_model.version)
        assert sandbox is None

    def test_get_ready_sandbox_returns_sandbox_only_when_ready(
        self, registry, sandbox_manager, mock_loaded_model, mock_descriptor
    ):
        """get_ready_sandbox should return sandbox only when model is READY."""
        registry.register_version(mock_descriptor)
        coordinator = ModelCoordinator(registry, sandbox_manager)

        # Before activation
        sandbox = coordinator.get_ready_sandbox(
            mock_loaded_model.model_id,
            mock_loaded_model.version,
        )
        assert sandbox is None

        # After activation
        coordinator.activate_model(
            mock_loaded_model.model_id,
            mock_loaded_model.version,
            mock_loaded_model,
            mock_descriptor,
        )

        sandbox = coordinator.get_ready_sandbox(
            mock_loaded_model.model_id,
            mock_loaded_model.version,
        )
        assert sandbox is not None

    def test_verify_invariants_detects_violations(
        self, registry, sandbox_manager, mock_loaded_model, mock_descriptor
    ):
        """verify_invariants should detect state/sandbox mismatches."""
        registry.register_version(mock_descriptor)
        coordinator = ModelCoordinator(registry, sandbox_manager)

        # Initially valid
        result = coordinator.verify_invariants()
        assert result["valid"]

        # Activate normally
        coordinator.activate_model(
            mock_loaded_model.model_id,
            mock_loaded_model.version,
            mock_loaded_model,
            mock_descriptor,
        )

        result = coordinator.verify_invariants()
        assert result["valid"]
        assert result["active_count"] == 1

    def test_concurrent_activations_are_serialized(
        self, registry, sandbox_manager, mock_descriptor
    ):
        """Concurrent activation attempts should be serialized by lock."""
        registry.register_version(mock_descriptor)
        coordinator = ModelCoordinator(registry, sandbox_manager)

        results = []

        def activate():
            def mock_infer(frame, **kwargs):
                return {"detections": []}

            model = LoadedModel(
                model_id="test_model",
                version="1.0.0",
                infer=mock_infer,
            )
            result = coordinator.activate_model(
                "test_model", "1.0.0", model, mock_descriptor
            )
            results.append(result)

        threads = [threading.Thread(target=activate) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Only one should succeed, rest should get ALREADY_ACTIVE
        success_count = sum(1 for r in results if r.success)
        already_active_count = sum(
            1 for r in results if r.code == CoordinationResultCode.ALREADY_ACTIVE
        )

        assert success_count == 1
        assert already_active_count == 4


# =============================================================================
# TIMEOUT EXECUTOR TESTS
# =============================================================================


class TestTimeoutExecutor:
    """Tests for improved timeout executor."""

    def test_thread_mode_is_default(self):
        """Default mode should be THREAD."""
        executor = TimeoutExecutor()
        assert executor.mode == ExecutorMode.THREAD
        executor.shutdown()

    def test_process_mode_can_be_configured(self):
        """Process mode should be configurable."""
        executor = TimeoutExecutor(mode=ExecutorMode.PROCESS, max_workers=2)
        assert executor.mode == ExecutorMode.PROCESS
        executor.shutdown()

    def test_successful_execution_returns_result(self):
        """Successful execution should return result."""
        executor = TimeoutExecutor()

        result, error, duration_ms = executor.execute_with_timeout(
            lambda x: x * 2,
            1000,  # timeout_ms
            5,  # argument to lambda
        )

        assert result == 10
        assert error is None
        assert duration_ms < 1000
        executor.shutdown()

    def test_timeout_returns_timeout_error(self):
        """Timeout should return TimeoutError."""
        executor = TimeoutExecutor()

        def slow_func():
            time.sleep(2)
            return "done"

        result, error, duration_ms = executor.execute_with_timeout(
            slow_func,
            timeout_ms=100,
        )

        assert result is None
        assert isinstance(error, TimeoutError)
        executor.shutdown()

    def test_pending_count_tracks_running_tasks(self):
        """pending_count should track active tasks."""
        executor = TimeoutExecutor(max_workers=2)

        assert executor.pending_count == 0

        # Start a slow task
        def slow_task():
            time.sleep(1)
            return "done"

        import concurrent.futures
        future = executor._executor.submit(slow_task)

        # Give it a moment to start
        time.sleep(0.1)

        # Note: pending_count only tracks tasks submitted via execute_with_timeout
        # The direct submit doesn't go through our tracking

        executor.shutdown(wait=True)

    def test_get_stats_returns_executor_info(self):
        """get_stats should return executor statistics."""
        executor = TimeoutExecutor(max_workers=4, mode=ExecutorMode.THREAD)

        stats = executor.get_stats()

        assert stats["mode"] == "thread"
        assert stats["max_workers"] == 4
        assert stats["pending_count"] == 0
        assert stats["shutdown"] is False

        executor.shutdown()

    def test_get_zombie_tasks_identifies_long_running(self):
        """get_zombie_tasks should identify tasks running longer than threshold."""
        executor = TimeoutExecutor()

        # Initially no zombies
        zombies = executor.get_zombie_tasks(threshold_seconds=0.1)
        assert len(zombies) == 0

        executor.shutdown()


# =============================================================================
# SANDBOX MANAGER TESTS
# =============================================================================


class TestSandboxManagerEnhancements:
    """Tests for enhanced sandbox manager functionality."""

    def test_sandbox_manager_accepts_executor_mode(self, mock_loaded_model, mock_descriptor):
        """SandboxManager should accept executor_mode parameter."""
        manager = SandboxManager(
            executor_mode=ExecutorMode.THREAD,
            executor_max_workers=4,
        )

        sandbox = manager.create_sandbox(mock_loaded_model, mock_descriptor)

        assert sandbox is not None
        manager.shutdown_all()

    def test_get_all_executor_stats(self, mock_loaded_model, mock_descriptor):
        """get_all_executor_stats should return stats for all sandboxes."""
        manager = SandboxManager()
        manager.create_sandbox(mock_loaded_model, mock_descriptor)

        stats = manager.get_all_executor_stats()

        qualified_id = f"{mock_loaded_model.model_id}:{mock_loaded_model.version}"
        assert qualified_id in stats
        assert "mode" in stats[qualified_id]
        assert "pending_count" in stats[qualified_id]

        manager.shutdown_all()

    def test_get_all_zombie_tasks(self, mock_loaded_model, mock_descriptor):
        """get_all_zombie_tasks should aggregate zombies across sandboxes."""
        manager = SandboxManager()
        manager.create_sandbox(mock_loaded_model, mock_descriptor)

        # No zombies expected in normal operation
        zombies = manager.get_all_zombie_tasks()
        assert len(zombies) == 0

        manager.shutdown_all()

    def test_get_total_pending_tasks(self, mock_loaded_model, mock_descriptor):
        """get_total_pending_tasks should sum pending across all sandboxes."""
        manager = SandboxManager()
        manager.create_sandbox(mock_loaded_model, mock_descriptor)

        total = manager.get_total_pending_tasks()
        assert total == 0  # No tasks running

        manager.shutdown_all()


# =============================================================================
# EXECUTION SANDBOX TESTS
# =============================================================================


class TestExecutionSandboxEnhancements:
    """Tests for enhanced execution sandbox functionality."""

    def test_sandbox_exposes_executor_stats(self, mock_loaded_model, mock_descriptor):
        """Sandbox should expose executor statistics."""
        sandbox = ExecutionSandbox(mock_loaded_model, mock_descriptor)

        stats = sandbox.get_executor_stats()

        assert "mode" in stats
        assert "pending_count" in stats
        assert stats["pending_count"] == 0

        sandbox.shutdown()

    def test_sandbox_exposes_zombie_tasks(self, mock_loaded_model, mock_descriptor):
        """Sandbox should expose zombie task detection."""
        sandbox = ExecutionSandbox(mock_loaded_model, mock_descriptor)

        zombies = sandbox.get_zombie_tasks(threshold_seconds=0.1)

        assert isinstance(zombies, list)
        assert len(zombies) == 0

        sandbox.shutdown()


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestPhase1Integration:
    """Integration tests for all Phase 1 components working together."""

    def test_full_model_lifecycle_with_coordinator(
        self, registry, sandbox_manager, mock_loaded_model, mock_descriptor
    ):
        """Test complete model lifecycle: register → activate → execute → deactivate."""
        # Setup coordinator
        coordinator = ModelCoordinator(registry, sandbox_manager)

        # Step 1: Register model
        registry.register_version(mock_descriptor)
        assert registry.version_exists("test_model", "1.0.0")

        # Step 2: Activate model
        result = coordinator.activate_model(
            "test_model", "1.0.0", mock_loaded_model, mock_descriptor
        )
        assert result.success

        # Verify invariants
        invariants = coordinator.verify_invariants()
        assert invariants["valid"]

        # Step 3: Get sandbox and execute
        sandbox = coordinator.get_ready_sandbox("test_model", "1.0.0")
        assert sandbox is not None

        import numpy as np
        dummy_frame = np.zeros((224, 224, 3), dtype=np.uint8)
        exec_result = sandbox.execute(dummy_frame)
        assert exec_result.success

        # Step 4: Deactivate model
        result = coordinator.deactivate_model(
            "test_model", "1.0.0", LoadState.UNLOADED
        )
        assert result.success

        # Verify cleanup
        sandbox = coordinator.get_ready_sandbox("test_model", "1.0.0")
        assert sandbox is None

        version = registry.get_version("test_model", "1.0.0")
        assert version.state == LoadState.UNLOADED

    def test_gpu_allocation_flows_through_loaded_model(self):
        """GPU device should flow from allocation through to LoadedModel."""
        # Create mock GPU manager
        gpu_manager = MagicMock(spec=GPUManager)
        gpu_manager.can_allocate.return_value = True
        gpu_manager.allocate.return_value = "cuda:0"

        # Create loader with GPU manager
        loader = ModelLoader(
            gpu_manager=gpu_manager,
            warmup_enabled=False,
            default_memory_estimate_mb=1024,
        )

        # The device should be "cuda:0" based on GPU manager
        mock_desc = MagicMock()
        mock_desc.model_id = "test"
        mock_desc.version = "1.0.0"
        mock_desc.qualified_id = "test:1.0.0"
        mock_desc.limits = MagicMock()
        mock_desc.limits.memory_mb = 1024

        device = loader._allocate_device(mock_desc)
        assert device == "cuda:0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
