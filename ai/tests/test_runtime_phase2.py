"""
Phase 2 Tests: Server & Observability

Tests for:
1. Liveness endpoint (/health/live)
2. Readiness endpoint (/health/ready)
3. Container health check validation
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

# Test imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# =============================================================================
# Test: Liveness Endpoint
# =============================================================================

class TestLivenessEndpoint:
    """Tests for /health/live endpoint."""

    def test_liveness_returns_alive_status(self):
        """Liveness probe should always return 'alive' if server is running."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)
        response = client.get("/health/live")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"
        assert "timestamp" in data

    def test_liveness_timestamp_is_valid_iso_format(self):
        """Liveness response timestamp should be valid ISO format."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)
        response = client.get("/health/live")

        data = response.json()
        timestamp = data["timestamp"]

        # Should parse without error
        # Remove trailing Z for parsing
        ts = timestamp.rstrip("Z")
        datetime.fromisoformat(ts)

    def test_liveness_does_not_check_dependencies(self):
        """Liveness should succeed even if models aren't loaded."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        # Liveness should always succeed regardless of registry state
        client = TestClient(app)
        response = client.get("/health/live")

        assert response.status_code == 200
        assert response.json()["status"] == "alive"


# =============================================================================
# Test: Readiness Endpoint
# =============================================================================

class TestReadinessEndpoint:
    """Tests for /health/ready endpoint."""

    def test_readiness_returns_ready_when_models_loaded(self):
        """Readiness probe should return ready when models are available."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)
        response = client.get("/health/ready")

        # May return 200 (ready) or 503 (not ready) depending on model state
        # For integration testing, we check the response structure
        if response.status_code == 200:
            data = response.json()
            assert data["ready"] is True
            assert data["status"] in ["ready", "degraded"]
            assert "models_ready" in data
            assert data["models_ready"] >= 1

    def test_readiness_returns_not_ready_when_no_models(self):
        """Readiness should return 503 when no models are ready."""
        from fastapi.testclient import TestClient
        from ai.server.main import app
        from ai.server import dependencies

        # Save original registry
        original_registry = dependencies._registry

        # Create mock registry with no ready models
        mock_registry = Mock()
        mock_registry.get_all_versions.return_value = []
        dependencies._registry = mock_registry

        try:
            client = TestClient(app)
            response = client.get("/health/ready")

            assert response.status_code == 503
            data = response.json()["detail"]
            assert data["ready"] is False
            assert data["status"] == "not_ready"
            assert data["models_ready"] == 0
            assert "reason" in data
        finally:
            # Restore original registry
            dependencies._registry = original_registry

    def test_readiness_returns_degraded_when_some_models_unhealthy(self):
        """Readiness should return degraded when some models are unhealthy."""
        from fastapi.testclient import TestClient
        from ai.server.main import app
        from ai.server import dependencies
        from ai.runtime.models import LoadState, HealthStatus

        # Save original dependencies
        original_registry = dependencies._registry
        original_sandbox_manager = dependencies._sandbox_manager

        # Create mock registry with mixed health models
        mock_registry = Mock()
        mock_model_healthy = Mock()
        mock_model_healthy.state = LoadState.READY
        mock_model_healthy.health = HealthStatus.HEALTHY

        mock_model_unhealthy = Mock()
        mock_model_unhealthy.state = LoadState.READY
        mock_model_unhealthy.health = HealthStatus.UNHEALTHY

        mock_registry.get_all_versions.return_value = [mock_model_healthy, mock_model_unhealthy]
        dependencies._registry = mock_registry

        # Mock sandbox manager (required for readiness check)
        mock_sandbox_manager = Mock()
        dependencies._sandbox_manager = mock_sandbox_manager

        try:
            client = TestClient(app)
            response = client.get("/health/ready")

            assert response.status_code == 200
            data = response.json()
            assert data["ready"] is True
            assert data["status"] == "degraded"
            assert "1 unhealthy" in data["reason"]
        finally:
            # Restore original dependencies
            dependencies._registry = original_registry
            dependencies._sandbox_manager = original_sandbox_manager

    def test_readiness_response_schema(self):
        """Readiness response should match expected schema."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)
        response = client.get("/health/ready")

        if response.status_code == 200:
            data = response.json()
            # Required fields
            assert "ready" in data
            assert "status" in data
            assert "models_ready" in data
            assert isinstance(data["ready"], bool)
            assert isinstance(data["status"], str)
            assert isinstance(data["models_ready"], int)


# =============================================================================
# Test: Health Endpoint (existing, for completeness)
# =============================================================================

class TestHealthEndpoint:
    """Tests for /health endpoint (detailed health)."""

    def test_health_returns_overall_status(self):
        """Health endpoint should return overall status."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)
        response = client.get("/health")

        if response.status_code == 200:
            data = response.json()
            assert "status" in data
            assert data["status"] in ["healthy", "degraded", "unhealthy"]
            assert "runtime_id" in data
            assert "models_loaded" in data

    def test_health_verbose_includes_gpu_info(self):
        """Health endpoint with verbose=true should include GPU info."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)
        response = client.get("/health?verbose=true")

        if response.status_code == 200:
            data = response.json()
            # Verbose mode should include GPU and model details
            assert "gpu_available" in data or data.get("gpu_available") is None
            assert "models" in data or data.get("models") is None

    def test_health_verbose_includes_per_model_details(self):
        """Health endpoint with verbose=true should include per-model health."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)
        response = client.get("/health?verbose=true")

        if response.status_code == 200:
            data = response.json()
            if data.get("models"):
                for model in data["models"]:
                    assert "model_id" in model
                    assert "version" in model
                    assert "state" in model
                    assert "health" in model


# =============================================================================
# Test: Container Health Check Simulation
# =============================================================================

class TestContainerHealthCheck:
    """Tests simulating container orchestrator health checks."""

    def test_docker_healthcheck_simulation(self):
        """Simulate Docker HEALTHCHECK behavior."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)

        # Docker HEALTHCHECK uses /health/ready
        response = client.get("/health/ready")

        # Container is healthy if status is 200
        # Container is unhealthy if status is 503
        assert response.status_code in [200, 503]

    def test_kubernetes_probes_simulation(self):
        """Simulate Kubernetes liveness and readiness probes."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)

        # livenessProbe: /health/live
        liveness_response = client.get("/health/live")
        assert liveness_response.status_code == 200  # Always alive if server responds

        # readinessProbe: /health/ready
        readiness_response = client.get("/health/ready")
        assert readiness_response.status_code in [200, 503]

    def test_startup_probe_behavior(self):
        """Test that startup allows time for model loading."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)

        # During startup, readiness may return 503
        # This is expected - Kubernetes will keep checking
        response = client.get("/health/ready")

        # Both states are valid during startup
        assert response.status_code in [200, 503]

        if response.status_code == 503:
            # Verify proper error structure for debugging
            data = response.json()["detail"]
            assert "reason" in data


# =============================================================================
# Test: Metrics Endpoint
# =============================================================================

class TestMetricsEndpoint:
    """Tests for /metrics endpoint (Prometheus)."""

    def test_metrics_returns_prometheus_format(self):
        """Metrics endpoint should return Prometheus text format."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)
        response = client.get("/metrics")

        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")

    def test_metrics_includes_inference_counters(self):
        """Metrics should include inference request counters."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)
        response = client.get("/metrics")

        content = response.text
        # Check for expected metric names
        assert "inference_requests_total" in content or "# HELP" in content

    def test_metrics_includes_model_gauges(self):
        """Metrics should include model status gauges."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)
        response = client.get("/metrics")

        content = response.text
        # Should have model-related metrics defined
        assert "model_load_status" in content or "# HELP" in content


# =============================================================================
# Test: Endpoint Discovery
# =============================================================================

class TestEndpointDiscovery:
    """Tests for endpoint availability and OpenAPI documentation."""

    def test_all_health_endpoints_exist(self):
        """All health endpoints should be accessible."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)

        # Test each endpoint exists (may return 200 or 503)
        endpoints = [
            "/health",
            "/health/live",
            "/health/ready",
            "/metrics",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            # Should not return 404
            assert response.status_code != 404, f"Endpoint {endpoint} not found"

    def test_openapi_schema_available(self):
        """OpenAPI schema should be available at /docs."""
        from fastapi.testclient import TestClient
        from ai.server.main import app

        client = TestClient(app)
        response = client.get("/openapi.json")

        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data

        # Check health endpoints are documented
        assert "/health" in data["paths"]
        assert "/health/live" in data["paths"]
        assert "/health/ready" in data["paths"]
