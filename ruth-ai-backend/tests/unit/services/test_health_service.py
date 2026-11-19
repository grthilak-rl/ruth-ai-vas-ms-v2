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


class TestHealthServiceCheckAll:
    """Tests for check_all concurrent health checks."""

    @pytest.mark.asyncio
    async def test_check_all_healthy(self):
        """Test check_all when all components are healthy."""
        service = HealthService(
            engine=MockEngine(),
            redis_client=MockRedisClient(),
            vas_client=MockVASClient(),
        )

        components = await service.check_all()

        assert components["database"].status == "healthy"
        assert components["redis"].status == "healthy"
        assert components["vas"].status == "healthy"

    @pytest.mark.asyncio
    async def test_check_all_partial_failure(self):
        """Test check_all with some components unhealthy."""
        service = HealthService(
            engine=MockEngine(),
            redis_client=MockRedisClient(should_fail=True),
            vas_client=MockVASClient(),
        )

        components = await service.check_all()

        assert components["database"].status == "healthy"
        assert components["redis"].status == "unhealthy"
        assert components["vas"].status == "healthy"

    @pytest.mark.asyncio
    async def test_check_all_runs_concurrently(self):
        """check_all runs the component checks concurrently.

        Proven by structure, not by wall-clock time (an elapsed-time bound
        failed under CPU load, e.g. with live inference running): each
        mocked check waits at a rendezvous until all three are inside at
        once. Concurrent checks meet there immediately. Sequential checks
        never would: the first waits in vain, and the peak stays 1.
        """
        gate = _Rendezvous(3)
        service = HealthService(
            engine=_GatedEngine(gate),
            redis_client=_gated(MockRedisClient(), "ping", gate),
            vas_client=_gated(MockVASClient(), "get_health", gate),
        )

        components = await service.check_all(
            db_timeout=30.0,
            redis_timeout=30.0,
            vas_timeout=30.0,
            ai_runtime_timeout=30.0,
        )

        assert gate.peak == 3, f"checks did not overlap (peak {gate.peak} of 3 in flight)"
        assert components["database"].status == "healthy"
        assert components["redis"].status == "healthy"
        assert components["vas"].status == "healthy"


class _Rendezvous:
    """Each caller waits until `n` callers are inside at the same time.

    The wait is bounded so a sequential implementation fails the peak
    assertion instead of hanging; it never delays a concurrent one."""

    def __init__(self, n: int, give_up_after: float = 5.0):
        self.n = n
        self.inside = 0
        self.peak = 0
        self._all_in = asyncio.Event()
        self._give_up_after = give_up_after

    async def __call__(self) -> None:
        self.inside += 1
        self.peak = max(self.peak, self.inside)
        if self.inside >= self.n:
            self._all_in.set()
        try:
            await asyncio.wait_for(self._all_in.wait(), timeout=self._give_up_after)
        except asyncio.TimeoutError:
            pass
        finally:
            self.inside -= 1


class _GatedEngine(MockEngine):
    """MockEngine whose connect() passes through the rendezvous first."""

    def __init__(self, gate: _Rendezvous):
        super().__init__()
        self._gate = gate

    def connect(self):
        inner, gate = super().connect(), self._gate

        class _Ctx:
            async def __aenter__(self):
                await gate()
                return await inner.__aenter__()

            async def __aexit__(self, *exc):
                return await inner.__aexit__(*exc)

        return _Ctx()


def _gated(client, method: str, gate: _Rendezvous):
    """Make `client.<method>` pass through the rendezvous first."""
    original = getattr(client, method)

    async def wrapper(*args, **kwargs):
        await gate()
        return await original(*args, **kwargs)

    setattr(client, method, wrapper)
    return client


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
