"""Health check service for Ruth AI Backend.

Performs real connectivity and health validation for:
- PostgreSQL database
- Redis cache
- AI Runtime
- VAS (Video Analytics Service)

All checks are async and implement proper timeouts.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.integrations.ai_runtime import AIRuntimeClient
from app.integrations.ai_runtime.exceptions import AIRuntimeError
from app.integrations.vas import VASClient
from app.integrations.vas.exceptions import VASError
from app.schemas.health import (
    AIRuntimeDetails,
    ComponentHealth,
    DatabaseDetails,
    HealthResponse,
    HealthStatus,
    NLPChatDetails,
    RedisDetails,
    VASDetails,
)

logger = get_logger(__name__)


class HealthService:
    """Service for performing health checks on all dependencies.

    All checks implement configurable timeouts to prevent blocking.
    Results include latency measurements and component-specific details.
    """

    def __init__(
        self,
        *,
        engine: AsyncEngine | None = None,
        redis_client: Redis | None = None,
        vas_client: VASClient | None = None,
        ai_runtime_client: AIRuntimeClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Initialize health service with optional dependencies.

        Args:
            engine: SQLAlchemy async engine for database checks
            redis_client: Redis async client for cache checks
            vas_client: VAS client for video service checks
            ai_runtime_client: AI Runtime client for inference service checks
            settings: Application settings (uses get_settings() if not provided)
        """
        self._engine = engine
        self._redis = redis_client
        self._vas_client = vas_client
        self._ai_runtime_client = ai_runtime_client
        self._settings = settings or get_settings()

    async def check_database(
        self,
        timeout_seconds: float = 5.0,
    ) -> ComponentHealth:
        """Check PostgreSQL database connectivity.

        Executes SELECT 1 query and measures latency.
        Includes connection pool statistics in details.

        Args:
            timeout_seconds: Maximum time to wait for response

        Returns:
            ComponentHealth with status, latency, and pool stats
        """
        if self._engine is None:
            return ComponentHealth(
                status="unhealthy",
                error="Database engine not initialized",
            )

        start_time = time.perf_counter()

        try:
            async with asyncio.timeout(timeout_seconds):
                async with self._engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Get pool statistics
            pool = self._engine.pool
            details: dict[str, Any] = {}

            if pool is not None:
                details = DatabaseDetails(
                    pool_size=pool.size(),
                    pool_checkedout=pool.checkedout(),
                    pool_overflow=pool.overflow(),
                    pool_checkedin=pool.checkedin(),
                ).model_dump(exclude_none=True)

            return ComponentHealth(
                status="healthy",
                latency_ms=latency_ms,
                details=details if details else None,
            )

        except asyncio.TimeoutError:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(
                "Database health check timed out",
                timeout_seconds=timeout_seconds,
            )
            return ComponentHealth(
                status="unhealthy",
                latency_ms=latency_ms,
                error=f"Database health check timed out after {timeout_seconds}s",
            )

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("Database health check failed", error=str(e))
            return ComponentHealth(
                status="unhealthy",
                latency_ms=latency_ms,
                error=f"Database connection failed: {type(e).__name__}",
            )

    async def check_redis(
        self,
        timeout_seconds: float = 3.0,
    ) -> ComponentHealth:
        """Check Redis cache connectivity.

        Executes PING command and retrieves server info.

        Args:
            timeout_seconds: Maximum time to wait for response

        Returns:
            ComponentHealth with status, latency, and memory stats
        """
        if self._redis is None:
            return ComponentHealth(
                status="unhealthy",
                error="Redis client not initialized",
            )

        start_time = time.perf_counter()

        try:
            async with asyncio.timeout(timeout_seconds):
                # Execute PING
                pong = await self._redis.ping()

                if not pong:
                    raise RedisError("PING returned False")

                # Get server info for details
                info = await self._redis.info(section="server")
                memory_info = await self._redis.info(section="memory")
                clients_info = await self._redis.info(section="clients")

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            details = RedisDetails(
                used_memory_human=memory_info.get("used_memory_human"),
                connected_clients=clients_info.get("connected_clients"),
                uptime_in_seconds=info.get("uptime_in_seconds"),
                redis_version=info.get("redis_version"),
            ).model_dump(exclude_none=True)

            return ComponentHealth(
                status="healthy",
                latency_ms=latency_ms,
                details=details if details else None,
            )

        except asyncio.TimeoutError:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(
                "Redis health check timed out",
                timeout_seconds=timeout_seconds,
            )
            return ComponentHealth(
                status="unhealthy",
                latency_ms=latency_ms,
                error=f"Redis health check timed out after {timeout_seconds}s",
            )

        except RedisError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("Redis health check failed", error=str(e))
            return ComponentHealth(
                status="unhealthy",
                latency_ms=latency_ms,
                error=f"Redis connection failed: {type(e).__name__}",
            )

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("Redis health check failed unexpectedly", error=str(e))
            return ComponentHealth(
                status="unhealthy",
                latency_ms=latency_ms,
                error=f"Redis error: {type(e).__name__}",
            )

    async def check_ai_runtime(
        self,
        timeout_seconds: float = 10.0,
    ) -> ComponentHealth:
        """Check AI Runtime service health.

        Uses the internal runtime registry to check if any AI runtimes
        are registered and healthy.

        Args:
            timeout_seconds: Maximum time to wait for response

        Returns:
            ComponentHealth with status, latency, and model info
        """
        # Import here to avoid circular imports
        from app.api.internal.ai_runtime import _registered_runtimes

        start_time = time.perf_counter()

        try:
            # Check registered runtimes from internal registry
            if not _registered_runtimes:
                return ComponentHealth(
                    status="unhealthy",
                    error="No AI Runtimes registered",
                )

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Get first registered runtime (usually only one)
            runtime = next(iter(_registered_runtimes.values()))

            # Extract model IDs from runtime
            models_loaded: list[str] = []
            for model in runtime.models:
                model_id = model.get("model_id")
                if model_id:
                    models_loaded.append(model_id)

            details = AIRuntimeDetails(
                runtime_id=runtime.runtime_id,
                models_loaded=models_loaded if models_loaded else None,
                gpu_available=None,  # Not tracked in registry yet
                hardware_type=None,
            ).model_dump(exclude_none=True)

            # Determine status based on runtime health
            status: HealthStatus = "healthy"
            error: str | None = None

            if runtime.runtime_health == "unhealthy":
                status = "unhealthy"
                error = "AI Runtime unhealthy"
            elif runtime.runtime_health == "degraded":
                status = "degraded"
                error = "AI Runtime degraded"
            elif runtime.runtime_health == "unknown":
                status = "degraded"
                error = "AI Runtime health unknown"

            return ComponentHealth(
                status=status,
                latency_ms=latency_ms,
                error=error,
                details=details if details else None,
            )

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("AI Runtime health check failed", error=str(e))
            return ComponentHealth(
                status="unhealthy",
                latency_ms=latency_ms,
                error=f"AI Runtime error: {type(e).__name__}",
            )

    async def check_vas(
        self,
        timeout_seconds: float = 5.0,
    ) -> ComponentHealth:
        """Check VAS (Video Analytics Service) health.

        Calls the VAS health endpoint to verify connectivity.

        Args:
            timeout_seconds: Maximum time to wait for response

        Returns:
            ComponentHealth with status, latency, and service info
        """
        if self._vas_client is None:
            return ComponentHealth(
                status="unhealthy",
                error="VAS client not initialized",
            )

        start_time = time.perf_counter()

        try:
            async with asyncio.timeout(timeout_seconds):
                health_data = await self._vas_client.get_health()

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Extract details from VAS health response
            vas_status = health_data.get("status", "unknown")

            details = VASDetails(
                version=health_data.get("version"),
                service=health_data.get("service"),
            ).model_dump(exclude_none=True)

            # Determine health status
            status: HealthStatus = "healthy"
            error: str | None = None

            if vas_status != "healthy":
                status = "unhealthy" if vas_status == "unhealthy" else "degraded"
                error = f"VAS reported status: {vas_status}"

            return ComponentHealth(
                status=status,
                latency_ms=latency_ms,
                error=error,
                details=details if details else None,
            )

        except asyncio.TimeoutError:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(
                "VAS health check timed out",
                timeout_seconds=timeout_seconds,
            )
            return ComponentHealth(
                status="unhealthy",
                latency_ms=latency_ms,
                error=f"VAS health check timed out after {timeout_seconds}s",
            )

        except VASError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("VAS health check failed", error=str(e))
            return ComponentHealth(
                status="unhealthy",
                latency_ms=latency_ms,
                error=f"VAS unavailable: {type(e).__name__}",
            )

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("VAS health check failed unexpectedly", error=str(e))
            return ComponentHealth(
                status="unhealthy",
                latency_ms=latency_ms,
                error=f"VAS error: {type(e).__name__}",
            )

    async def check_nlp_chat(
        self,
        timeout_seconds: float = 5.0,
    ) -> ComponentHealth:
        """Check NLP Chat Service health.

        Calls the NLP Chat Service health endpoint to verify connectivity
        and LLM availability.

        Args:
            timeout_seconds: Maximum time to wait for response

        Returns:
            ComponentHealth with status, latency, and service info
        """
        nlp_chat_url = self._settings.nlp_chat_service_url
        if not nlp_chat_url:
            return ComponentHealth(
                status="degraded",
                error="NLP Chat Service URL not configured",
            )

        start_time = time.perf_counter()

        try:
            async with asyncio.timeout(timeout_seconds):
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{nlp_chat_url}/health")
                    response.raise_for_status()
                    health_data = response.json()

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Extract details from NLP Chat health response
            nlp_status = health_data.get("status", "unknown")
            components_data = health_data.get("components", {})

            # Get Ollama status if available
            ollama_component = components_data.get("ollama", {})
            ollama_status = ollama_component.get("status", "unknown")

            details = NLPChatDetails(
                version=health_data.get("version"),
                service=health_data.get("service"),
                enabled=True,  # If we can reach it, it's enabled
                ollama_status=ollama_status,
            ).model_dump(exclude_none=True)

            # Determine health status
            status: HealthStatus = "healthy"
            error: str | None = None

            if nlp_status == "unhealthy":
                status = "unhealthy"
                error = "NLP Chat Service reported unhealthy"
            elif nlp_status == "degraded":
                status = "degraded"
                error = "NLP Chat Service reported degraded (check LLM models)"
            elif nlp_status != "healthy":
                status = "degraded"
                error = f"NLP Chat Service reported status: {nlp_status}"

            return ComponentHealth(
                status=status,
                latency_ms=latency_ms,
                error=error,
                details=details if details else None,
            )

        except asyncio.TimeoutError:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(
                "NLP Chat health check timed out",
                timeout_seconds=timeout_seconds,
            )
            return ComponentHealth(
                status="unhealthy",
                latency_ms=latency_ms,
                error=f"NLP Chat health check timed out after {timeout_seconds}s",
            )

        except httpx.HTTPStatusError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("NLP Chat health check failed", error=str(e))
            return ComponentHealth(
                status="unhealthy",
                latency_ms=latency_ms,
                error=f"NLP Chat Service returned HTTP {e.response.status_code}",
            )

        except httpx.RequestError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("NLP Chat health check connection failed", error=str(e))
            return ComponentHealth(
                status="unhealthy",
                latency_ms=latency_ms,
                error="NLP Chat Service unavailable",
            )

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("NLP Chat health check failed unexpectedly", error=str(e))
            return ComponentHealth(
                status="unhealthy",
                latency_ms=latency_ms,
                error=f"NLP Chat error: {type(e).__name__}",
            )

    async def check_all(
        self,
        *,
        db_timeout: float = 5.0,
        redis_timeout: float = 3.0,
        ai_runtime_timeout: float = 10.0,
        vas_timeout: float = 5.0,
        nlp_chat_timeout: float = 5.0,
    ) -> dict[str, ComponentHealth]:
        """Check all components concurrently.

        Runs all health checks in parallel for efficiency.
        Individual timeouts are applied per component.

        Args:
            db_timeout: Database check timeout
            redis_timeout: Redis check timeout
            ai_runtime_timeout: AI Runtime check timeout
            vas_timeout: VAS check timeout
            nlp_chat_timeout: NLP Chat Service check timeout

        Returns:
            Dictionary mapping component names to health status
        """
        # Run all checks concurrently
        results = await asyncio.gather(
            self.check_database(timeout_seconds=db_timeout),
            self.check_redis(timeout_seconds=redis_timeout),
            self.check_ai_runtime(timeout_seconds=ai_runtime_timeout),
            self.check_vas(timeout_seconds=vas_timeout),
            self.check_nlp_chat(timeout_seconds=nlp_chat_timeout),
            return_exceptions=True,
        )

        components: dict[str, ComponentHealth] = {}

        # Process results (handle any unexpected exceptions)
        component_names = ["database", "redis", "ai_runtime", "vas", "nlp_chat"]
        for name, result in zip(component_names, results):
            if isinstance(result, Exception):
                logger.error(
                    f"Unexpected error in {name} health check",
                    error=str(result),
                )
                components[name] = ComponentHealth(
                    status="unhealthy",
                    error=f"Health check failed: {type(result).__name__}",
                )
            else:
                components[name] = result

        return components

    def determine_overall_status(
        self,
        components: dict[str, ComponentHealth],
    ) -> HealthStatus:
        """Determine overall health status from component statuses.

        Priority: unhealthy > degraded > healthy

        Args:
            components: Dictionary of component health statuses

        Returns:
            Overall health status
        """
        statuses = [c.status for c in components.values()]

        if "unhealthy" in statuses:
            return "unhealthy"
        if "degraded" in statuses:
            return "degraded"
        return "healthy"

    def is_ready(self, components: dict[str, ComponentHealth]) -> bool:
        """Check if the service is ready to accept requests.

        Readiness requires database to be healthy at minimum.
        Other components being unhealthy results in degraded mode.

        Args:
            components: Dictionary of component health statuses

        Returns:
            True if service can accept requests
        """
        db_health = components.get("database")
        return db_health is not None and db_health.status == "healthy"
