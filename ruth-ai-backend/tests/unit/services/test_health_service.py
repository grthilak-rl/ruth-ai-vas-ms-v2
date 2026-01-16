"""Unit tests for HealthService.

Tests health check functionality for all components:
- Database (PostgreSQL)
- Redis cache
- AI Runtime
- VAS (Video Analytics Service)
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.services.health_service import HealthService
from app.schemas.health import ComponentHealth, HealthStatus


class MockEngine:
    """Mock SQLAlchemy engine for testing."""

    def __init__(self, *, should_fail: bool = False, latency: float = 0.0):
        self._should_fail = should_fail
        self._latency = latency
        self._pool = MockPool()

    @property
    def pool(self):
        return self._pool

    def connect(self):
        """Return an async context manager for the connection."""
        return MockConnectionContext(
            should_fail=self._should_fail,
            latency=self._latency,
        )


class MockPool:
    """Mock connection pool."""

    def size(self) -> int:
        return 10

    def checkedout(self) -> int:
        return 3

    def overflow(self) -> int:
        return 0

    def checkedin(self) -> int:
        return 7


class MockConnectionContext:
    """Mock async context manager for database connection."""

    def __init__(self, *, should_fail: bool = False, latency: float = 0.0):
        self._should_fail = should_fail
        self._latency = latency

    async def __aenter__(self):
        if self._latency > 0:
            await asyncio.sleep(self._latency)
        if self._should_fail:
            raise ConnectionError("Database connection failed")
        return MockConnection()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockConnection:
    """Mock database connection."""

    async def execute(self, query):
        return MagicMock()


class MockRedisClient:
    """Mock Redis client for testing."""

    def __init__(
        self,
        *,
        should_fail: bool = False,
        latency: float = 0.0,
        ping_result: bool = True,
    ):
        self._should_fail = should_fail
        self._latency = latency
        self._ping_result = ping_result

    async def ping(self) -> bool:
        if self._latency > 0:
            await asyncio.sleep(self._latency)
        if self._should_fail:
            from redis.exceptions import RedisError
            raise RedisError("Redis connection failed")
        return self._ping_result

    async def info(self, section: str = "server") -> dict:
        if section == "server":
            return {"uptime_in_seconds": 86400, "redis_version": "7.0.0"}
        elif section == "memory":
            return {"used_memory_human": "1.5MB"}
        elif section == "clients":
            return {"connected_clients": 5}
        return {}


class MockVASClient:
    """Mock VAS client for testing."""

    def __init__(
        self,
        *,
        should_fail: bool = False,
        latency: float = 0.0,
        health_status: str = "healthy",
    ):
        self._should_fail = should_fail
        self._latency = latency
        self._health_status = health_status

    async def get_health(self) -> dict:
        if self._latency > 0:
            await asyncio.sleep(self._latency)
        if self._should_fail:
            from app.integrations.vas.exceptions import VASConnectionError
            raise VASConnectionError("VAS connection failed")
        return {
            "status": self._health_status,
            "service": "VAS Backend",
            "version": "1.0.0",
        }


class MockAIRuntimeClient:
    """Mock AI Runtime client for testing."""

    def __init__(
        self,
        *,
        should_fail: bool = False,
        latency: float = 0.0,
        is_healthy: bool = True,
    ):
        self._should_fail = should_fail
        self._latency = latency
        self._is_healthy = is_healthy

    async def check_health(self, include_models: bool = True):
        from app.integrations.ai_runtime.models import (
            RuntimeHealth,
            RuntimeStatus,
            HardwareType,
            ModelHealth,
            ModelStatus,
        )

        if self._latency > 0:
            await asyncio.sleep(self._latency)
        if self._should_fail:
            from app.integrations.ai_runtime.exceptions import AIRuntimeConnectionError
            raise AIRuntimeConnectionError("AI Runtime connection failed")

        return RuntimeHealth(
            runtime_id="test-runtime-001",
            status=RuntimeStatus.READY if self._is_healthy else RuntimeStatus.ERROR,
            hardware_type=HardwareType.GPU,
            is_healthy=self._is_healthy,
            models=[
                ModelHealth(
                    model_id="fall_detection",
                    version="1.0.0",
                    status=ModelStatus.READY,
                )
            ] if include_models else [],
            error="Runtime error" if not self._is_healthy else None,
        )


class TestHealthServiceDatabase:
    """Tests for database health check."""

    @pytest.mark.asyncio
    async def test_check_database_healthy(self):
        """Test database health check when database is healthy."""
        engine = MockEngine()
        service = HealthService(engine=engine)

        result = await service.check_database(timeout_seconds=5.0)

        assert result.status == "healthy"
        assert result.latency_ms is not None
        assert result.latency_ms >= 0
        assert result.error is None
        assert result.details is not None
        assert "pool_size" in result.details
        assert result.details["pool_size"] == 10

    @pytest.mark.asyncio
    async def test_check_database_unhealthy_connection_error(self):
        """Test database health check when connection fails."""
        engine = MockEngine(should_fail=True)
        service = HealthService(engine=engine)

        result = await service.check_database(timeout_seconds=5.0)

        assert result.status == "unhealthy"
        assert result.error is not None
        assert "Database connection failed" in result.error

    @pytest.mark.asyncio
    async def test_check_database_unhealthy_not_initialized(self):
        """Test database health check when engine is None."""
        service = HealthService(engine=None)

        result = await service.check_database(timeout_seconds=5.0)

        assert result.status == "unhealthy"
        assert result.error == "Database engine not initialized"

    @pytest.mark.asyncio
    async def test_check_database_timeout(self):
        """Test database health check times out properly."""
        engine = MockEngine(latency=2.0)
        service = HealthService(engine=engine)

        result = await service.check_database(timeout_seconds=0.1)

        assert result.status == "unhealthy"
        assert result.error is not None
        assert "timed out" in result.error


class TestHealthServiceRedis:
    """Tests for Redis health check."""

    @pytest.mark.asyncio
    async def test_check_redis_healthy(self):
        """Test Redis health check when Redis is healthy."""
        redis = MockRedisClient()
        service = HealthService(redis_client=redis)

        result = await service.check_redis(timeout_seconds=3.0)

        assert result.status == "healthy"
        assert result.latency_ms is not None
        assert result.error is None
        assert result.details is not None
        assert result.details["used_memory_human"] == "1.5MB"
        assert result.details["connected_clients"] == 5

    @pytest.mark.asyncio
    async def test_check_redis_unhealthy_connection_error(self):
        """Test Redis health check when connection fails."""
        redis = MockRedisClient(should_fail=True)
        service = HealthService(redis_client=redis)

        result = await service.check_redis(timeout_seconds=3.0)

        assert result.status == "unhealthy"
        assert result.error is not None
        assert "Redis connection failed" in result.error

    @pytest.mark.asyncio
    async def test_check_redis_unhealthy_not_initialized(self):
        """Test Redis health check when client is None."""
        service = HealthService(redis_client=None)

        result = await service.check_redis(timeout_seconds=3.0)

        assert result.status == "unhealthy"
        assert result.error == "Redis client not initialized"

    @pytest.mark.asyncio
    async def test_check_redis_timeout(self):
        """Test Redis health check times out properly."""
        redis = MockRedisClient(latency=2.0)
        service = HealthService(redis_client=redis)

        result = await service.check_redis(timeout_seconds=0.1)

        assert result.status == "unhealthy"
        assert result.error is not None
        assert "timed out" in result.error


class TestHealthServiceVAS:
    """Tests for VAS health check."""

    @pytest.mark.asyncio
    async def test_check_vas_healthy(self):
        """Test VAS health check when VAS is healthy."""
        vas = MockVASClient()
        service = HealthService(vas_client=vas)

        result = await service.check_vas(timeout_seconds=5.0)

        assert result.status == "healthy"
        assert result.latency_ms is not None
        assert result.error is None
        assert result.details is not None
        assert result.details["version"] == "1.0.0"
        assert result.details["service"] == "VAS Backend"

    @pytest.mark.asyncio
    async def test_check_vas_unhealthy_connection_error(self):
        """Test VAS health check when connection fails."""
        vas = MockVASClient(should_fail=True)
        service = HealthService(vas_client=vas)

        result = await service.check_vas(timeout_seconds=5.0)

        assert result.status == "unhealthy"
        assert result.error is not None
        assert "VAS unavailable" in result.error

    @pytest.mark.asyncio
    async def test_check_vas_unhealthy_not_initialized(self):
        """Test VAS health check when client is None."""
        service = HealthService(vas_client=None)

        result = await service.check_vas(timeout_seconds=5.0)

        assert result.status == "unhealthy"
        assert result.error == "VAS client not initialized"

    @pytest.mark.asyncio
    async def test_check_vas_degraded(self):
        """Test VAS health check when VAS reports degraded status."""
        vas = MockVASClient(health_status="degraded")
        service = HealthService(vas_client=vas)

        result = await service.check_vas(timeout_seconds=5.0)

        assert result.status == "degraded"
        assert result.error is not None
        assert "degraded" in result.error


class TestHealthServiceAIRuntime:
    """Tests for AI Runtime health check."""

    @pytest.mark.asyncio
    async def test_check_ai_runtime_healthy(self):
        """Test AI Runtime health check when runtime is healthy."""
        ai_runtime = MockAIRuntimeClient()
        service = HealthService(ai_runtime_client=ai_runtime)

        result = await service.check_ai_runtime(timeout_seconds=10.0)

        assert result.status == "healthy"
        assert result.latency_ms is not None
        assert result.error is None
        assert result.details is not None
        assert result.details["runtime_id"] == "test-runtime-001"
        assert result.details["hardware_type"] == "gpu"
        assert "fall_detection" in result.details["models_loaded"]

    @pytest.mark.asyncio
    async def test_check_ai_runtime_unhealthy_connection_error(self):
        """Test AI Runtime health check when connection fails."""
        ai_runtime = MockAIRuntimeClient(should_fail=True)
        service = HealthService(ai_runtime_client=ai_runtime)

        result = await service.check_ai_runtime(timeout_seconds=10.0)

        assert result.status == "unhealthy"
        assert result.error is not None
        assert "AI Runtime unavailable" in result.error

    @pytest.mark.asyncio
    async def test_check_ai_runtime_unhealthy_not_initialized(self):
        """Test AI Runtime health check when client is None."""
        service = HealthService(ai_runtime_client=None)

        result = await service.check_ai_runtime(timeout_seconds=10.0)

        assert result.status == "unhealthy"
        assert result.error == "AI Runtime client not initialized"

    @pytest.mark.asyncio
    async def test_check_ai_runtime_unhealthy_error_state(self):
        """Test AI Runtime health check when runtime reports error."""
        ai_runtime = MockAIRuntimeClient(is_healthy=False)
        service = HealthService(ai_runtime_client=ai_runtime)

        result = await service.check_ai_runtime(timeout_seconds=10.0)

        assert result.status == "unhealthy"
        assert result.error is not None


class TestHealthServiceCheckAll:
    """Tests for check_all concurrent health checks."""

    @pytest.mark.asyncio
    async def test_check_all_healthy(self):
        """Test check_all when all components are healthy."""
        service = HealthService(
            engine=MockEngine(),
            redis_client=MockRedisClient(),
            vas_client=MockVASClient(),
            ai_runtime_client=MockAIRuntimeClient(),
        )

        components = await service.check_all()

        assert len(components) == 4
        assert components["database"].status == "healthy"
        assert components["redis"].status == "healthy"
        assert components["vas"].status == "healthy"
        assert components["ai_runtime"].status == "healthy"

    @pytest.mark.asyncio
    async def test_check_all_partial_failure(self):
        """Test check_all with some components unhealthy."""
        service = HealthService(
            engine=MockEngine(),
            redis_client=MockRedisClient(should_fail=True),
            vas_client=MockVASClient(),
            ai_runtime_client=None,  # Not initialized
        )

        components = await service.check_all()

        assert components["database"].status == "healthy"
        assert components["redis"].status == "unhealthy"
        assert components["vas"].status == "healthy"
        assert components["ai_runtime"].status == "unhealthy"

    @pytest.mark.asyncio
    async def test_check_all_runs_concurrently(self):
        """Test that check_all runs checks concurrently."""
        # Each mock has 0.1s latency
        service = HealthService(
            engine=MockEngine(latency=0.1),
            redis_client=MockRedisClient(latency=0.1),
            vas_client=MockVASClient(latency=0.1),
            ai_runtime_client=MockAIRuntimeClient(latency=0.1),
        )

        import time
        start = time.perf_counter()
        await service.check_all(
            db_timeout=1.0,
            redis_timeout=1.0,
            vas_timeout=1.0,
            ai_runtime_timeout=1.0,
        )
        elapsed = time.perf_counter() - start

        # If running concurrently, should take ~0.1s
        # If sequential, would take ~0.4s
        assert elapsed < 0.3, f"Checks did not run concurrently: {elapsed}s"


class TestHealthServiceOverallStatus:
    """Tests for determine_overall_status."""

    def test_all_healthy(self):
        """Test overall status is healthy when all components are healthy."""
        service = HealthService()
        components = {
            "database": ComponentHealth(status="healthy"),
            "redis": ComponentHealth(status="healthy"),
            "vas": ComponentHealth(status="healthy"),
            "ai_runtime": ComponentHealth(status="healthy"),
        }

        assert service.determine_overall_status(components) == "healthy"

    def test_one_degraded(self):
        """Test overall status is degraded when one component is degraded."""
        service = HealthService()
        components = {
            "database": ComponentHealth(status="healthy"),
            "redis": ComponentHealth(status="healthy"),
            "vas": ComponentHealth(status="degraded"),
            "ai_runtime": ComponentHealth(status="healthy"),
        }

        assert service.determine_overall_status(components) == "degraded"

    def test_one_unhealthy(self):
        """Test overall status is unhealthy when one component is unhealthy."""
        service = HealthService()
        components = {
            "database": ComponentHealth(status="healthy"),
            "redis": ComponentHealth(status="unhealthy"),
            "vas": ComponentHealth(status="healthy"),
            "ai_runtime": ComponentHealth(status="healthy"),
        }

        assert service.determine_overall_status(components) == "unhealthy"

    def test_unhealthy_takes_precedence(self):
        """Test unhealthy takes precedence over degraded."""
        service = HealthService()
        components = {
            "database": ComponentHealth(status="healthy"),
            "redis": ComponentHealth(status="degraded"),
            "vas": ComponentHealth(status="unhealthy"),
            "ai_runtime": ComponentHealth(status="degraded"),
        }

        assert service.determine_overall_status(components) == "unhealthy"


class TestHealthServiceIsReady:
    """Tests for is_ready readiness check."""

    def test_ready_when_database_healthy(self):
        """Test service is ready when database is healthy."""
        service = HealthService()
        components = {
            "database": ComponentHealth(status="healthy"),
            "redis": ComponentHealth(status="unhealthy"),  # Other components can fail
            "vas": ComponentHealth(status="unhealthy"),
            "ai_runtime": ComponentHealth(status="unhealthy"),
        }

        assert service.is_ready(components) is True

    def test_not_ready_when_database_unhealthy(self):
        """Test service is not ready when database is unhealthy."""
        service = HealthService()
        components = {
            "database": ComponentHealth(status="unhealthy"),
            "redis": ComponentHealth(status="healthy"),
            "vas": ComponentHealth(status="healthy"),
            "ai_runtime": ComponentHealth(status="healthy"),
        }

        assert service.is_ready(components) is False

    def test_not_ready_when_database_degraded(self):
        """Test service is not ready when database is degraded."""
        service = HealthService()
        components = {
            "database": ComponentHealth(status="degraded"),
            "redis": ComponentHealth(status="healthy"),
            "vas": ComponentHealth(status="healthy"),
            "ai_runtime": ComponentHealth(status="healthy"),
        }

        assert service.is_ready(components) is False

    def test_not_ready_when_database_missing(self):
        """Test service is not ready when database status is missing."""
        service = HealthService()
        components = {
            "redis": ComponentHealth(status="healthy"),
            "vas": ComponentHealth(status="healthy"),
            "ai_runtime": ComponentHealth(status="healthy"),
        }

        assert service.is_ready(components) is False
