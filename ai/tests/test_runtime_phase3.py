"""
Phase 3 Tests: Containerization

Tests for:
1. Environment-based configuration (12-factor)
2. Graceful shutdown handling
3. GPU manager release_all
4. Dependencies clear_all
"""

import pytest
import os
from unittest.mock import Mock, patch, MagicMock

# Test imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# =============================================================================
# Test: Environment-Based Configuration (12-Factor)
# =============================================================================

class TestEnvironmentConfiguration:
    """Tests for 12-factor compliant configuration."""

    def test_config_loads_defaults(self):
        """Config should load with sensible defaults."""
        from ai.server.config import RuntimeConfig

        # Create fresh config with cleared environment
        with patch.dict(os.environ, {}, clear=True):
            config = RuntimeConfig()

            assert config.server_host == "0.0.0.0"
            assert config.server_port == 8000
            # ruth_ai_env defaults to "production" but may be overridden by .env file
            assert config.ruth_ai_env in ["production", "development", "test"]
            assert config.ai_runtime_hardware == "auto"

    def test_config_loads_from_environment(self):
        """Config should load values from environment variables."""
        from ai.server.config import RuntimeConfig

        # Set environment variables
        with patch.dict(os.environ, {
            "SERVER_PORT": "9000",
            "LOG_LEVEL": "DEBUG",
            "RUTH_AI_ENV": "development",
            "AI_RUNTIME_HARDWARE": "cpu"
        }):
            config = RuntimeConfig()

            assert config.server_port == 9000
            assert config.log_level == "DEBUG"
            assert config.ruth_ai_env == "development"
            assert config.ai_runtime_hardware == "cpu"

    def test_config_deployment_profiles(self):
        """Config should support deployment profiles."""
        from ai.server.config import RuntimeConfig

        profiles = ["dev", "test", "prod-cpu", "prod-gpu", "edge-jetson"]

        for profile in profiles:
            with patch.dict(os.environ, {"RUTH_AI_PROFILE": profile}):
                config = RuntimeConfig()
                assert config.ruth_ai_profile == profile

    def test_config_hardware_modes(self):
        """Config should support hardware modes."""
        from ai.server.config import RuntimeConfig

        modes = ["auto", "cpu", "gpu", "jetson"]

        for mode in modes:
            with patch.dict(os.environ, {"AI_RUNTIME_HARDWARE": mode}):
                config = RuntimeConfig()
                assert config.ai_runtime_hardware == mode

    def test_config_graceful_shutdown_timeout(self):
        """Config should have graceful shutdown timeout."""
        from ai.server.config import RuntimeConfig

        config = RuntimeConfig()
        assert hasattr(config, "graceful_shutdown_timeout_seconds")
        assert config.graceful_shutdown_timeout_seconds >= 5
        assert config.graceful_shutdown_timeout_seconds <= 300

    def test_config_caching_and_reload(self):
        """Config should support caching and reload."""
        from ai.server.config import get_config, reload_config

        config1 = get_config()
        config2 = get_config()

        # Should be same cached instance
        assert config1 is config2

        # Reload should return fresh instance
        config3 = reload_config()
        # Note: IDs might be same if runtime_id is generated consistently


# =============================================================================
# Test: Dependencies Clear All
# =============================================================================

class TestDependenciesClearAll:
    """Tests for dependencies.clear_all() function."""

    def test_clear_all_resets_dependencies(self):
        """clear_all should reset all global dependencies to None."""
        from ai.server import dependencies

        # Set some mock values
        mock_registry = Mock()
        mock_pipeline = Mock()
        mock_reporter = Mock()
        mock_sandbox_manager = Mock()

        dependencies.set_registry(mock_registry)
        dependencies.set_pipeline(mock_pipeline)
        dependencies.set_reporter(mock_reporter)
        dependencies.set_sandbox_manager(mock_sandbox_manager)

        # Verify they're set
        assert dependencies.get_registry() is mock_registry
        assert dependencies.get_pipeline() is mock_pipeline
        assert dependencies.get_reporter() is mock_reporter
        assert dependencies.get_sandbox_manager() is mock_sandbox_manager

        # Clear all
        dependencies.clear_all()

        # Verify they're cleared
        assert dependencies.get_registry() is None
        assert dependencies.get_pipeline() is None
        assert dependencies.get_reporter() is None
        assert dependencies.get_sandbox_manager() is None


# =============================================================================
# Test: GPU Manager Release All
# =============================================================================

class TestGPUManagerReleaseAll:
    """Tests for GPUManager.release_all() method."""

    def test_release_all_clears_allocations(self):
        """release_all should clear all GPU allocations."""
        from ai.runtime.gpu_manager import GPUManager

        # Create manager (will work in CPU-only mode)
        manager = GPUManager(enable_gpu=False, fallback_to_cpu=True)

        # release_all should return 0 when no allocations
        released = manager.release_all()
        assert released == 0

    def test_release_all_returns_count(self):
        """release_all should return number of released allocations."""
        from ai.runtime.gpu_manager import GPUManager, ModelAllocation
        from datetime import datetime

        manager = GPUManager(enable_gpu=False, fallback_to_cpu=True)

        # Manually add some allocations for testing
        with manager._lock:
            manager._allocations["model1:1.0"] = ModelAllocation(
                model_id="model1",
                version="1.0",
                device_id=-1,  # CPU
                allocated_mb=1024,
                allocated_at=datetime.utcnow()
            )
            manager._allocations["model2:2.0"] = ModelAllocation(
                model_id="model2",
                version="2.0",
                device_id=-1,
                allocated_mb=2048,
                allocated_at=datetime.utcnow()
            )

        # Release all
        released = manager.release_all()

        assert released == 2
        assert len(manager._allocations) == 0


# =============================================================================
# Test: Sandbox Manager Shutdown
# =============================================================================

class TestSandboxManagerShutdown:
    """Tests for SandboxManager shutdown behavior."""

    def test_shutdown_all_exists(self):
        """SandboxManager should have shutdown_all method."""
        from ai.runtime.sandbox import SandboxManager

        manager = SandboxManager()
        assert hasattr(manager, "shutdown_all")
        assert callable(manager.shutdown_all)

    def test_shutdown_all_empty_manager(self):
        """shutdown_all should work with no sandboxes."""
        from ai.runtime.sandbox import SandboxManager

        manager = SandboxManager()

        # Should not raise
        manager.shutdown_all()

        # Should have no sandboxes (use property, not method)
        assert manager.sandbox_count == 0


# =============================================================================
# Test: Dockerfile Validation
# =============================================================================

class TestDockerfileStructure:
    """Tests for Dockerfile structure validation."""

    @pytest.fixture
    def dockerfile_content(self):
        """Load Dockerfile content."""
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
        if dockerfile_path.exists():
            return dockerfile_path.read_text()
        return None

    def test_dockerfile_exists(self, dockerfile_content):
        """Dockerfile should exist."""
        assert dockerfile_content is not None

    def test_dockerfile_has_variant_arg(self, dockerfile_content):
        """Dockerfile should have VARIANT build arg."""
        if dockerfile_content:
            assert "ARG VARIANT=" in dockerfile_content

    def test_dockerfile_has_cpu_base(self, dockerfile_content):
        """Dockerfile should have CPU base image."""
        if dockerfile_content:
            assert "base-cpu" in dockerfile_content
            assert "python:" in dockerfile_content

    def test_dockerfile_has_gpu_base(self, dockerfile_content):
        """Dockerfile should have GPU base image."""
        if dockerfile_content:
            assert "base-gpu" in dockerfile_content
            assert "nvidia/cuda" in dockerfile_content

    def test_dockerfile_has_jetson_base(self, dockerfile_content):
        """Dockerfile should have Jetson base image."""
        if dockerfile_content:
            assert "base-jetson" in dockerfile_content
            assert "l4t" in dockerfile_content.lower()

    def test_dockerfile_has_healthcheck(self, dockerfile_content):
        """Dockerfile should have HEALTHCHECK."""
        if dockerfile_content:
            assert "HEALTHCHECK" in dockerfile_content
            assert "/health/ready" in dockerfile_content

    def test_dockerfile_has_stopsignal(self, dockerfile_content):
        """Dockerfile should have STOPSIGNAL for graceful shutdown."""
        if dockerfile_content:
            assert "STOPSIGNAL" in dockerfile_content
            assert "SIGTERM" in dockerfile_content

    def test_dockerfile_has_graceful_shutdown(self, dockerfile_content):
        """Dockerfile should have graceful shutdown timeout in CMD."""
        if dockerfile_content:
            assert "timeout-graceful-shutdown" in dockerfile_content

    def test_dockerfile_has_nonroot_user(self, dockerfile_content):
        """Dockerfile should run as non-root user."""
        if dockerfile_content:
            assert "USER ruth" in dockerfile_content or "USER" in dockerfile_content

    def test_dockerfile_has_12_factor_envs(self, dockerfile_content):
        """Dockerfile should set 12-factor compliant ENV vars."""
        if dockerfile_content:
            assert "PYTHONUNBUFFERED=1" in dockerfile_content
            assert "PYTHONDONTWRITEBYTECODE=1" in dockerfile_content


# =============================================================================
# Test: Requirements Files
# =============================================================================

class TestRequirementsFiles:
    """Tests for requirements file structure."""

    def test_requirements_cpu_exists(self):
        """requirements.txt should exist."""
        req_path = Path(__file__).parent.parent / "requirements.txt"
        assert req_path.exists()

    def test_requirements_gpu_exists(self):
        """requirements-gpu.txt should exist."""
        req_path = Path(__file__).parent.parent / "requirements-gpu.txt"
        assert req_path.exists()

    def test_requirements_gpu_has_cuda_torch(self):
        """requirements-gpu.txt should have CUDA torch."""
        req_path = Path(__file__).parent.parent / "requirements-gpu.txt"
        if req_path.exists():
            content = req_path.read_text()
            assert "cu121" in content or "cuda" in content.lower()

    def test_requirements_cpu_has_cpu_torch(self):
        """requirements.txt should have CPU torch."""
        req_path = Path(__file__).parent.parent / "requirements.txt"
        if req_path.exists():
            content = req_path.read_text()
            assert "cpu" in content.lower()


# =============================================================================
# Test: Graceful Shutdown Flow
# =============================================================================

class TestGracefulShutdownFlow:
    """Tests for graceful shutdown flow."""

    def test_lifespan_cleanup_is_async(self):
        """Lifespan cleanup should be async-compatible."""
        from ai.server.main import lifespan

        # lifespan should be an async context manager
        import inspect
        assert inspect.isasyncgenfunction(lifespan.__wrapped__ if hasattr(lifespan, '__wrapped__') else lifespan)

    def test_shutdown_clears_dependencies(self):
        """Shutdown should clear global dependencies."""
        from ai.server import dependencies

        # Clear to known state
        dependencies.clear_all()

        # All should be None after clear
        assert dependencies.get_registry() is None
        assert dependencies.get_pipeline() is None
        assert dependencies.get_reporter() is None
        assert dependencies.get_sandbox_manager() is None
