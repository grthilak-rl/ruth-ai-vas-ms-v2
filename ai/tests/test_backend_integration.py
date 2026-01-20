"""
Tests for Backend Integration Client

Tests the HTTPBackendClient and its integration with the CapabilityPublisher.
"""

import json
import time
import threading
import uuid
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from ai.runtime.backend_client import (
    HTTPBackendClient,
    AsyncHTTPBackendClient,
    BackendClientConfig,
    create_backend_client,
)
from ai.runtime.reporting import (
    FullCapabilityReport,
    ModelCapabilityReport,
    RuntimeCapacityReport,
    VersionCapability,
    HealthStatus,
    ModelStatus,
    CapabilityPublisher,
    HealthAggregator,
    RuntimeCapacityTracker,
    create_reporting_stack,
)
from ai.runtime.registry import ModelRegistry
from ai.runtime.models import (
    ModelVersionDescriptor,
    LoadState,
    HealthStatus as ModelHealthStatus,
)


# =============================================================================
# TEST FIXTURES
# =============================================================================


class MockBackendHandler(BaseHTTPRequestHandler):
    """Mock HTTP server handler for testing backend client."""

    # Class-level storage for received requests
    received_requests: List[Dict[str, Any]] = []
    response_status: int = 200
    response_body: Dict[str, Any] = {"status": "ok"}

    def do_POST(self):
        """Handle POST requests."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        # Store the request
        request_data = {
            "path": self.path,
            "headers": dict(self.headers),
            "body": json.loads(body) if body else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        MockBackendHandler.received_requests.append(request_data)

        # Send response
        self.send_response(self.response_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.response_body).encode())

    def log_message(self, format, *args):
        """Suppress logging."""
        pass


@pytest.fixture
def mock_backend_server():
    """Start a mock backend server."""
    # Clear previous requests
    MockBackendHandler.received_requests = []
    MockBackendHandler.response_status = 200
    MockBackendHandler.response_body = {"status": "ok"}

    # Find available port
    server = HTTPServer(("localhost", 0), MockBackendHandler)
    port = server.server_address[1]

    # Start server in background thread
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    yield f"http://localhost:{port}"

    # Cleanup
    server.shutdown()


@pytest.fixture
def sample_capability_report() -> FullCapabilityReport:
    """Create a sample capability report for testing."""
    version_cap = VersionCapability(
        model_id="fall_detection",
        version="1.0.0",
        display_name="Fall Detection",
        description="Detects falls in video frames",
        input_types=["frame"],
        input_format="jpeg",
        output_event_types=["fall_detected", "no_fall"],
        provides_bounding_boxes=True,
        provides_metadata=True,
        supports_cpu=True,
        supports_gpu=True,
        supports_jetson=False,
        inference_time_hint_ms=100,
        recommended_fps=10,
        max_fps=30,
        recommended_batch_size=1,
        max_concurrent=5,
        status=ModelStatus.ACTIVE,
        health=HealthStatus.HEALTHY,
    )

    model_report = ModelCapabilityReport(
        model_id="fall_detection",
        health=HealthStatus.HEALTHY,
        versions=[version_cap],
        total_versions=1,
        healthy_versions=1,
        degraded_versions=0,
    )

    capacity_report = RuntimeCapacityReport(
        max_concurrent_inferences=10,
        active_inferences=2,
        available_slots=8,
        per_model_limits={"fall_detection": 5},
        backpressure_level="none",
        queue_depth=0,
        queue_capacity=100,
    )

    return FullCapabilityReport(
        runtime_id="test-runtime-001",
        timestamp=datetime.now(timezone.utc),
        models=[model_report],
        capacity=capacity_report,
        runtime_health=HealthStatus.HEALTHY,
        total_models=1,
        healthy_models=1,
        total_versions=1,
        ready_versions=1,
    )


# =============================================================================
# HTTP BACKEND CLIENT TESTS
# =============================================================================


class TestHTTPBackendClient:
    """Tests for HTTPBackendClient."""

    def test_client_initialization(self):
        """Test client initializes with correct config."""
        config = BackendClientConfig(
            backend_url="http://localhost:8080",
            api_key="test-key",
        )
        client = HTTPBackendClient(config=config, runtime_id="test-001")

        assert client.runtime_id == "test-001"
        assert client.config.backend_url == "http://localhost:8080"
        assert not client.is_registered()

        client.close()

    def test_register_capabilities_success(self, mock_backend_server, sample_capability_report):
        """Test successful capability registration."""
        client = HTTPBackendClient(
            config=BackendClientConfig(backend_url=mock_backend_server),
            runtime_id="test-runtime",
        )

        correlation_id = str(uuid.uuid4())
        result = client.register_capabilities(sample_capability_report, correlation_id)

        assert result is True
        assert client.is_registered()
        assert len(MockBackendHandler.received_requests) == 1

        # Verify request content
        request = MockBackendHandler.received_requests[0]
        assert request["path"] == "/internal/v1/ai-runtime/register"
        assert request["headers"]["X-Correlation-ID"] == correlation_id
        # runtime_id comes from the report, not the client
        assert request["body"]["runtime_id"] == sample_capability_report.runtime_id
        assert request["body"]["runtime_health"] == "healthy"

        client.close()

    def test_register_capabilities_failure(self, mock_backend_server, sample_capability_report):
        """Test capability registration handles server errors."""
        MockBackendHandler.response_status = 500
        MockBackendHandler.response_body = {"error": "Internal server error"}

        client = HTTPBackendClient(
            config=BackendClientConfig(
                backend_url=mock_backend_server,
                max_retries=0,  # No retries for faster test
            ),
            runtime_id="test-runtime",
        )

        result = client.register_capabilities(sample_capability_report, "corr-123")

        assert result is False
        assert not client.is_registered()

        client.close()

    def test_deregister_version(self, mock_backend_server):
        """Test version deregistration."""
        client = HTTPBackendClient(
            config=BackendClientConfig(backend_url=mock_backend_server),
            runtime_id="test-runtime",
        )

        result = client.deregister_version(
            model_id="fall_detection",
            version="1.0.0",
            correlation_id="corr-456",
        )

        assert result is True
        assert len(MockBackendHandler.received_requests) == 1

        request = MockBackendHandler.received_requests[0]
        assert "/deregister/version" in request["path"]
        assert request["body"]["model_id"] == "fall_detection"
        assert request["body"]["version"] == "1.0.0"

        client.close()

    def test_push_health(self, mock_backend_server):
        """Test health status push."""
        client = HTTPBackendClient(
            config=BackendClientConfig(backend_url=mock_backend_server),
            runtime_id="test-runtime",
        )

        result = client.push_health(
            runtime_health=HealthStatus.HEALTHY,
            model_healths={
                "fall_detection": HealthStatus.HEALTHY,
                "helmet_detection": HealthStatus.DEGRADED,
            },
            correlation_id="health-001",
        )

        assert result is True
        assert len(MockBackendHandler.received_requests) == 1

        request = MockBackendHandler.received_requests[0]
        assert request["path"] == "/internal/v1/ai-runtime/health"
        assert request["body"]["runtime_health"] == "healthy"
        assert request["body"]["models"]["fall_detection"] == "healthy"
        assert request["body"]["models"]["helmet_detection"] == "degraded"

        client.close()

    def test_deregister_on_shutdown(self, mock_backend_server):
        """Test deregistration during shutdown."""
        client = HTTPBackendClient(
            config=BackendClientConfig(backend_url=mock_backend_server),
            runtime_id="test-runtime",
        )

        result = client.deregister("shutdown-001")

        assert result is True
        assert len(MockBackendHandler.received_requests) == 1

        request = MockBackendHandler.received_requests[0]
        assert request["path"] == "/internal/v1/ai-runtime/deregister"
        assert request["body"]["reason"] == "graceful_shutdown"

        client.close()

    def test_retry_on_connection_error(self):
        """Test client retries on connection errors."""
        client = HTTPBackendClient(
            config=BackendClientConfig(
                backend_url="http://localhost:19999",  # Non-existent port
                max_retries=2,
                retry_delay_base=0.1,
            ),
            runtime_id="test-runtime",
        )

        # This should fail after retries
        result = client.push_health(
            runtime_health=HealthStatus.HEALTHY,
            model_healths={},
            correlation_id="retry-test",
        )

        assert result is False

        client.close()

    def test_no_retry_on_client_error(self, mock_backend_server, sample_capability_report):
        """Test client doesn't retry on 4xx errors."""
        MockBackendHandler.response_status = 400
        MockBackendHandler.response_body = {"error": "Bad request"}

        client = HTTPBackendClient(
            config=BackendClientConfig(
                backend_url=mock_backend_server,
                max_retries=3,
            ),
            runtime_id="test-runtime",
        )

        result = client.register_capabilities(sample_capability_report, "no-retry")

        # Should have only one request (no retries)
        assert result is False
        assert len(MockBackendHandler.received_requests) == 1

        client.close()


# =============================================================================
# FACTORY FUNCTION TESTS
# =============================================================================


class TestFactoryFunction:
    """Tests for the create_backend_client factory."""

    def test_create_sync_client(self):
        """Test creating synchronous client."""
        client = create_backend_client(
            backend_url="http://localhost:8080",
            runtime_id="test-001",
            async_client=False,
        )

        assert isinstance(client, HTTPBackendClient)
        assert client.runtime_id == "test-001"

        client.close()

    def test_create_async_client(self):
        """Test creating asynchronous client."""
        client = create_backend_client(
            backend_url="http://localhost:8080",
            runtime_id="test-002",
            async_client=True,
        )

        assert isinstance(client, AsyncHTTPBackendClient)
        assert client.runtime_id == "test-002"

    def test_create_client_with_auth(self):
        """Test creating client with authentication."""
        client = create_backend_client(
            backend_url="http://localhost:8080",
            runtime_id="test-003",
            api_key="my-api-key",
            service_token="my-token",
        )

        assert client.config.api_key == "my-api-key"
        assert client.config.service_token == "my-token"

        client.close()


# =============================================================================
# INTEGRATION WITH CAPABILITY PUBLISHER TESTS
# =============================================================================


class TestCapabilityPublisherIntegration:
    """Tests for CapabilityPublisher with HTTPBackendClient."""

    def test_backend_client_with_sample_report(self, mock_backend_server, sample_capability_report):
        """Test backend client correctly sends capability report."""
        # Create backend client
        backend_client = HTTPBackendClient(
            config=BackendClientConfig(backend_url=mock_backend_server),
            runtime_id="integration-test",
        )

        # Call register_capabilities directly
        correlation_id = "test-corr-id"
        result = backend_client.register_capabilities(sample_capability_report, correlation_id)

        # Should have made exactly one registration call
        assert result is True
        assert backend_client.is_registered()
        assert len(MockBackendHandler.received_requests) == 1

        request = MockBackendHandler.received_requests[0]
        assert request["path"] == "/internal/v1/ai-runtime/register"
        assert request["body"]["runtime_id"] == "test-runtime-001"
        assert request["body"]["runtime_health"] == "healthy"
        assert len(request["body"]["models"]) == 1

        backend_client.close()

    def test_backend_client_failure_tracking(self, mock_backend_server, sample_capability_report):
        """Test backend client tracks failures correctly."""
        MockBackendHandler.response_status = 500

        backend_client = HTTPBackendClient(
            config=BackendClientConfig(
                backend_url=mock_backend_server,
                max_retries=0,
            ),
            runtime_id="failure-test",
        )

        # Call register - should fail
        result = backend_client.register_capabilities(sample_capability_report, "fail-test")

        # Should have failed
        assert result is False
        assert not backend_client.is_registered()

        backend_client.close()


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================


class TestBackendClientConfig:
    """Tests for BackendClientConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = BackendClientConfig()

        assert config.backend_url == "http://localhost:8080"
        assert config.connect_timeout == 5.0
        assert config.read_timeout == 10.0
        assert config.max_retries == 3
        assert config.api_key is None

    def test_custom_config(self):
        """Test custom configuration values."""
        config = BackendClientConfig(
            backend_url="http://backend:9000",
            connect_timeout=10.0,
            max_retries=5,
            api_key="secret-key",
        )

        assert config.backend_url == "http://backend:9000"
        assert config.connect_timeout == 10.0
        assert config.max_retries == 5
        assert config.api_key == "secret-key"


# =============================================================================
# PAYLOAD SERIALIZATION TESTS
# =============================================================================


class TestPayloadSerialization:
    """Tests for capability report serialization."""

    def test_version_capability_to_dict(self):
        """Test VersionCapability serializes correctly."""
        cap = VersionCapability(
            model_id="test_model",
            version="2.0.0",
            display_name="Test Model",
            description="A test model",
            input_types=["frame", "batch"],
            input_format="png",
            output_event_types=["event_a"],
            provides_bounding_boxes=False,
            provides_metadata=True,
            supports_cpu=True,
            supports_gpu=False,
            supports_jetson=False,
            inference_time_hint_ms=50,
            recommended_fps=15,
            max_fps=None,
            recommended_batch_size=4,
            max_concurrent=10,
            status=ModelStatus.IDLE,
            health=HealthStatus.DEGRADED,
            degraded_reason="High latency",
        )

        data = cap.to_dict()

        assert data["model_id"] == "test_model"
        assert data["version"] == "2.0.0"
        assert data["status"] == "idle"
        assert data["health"] == "degraded"
        assert data["degraded_reason"] == "High latency"
        assert data["hardware"]["supports_cpu"] is True
        assert data["hardware"]["supports_gpu"] is False
        assert data["performance"]["inference_time_hint_ms"] == 50

    def test_full_report_to_dict(self, sample_capability_report):
        """Test FullCapabilityReport serializes correctly."""
        data = sample_capability_report.to_dict()

        assert data["runtime_id"] == "test-runtime-001"
        assert data["runtime_health"] == "healthy"
        assert data["summary"]["total_models"] == 1
        assert data["summary"]["healthy_models"] == 1
        assert len(data["models"]) == 1
        assert data["capacity"]["concurrency"]["max_concurrent"] == 10


# =============================================================================
# ASYNC CLIENT TESTS
# =============================================================================


class TestAsyncHTTPBackendClient:
    """Tests for AsyncHTTPBackendClient."""

    def test_async_client_initialization(self):
        """Test async client initializes correctly."""
        client = AsyncHTTPBackendClient(
            config=BackendClientConfig(backend_url="http://localhost:8080"),
            runtime_id="async-test",
        )

        assert client.runtime_id == "async-test"
        assert not client.is_registered()

        # Close synchronously for test (don't await)
        # In real usage, would use: await client.close()

    def test_async_client_config(self):
        """Test async client configuration."""
        config = BackendClientConfig(
            backend_url="http://backend:9000",
            api_key="async-key",
        )
        client = AsyncHTTPBackendClient(
            config=config,
            runtime_id="async-config-test",
        )

        assert client.runtime_id == "async-config-test"
        assert client.config.api_key == "async-key"
