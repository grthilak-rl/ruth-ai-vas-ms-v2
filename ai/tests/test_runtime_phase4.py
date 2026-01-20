"""
Phase 4 Tests: Production Hardening

Tests for:
1. Circuit breaker persistence
2. Fair RWLock (writer starvation fix)
3. Input validation on frame metadata
"""

import pytest
import os
import json
import base64
import threading
import time
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
from pathlib import Path

# Test imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# =============================================================================
# Test: Circuit Breaker Persistence
# =============================================================================

class TestCircuitBreakerPersistence:
    """Tests for circuit breaker state persistence."""

    @pytest.fixture
    def temp_state_file(self):
        """Create a temporary state file."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            yield f.name
        # Cleanup
        if os.path.exists(f.name):
            os.unlink(f.name)

    def test_persistence_saves_state(self, temp_state_file):
        """Persistence should save circuit breaker state to file."""
        from ai.runtime.recovery import (
            CircuitBreakerPersistence,
            CircuitBreakerState,
            CircuitState,
        )

        persistence = CircuitBreakerPersistence(state_file=temp_state_file)

        # Create test state
        state = CircuitBreakerState(model_id="test_model", version="1.0.0")
        state.state = CircuitState.OPEN
        state.recovery_attempts = 2

        # Save
        result = persistence.save_state({"test_model:1.0.0": state})
        assert result is True

        # Verify file exists and contains data
        assert os.path.exists(temp_state_file)
        with open(temp_state_file) as f:
            data = json.load(f)
        assert "test_model:1.0.0" in data
        assert data["test_model:1.0.0"]["state"] == "open"
        assert data["test_model:1.0.0"]["recovery_attempts"] == 2

    def test_persistence_loads_state(self, temp_state_file):
        """Persistence should load circuit breaker state from file."""
        from ai.runtime.recovery import CircuitBreakerPersistence

        # Write test data
        test_data = {
            "model1:1.0.0": {
                "model_id": "model1",
                "version": "1.0.0",
                "state": "open",
                "recovery_attempts": 3,
                "unhealthy_transitions": 5,
            }
        }
        with open(temp_state_file, "w") as f:
            json.dump(test_data, f)

        # Load
        persistence = CircuitBreakerPersistence(state_file=temp_state_file)
        loaded = persistence.load_state()

        assert "model1:1.0.0" in loaded
        assert loaded["model1:1.0.0"]["recovery_attempts"] == 3

    def test_persistence_clears_state(self, temp_state_file):
        """Persistence should clear state file."""
        from ai.runtime.recovery import CircuitBreakerPersistence

        # Create file
        with open(temp_state_file, "w") as f:
            f.write("{}")

        persistence = CircuitBreakerPersistence(state_file=temp_state_file)
        result = persistence.clear_state()

        assert result is True
        assert not os.path.exists(temp_state_file)

    def test_persistence_handles_missing_file(self, temp_state_file):
        """Persistence should handle missing state file gracefully."""
        from ai.runtime.recovery import CircuitBreakerPersistence

        # Ensure file doesn't exist
        if os.path.exists(temp_state_file):
            os.unlink(temp_state_file)

        persistence = CircuitBreakerPersistence(state_file=temp_state_file)
        loaded = persistence.load_state()

        assert loaded == {}

    def test_circuit_breaker_restores_state_on_init(self, temp_state_file):
        """CircuitBreaker should restore state from persistence on init."""
        from ai.runtime.recovery import (
            CircuitBreaker,
            CircuitBreakerPersistence,
            CircuitState,
        )

        # Pre-populate state file
        test_data = {
            "restored_model:2.0.0": {
                "model_id": "restored_model",
                "version": "2.0.0",
                "state": "open",
                "recovery_attempts": 1,
                "unhealthy_transitions": 2,
                "consecutive_timeouts": 0,
            }
        }
        with open(temp_state_file, "w") as f:
            json.dump(test_data, f)

        # Create circuit breaker with persistence
        persistence = CircuitBreakerPersistence(state_file=temp_state_file)
        breaker = CircuitBreaker(persistence=persistence, enable_persistence=True)

        # Check state was restored
        state = breaker.get_state("restored_model", "2.0.0")
        assert state is not None
        assert state.state == CircuitState.OPEN
        assert state.recovery_attempts == 1


# =============================================================================
# Test: Fair RWLock (Writer Starvation Fix)
# =============================================================================

class TestFairRWLock:
    """Tests for fair read-write lock."""

    def test_rwlock_allows_concurrent_readers(self):
        """RWLock should allow multiple concurrent readers."""
        from ai.runtime.registry import _RWLock

        lock = _RWLock()
        readers_acquired = []
        barrier = threading.Barrier(3)

        def reader(id):
            with lock.read():
                readers_acquired.append(id)
                barrier.wait(timeout=2)
                time.sleep(0.01)

        threads = [threading.Thread(target=reader, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)

        assert len(readers_acquired) == 3

    def test_rwlock_exclusive_writer(self):
        """RWLock should provide exclusive access to writer."""
        from ai.runtime.registry import _RWLock

        lock = _RWLock()
        shared_value = [0]
        iterations = 100

        def writer():
            for _ in range(iterations):
                with lock.write():
                    val = shared_value[0]
                    time.sleep(0.0001)
                    shared_value[0] = val + 1

        threads = [threading.Thread(target=writer) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # All increments should be atomic
        assert shared_value[0] == iterations * 3

    def test_rwlock_writer_not_starved(self):
        """RWLock should not starve writers when readers are active."""
        from ai.runtime.registry import _RWLock

        lock = _RWLock()
        writer_acquired = threading.Event()
        readers_started = 0
        reader_barrier = threading.Barrier(5)

        def reader():
            nonlocal readers_started
            for _ in range(10):
                with lock.read():
                    readers_started += 1
                    time.sleep(0.001)

        def writer():
            time.sleep(0.01)  # Let readers start
            with lock.write():
                writer_acquired.set()

        # Start many readers
        reader_threads = [threading.Thread(target=reader) for _ in range(5)]
        writer_thread = threading.Thread(target=writer)

        for t in reader_threads:
            t.start()
        writer_thread.start()

        # Writer should acquire within reasonable time (not starved)
        assert writer_acquired.wait(timeout=5), "Writer was starved!"

        for t in reader_threads:
            t.join(timeout=5)
        writer_thread.join(timeout=5)

    def test_rwlock_context_manager(self):
        """RWLock should work with context managers."""
        from ai.runtime.registry import _RWLock

        lock = _RWLock()

        # Read context
        with lock.read():
            pass  # Should not raise

        # Write context
        with lock.write():
            pass  # Should not raise


# =============================================================================
# Test: Input Validation on Frame Metadata
# =============================================================================

class TestFrameInputValidation:
    """Tests for inference input validation."""

    def test_valid_inference_request(self):
        """Valid inference request should pass validation."""
        from ai.server.routes.inference import InferenceRequest

        request = InferenceRequest(
            stream_id="550e8400-e29b-41d4-a716-446655440000",
            frame_base64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            timestamp=datetime.now(timezone.utc),
            model_id="fall_detection",
        )

        assert request.stream_id == "550e8400-e29b-41d4-a716-446655440000"
        assert request.model_id == "fall_detection"

    def test_invalid_stream_id_rejected(self):
        """Invalid stream_id format should be rejected."""
        from ai.server.routes.inference import InferenceRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            InferenceRequest(
                stream_id="not-a-uuid",
                frame_base64="dGVzdA==",
                timestamp=datetime.now(timezone.utc),
            )

        assert "stream_id must be a valid UUID" in str(exc_info.value)

    def test_invalid_model_id_rejected(self):
        """Invalid model_id format should be rejected."""
        from ai.server.routes.inference import InferenceRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            InferenceRequest(
                stream_id="550e8400-e29b-41d4-a716-446655440000",
                frame_base64="dGVzdA==",
                timestamp=datetime.now(timezone.utc),
                model_id="123invalid",  # Can't start with number
            )

        assert "model_id must start with a letter" in str(exc_info.value)

    def test_invalid_version_rejected(self):
        """Invalid model_version format should be rejected."""
        from ai.server.routes.inference import InferenceRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            InferenceRequest(
                stream_id="550e8400-e29b-41d4-a716-446655440000",
                frame_base64="dGVzdA==",
                timestamp=datetime.now(timezone.utc),
                model_version="v1.0",  # Not valid semver
            )

        assert "model_version must be semantic version" in str(exc_info.value)

    def test_valid_semver_accepted(self):
        """Valid semantic versions should be accepted."""
        from ai.server.routes.inference import InferenceRequest

        versions = ["1.0.0", "2.1.0", "0.0.1", "1.2.3-beta"]
        for version in versions:
            request = InferenceRequest(
                stream_id="550e8400-e29b-41d4-a716-446655440000",
                frame_base64="dGVzdA==",
                timestamp=datetime.now(timezone.utc),
                model_version=version,
            )
            assert request.model_version == version

    def test_invalid_frame_format_rejected(self):
        """Invalid frame_format should be rejected."""
        from ai.server.routes.inference import InferenceRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            InferenceRequest(
                stream_id="550e8400-e29b-41d4-a716-446655440000",
                frame_base64="dGVzdA==",
                timestamp=datetime.now(timezone.utc),
                frame_format="gif",  # Not supported
            )

        assert "frame_format must be one of" in str(exc_info.value)

    def test_timestamp_drift_rejected(self):
        """Timestamps too far in past/future should be rejected."""
        from ai.server.routes.inference import InferenceRequest
        from pydantic import ValidationError

        # Timestamp 48 hours in the past
        old_ts = datetime.now(timezone.utc) - timedelta(hours=48)

        with pytest.raises(ValidationError) as exc_info:
            InferenceRequest(
                stream_id="550e8400-e29b-41d4-a716-446655440000",
                frame_base64="dGVzdA==",
                timestamp=old_ts,
            )

        assert "timestamp drift too large" in str(exc_info.value)

    def test_deep_metadata_rejected(self):
        """Deeply nested metadata should be rejected."""
        from ai.server.routes.inference import InferenceRequest
        from pydantic import ValidationError

        # Create deeply nested structure
        deep_dict = {"level1": {"level2": {"level3": {"level4": {"level5": {"level6": "too deep"}}}}}}

        with pytest.raises(ValidationError) as exc_info:
            InferenceRequest(
                stream_id="550e8400-e29b-41d4-a716-446655440000",
                frame_base64="dGVzdA==",
                timestamp=datetime.now(timezone.utc),
                metadata=deep_dict,
            )

        assert "nesting depth exceeds limit" in str(exc_info.value)

    def test_large_metadata_rejected(self):
        """Metadata exceeding size limit should be rejected."""
        from ai.server.routes.inference import InferenceRequest
        from pydantic import ValidationError

        # Create large metadata (> 64KB)
        large_string = "x" * 70000
        large_metadata = {"data": large_string}

        with pytest.raises(ValidationError) as exc_info:
            InferenceRequest(
                stream_id="550e8400-e29b-41d4-a716-446655440000",
                frame_base64="dGVzdA==",
                timestamp=datetime.now(timezone.utc),
                metadata=large_metadata,
            )

        assert "metadata too large" in str(exc_info.value)

    def test_invalid_base64_rejected(self):
        """Invalid base64 characters should be rejected."""
        from ai.server.routes.inference import InferenceRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            InferenceRequest(
                stream_id="550e8400-e29b-41d4-a716-446655440000",
                frame_base64="invalid!@#$%^&*()",
                timestamp=datetime.now(timezone.utc),
            )

        assert "Invalid base64" in str(exc_info.value) or "illegal characters" in str(exc_info.value)

    def test_frame_dimension_validation(self):
        """Frame dimensions should be validated."""
        from ai.server.routes.inference import InferenceRequest
        from pydantic import ValidationError

        # Width too large
        with pytest.raises(ValidationError):
            InferenceRequest(
                stream_id="550e8400-e29b-41d4-a716-446655440000",
                frame_base64="dGVzdA==",
                timestamp=datetime.now(timezone.utc),
                frame_width=10000,  # > 7680
            )

        # Height too small
        with pytest.raises(ValidationError):
            InferenceRequest(
                stream_id="550e8400-e29b-41d4-a716-446655440000",
                frame_base64="dGVzdA==",
                timestamp=datetime.now(timezone.utc),
                frame_height=32,  # < 64
            )


# =============================================================================
# Test: Frame Decoding Validation
# =============================================================================

class TestFrameDecodingValidation:
    """Tests for frame decoding security."""

    def test_decode_valid_png(self):
        """Valid PNG should decode successfully."""
        from ai.server.routes.inference import _decode_base64_frame
        import numpy as np
        from PIL import Image
        import io
        import base64

        # Create a 100x100 test image (meets min size requirement)
        test_image = Image.new("RGB", (100, 100), color=(255, 0, 0))
        buffer = io.BytesIO()
        test_image.save(buffer, format="PNG")
        png_base64 = base64.b64encode(buffer.getvalue()).decode()

        frame = _decode_base64_frame(png_base64, "png")

        assert frame is not None
        assert frame.shape[0] == 100  # height
        assert frame.shape[1] == 100  # width
        assert frame.shape[2] == 3  # BGR channels

    def test_decode_invalid_data_raises(self):
        """Invalid image data should raise ValueError."""
        from ai.server.routes.inference import _decode_base64_frame

        # Valid base64 but not an image
        invalid_data = base64.b64encode(b"not an image").decode()

        with pytest.raises(ValueError) as exc_info:
            _decode_base64_frame(invalid_data, "jpeg")

        assert "Failed to decode" in str(exc_info.value)


# =============================================================================
# Test: Model Registry with Fair RWLock
# =============================================================================

class TestRegistryWithFairLock:
    """Tests for ModelRegistry using the fair RWLock."""

    def test_registry_concurrent_reads(self):
        """Registry should handle concurrent reads."""
        from ai.runtime.registry import ModelRegistry
        from ai.runtime.models import ModelVersionDescriptor, InputSpecification, OutputSpecification
        from pathlib import Path

        registry = ModelRegistry()

        # Register a model
        desc = ModelVersionDescriptor(
            model_id="test",
            version="1.0.0",
            display_name="Test",
            description="Test model",
            directory_path=Path("/tmp/test"),
            input_spec=InputSpecification(),
            output_spec=OutputSpecification(),
        )
        registry.register_version(desc)

        # Concurrent reads
        results = []

        def reader():
            for _ in range(100):
                v = registry.get_version("test", "1.0.0")
                results.append(v is not None)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert all(results)
        assert len(results) == 500

    def test_registry_concurrent_writes(self):
        """Registry should handle concurrent writes safely."""
        from ai.runtime.registry import ModelRegistry
        from ai.runtime.models import LoadState

        registry = ModelRegistry()

        # Pre-register a model
        from ai.runtime.models import ModelVersionDescriptor, InputSpecification, OutputSpecification
        from pathlib import Path

        desc = ModelVersionDescriptor(
            model_id="test",
            version="1.0.0",
            display_name="Test",
            description="Test model",
            directory_path=Path("/tmp/test"),
            input_spec=InputSpecification(),
            output_spec=OutputSpecification(),
        )
        registry.register_version(desc)

        # Concurrent state updates
        states = [LoadState.LOADING, LoadState.READY, LoadState.FAILED]
        errors = []

        def writer(state):
            try:
                for _ in range(50):
                    registry.update_state("test", "1.0.0", state)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(s,)) for s in states]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0
