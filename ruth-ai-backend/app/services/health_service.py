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
from app.integrations.vas import VASClient
from app.integrations.vas.exceptions import VASError
from app.schemas.health import (
    AIRuntimeDetails,
    CameraModelsDetails,
    ComponentHealth,
    DatabaseDetails,
    HealthResponse,
    HealthStatus,
    ModelStoreRuntimeDetails,
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
        settings: Settings | None = None,
    ) -> None:
        """Initialize health service with optional dependencies.

        Args:
            engine: SQLAlchemy async engine for database checks
            redis_client: Redis async client for cache checks
            vas_client: VAS client for video service checks
            settings: Application settings (uses get_settings() if not provided)
        """
        self._engine = engine
        self._redis = redis_client
        self._vas_client = vas_client
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

    # Upper bound for the live /health probe of the built-in AI runtime.
    AI_RUNTIME_PROBE_TIMEOUT_SECONDS = 5.0

    async def _probe_ai_runtime(
        self, timeout_seconds: float
    ) -> tuple[bool, dict[str, Any], str | None]:
        """GET the unified runtime's /health?verbose=true.

        Returns (reachable, body, error). Never raises. Any HTTP response with
        a JSON body counts as reachable (the runtime answers 503 while it is
        still initialising); connection errors and timeouts do not.
        """
        url = f"{self._settings.unified_runtime_url}/health"
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(url, params={"verbose": "true"})
            try:
                body = response.json()
            except ValueError:
                return False, {}, f"HTTP {response.status_code} with non-JSON body"
            if response.status_code >= 500 and "status" not in body:
                body = {"status": "unhealthy", "reasons": [str(body.get("detail", body))]}
            return True, body if isinstance(body, dict) else {}, None
        except httpx.TimeoutException:
            return False, {}, f"no response within {timeout_seconds:.0f}s"
        except httpx.HTTPError as e:
            return False, {}, f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        except Exception as e:  # never let the probe break health checks
            return False, {}, f"{type(e).__name__}: {e}"

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
        from app.api.internal.ai_runtime import _registered_runtimes as _all_runtimes
        from app.integrations.unified_runtime.config import get_unified_runtime_config

        # The model store runtime (uploaded models) is never "the AI runtime":
        # system health reflects the built-in runtime only. Without a store
        # runtime registered this is the full registry, as before.
        store_runtime_id = get_unified_runtime_config().model_store_runtime_id
        _registered_runtimes = {
            rid: reg for rid, reg in _all_runtimes.items() if rid != store_runtime_id
        }

        # Retired on purpose (UNIFIED_RUNTIME_IN_USE=false): every built-in
        # model is gone and all inference runs in the model store runtime,
        # which has its own component. Left out of overall health, with no
        # network call, like the other disabled components. With the flag on,
        # a runtime with no models is still judged (unhealthy) as before.
        if not get_unified_runtime_config().unified_runtime_in_use:
            return ComponentHealth(
                status="disabled",
                details=AIRuntimeDetails(
                    reasons=["not in use: UNIFIED_RUNTIME_IN_USE=false (built-in models retired; "
                             "inference runs in the model store runtime)"],
                ).model_dump(exclude_none=True),
            )

        start_time = time.perf_counter()

        try:
            # First registered runtime (usually only one). The registry is in
            # memory: right after this backend restarts it is empty until the
            # runtime's next capability publish (<= ~60 s). An empty registry
            # alone is therefore not an outage; the live probe below decides.
            runtime = next(iter(_registered_runtimes.values()), None)

            # Extract model IDs from runtime
            models_loaded: list[str] = []
            for model in (runtime.models if runtime else []):
                model_id = model.get("model_id")
                if model_id:
                    models_loaded.append(model_id)

            # Live probe. The registry only holds the last pushed state, so a
            # runtime that crashed (or never restarted after a reboot) would
            # otherwise stay "healthy" here, and the runtime's own push never
            # considered the GPU at all.
            probe_ok, probe, probe_error = await self._probe_ai_runtime(
                min(timeout_seconds, self.AI_RUNTIME_PROBE_TIMEOUT_SECONDS)
            )
            latency_ms = int((time.perf_counter() - start_time) * 1000)

            if not probe_ok:
                details = AIRuntimeDetails(
                    runtime_id=runtime.runtime_id if runtime else None,
                    models_loaded=models_loaded or None,
                    reachable=False,
                ).model_dump(exclude_none=True)
                return ComponentHealth(
                    status="unhealthy",
                    latency_ms=latency_ms,
                    error=f"AI Runtime unreachable: {probe_error}"
                    + ("" if runtime else " (and not registered)"),
                    details=details,
                )

            if runtime is None:
                # Not registered yet: take what we can from the probe.
                models_loaded = [
                    m["model_id"]
                    for m in (probe.get("models") or [])
                    if isinstance(m, dict) and m.get("model_id") and m.get("state") == "ready"
                ]

            gpu_available = probe.get("gpu_available")
            # Runtimes older than the gpu_expected field are GPU deployments.
            gpu_expected = probe.get("gpu_expected", True)
            reasons = [r for r in (probe.get("reasons") or []) if isinstance(r, str)]
            models_on_cpu = [
                f"{m.get('model_id')}:{m.get('version')}"
                for m in (probe.get("models") or [])
                if isinstance(m, dict) and m.get("device") == "cpu"
            ] if gpu_expected else []

            details = AIRuntimeDetails(
                runtime_id=runtime.runtime_id if runtime else probe.get("runtime_id"),
                models_loaded=models_loaded or None,
                gpu_available=gpu_available,
                hardware_type=(
                    "cuda" if gpu_available else ("cpu" if gpu_available is False else None)
                ),
                reachable=True,
                gpu_expected=gpu_expected,
                gpu_reason=probe.get("gpu_reason"),
                reasons=reasons or None,
                models_on_cpu=models_on_cpu or None,
            ).model_dump(exclude_none=True)

            # Worst of: GPU state, live probe status, pushed registry status.
            status: HealthStatus = "healthy"
            error: str | None = None

            if gpu_expected and gpu_available is False:
                status = "unhealthy"
                error = (
                    "GPU unavailable - AI inference is not running on the GPU"
                    + (f": {probe['gpu_reason']}" if probe.get("gpu_reason") else "")
                )
            elif probe.get("status") == "unhealthy":
                status = "unhealthy"
                error = "AI Runtime unhealthy" + (f": {'; '.join(reasons)}" if reasons else "")
            elif models_on_cpu:
                status = "degraded"
                error = f"Models running on CPU: {', '.join(models_on_cpu)}"
            elif probe.get("status") == "degraded":
                status = "degraded"
                error = "AI Runtime degraded" + (f": {'; '.join(reasons)}" if reasons else "")

            if status == "healthy" and runtime is None:
                status = "degraded"
                error = (
                    "AI Runtime not registered yet (live probe OK; it "
                    "re-registers within ~60 s of a backend restart)"
                )
            elif status == "healthy":
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

    async def check_camera_models(self, timeout_seconds: float = 5.0) -> ComponentHealth:
        """Is every model on every camera working?

        A model can fail on every frame while its session reads as live (the
        retired geo_fencing did for 22 minutes on 2026-11-19, with everything
        here healthy). Status mapping:

        * every model running -> ``healthy``
        * any model failing (no result for 60 s) or unavailable (not
          installed, including saved models a resume left out) -> ``degraded``
        * the check itself cannot run -> ``degraded`` with the error

        Degraded, not unhealthy: one camera's model is a real problem for
        that camera, not an outage of the core system.
        """
        from app.core.database import get_session_factory
        from app.services.camera_model_status import STATUS_RUNNING, camera_model_statuses

        start = time.perf_counter()
        factory = get_session_factory()
        if factory is None:
            return ComponentHealth(status="degraded", error="database not initialised")
        try:
            async with factory() as db:
                statuses = await asyncio.wait_for(camera_model_statuses(db), timeout=timeout_seconds)
        except Exception as e:  # noqa: BLE001 - a health check never raises
            return ComponentHealth(
                status="degraded",
                latency_ms=int((time.perf_counter() - start) * 1000),
                error=f"Camera model check failed: {type(e).__name__}: {e}"[:300],
            )
        problems = [s for s in statuses if s.status != STATUS_RUNNING]
        details = CameraModelsDetails(
            cameras=len({s.device_id for s in statuses}),
            models=len(statuses),
            failing=sum(s.status == "failing" for s in problems),
            unavailable=sum(s.status == "unavailable" for s in problems),
            problems=[s.as_dict() for s in problems],
        )
        latency = int((time.perf_counter() - start) * 1000)
        if not problems:
            return ComponentHealth(status="healthy", latency_ms=latency, details=details.model_dump())
        first = problems[0]
        more = f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""
        return ComponentHealth(
            status="degraded",
            latency_ms=latency,
            error=f"{first.camera}: {first.model_id} {first.status}: {first.message}{more}",
            details=details.model_dump(),
        )

    async def check_model_store_runtime(self) -> ComponentHealth:
        """Check the model store runtime (uploaded models).

        Separate from ``check_ai_runtime`` on purpose: the store runtime is
        never "the AI runtime", and this check does not touch that one's
        result. It exists because the store runtime once sat unreachable for
        twelve days while every surface degraded silently — see
        ``app.services.model_store.runtime_probe``.

        Status mapping:

        * not configured -> ``disabled`` (excluded from overall health)
        * reachable, all models ready -> ``healthy``
        * reachable, some models not ready -> ``degraded``
        * unreachable -> ``degraded``, with ``details.reachable = False``

        Unreachable is deliberately ``degraded`` rather than ``unhealthy``:
        uploaded models being unavailable is a real outage for the people
        using them, but the core system is fine, and flipping overall health
        to ``unhealthy`` would trip alerting tuned for database and runtime
        failures. The UI reads ``details.reachable`` to render this case red
        ("Unreachable") while a partially-ready store stays amber.

        Returns:
            ComponentHealth for the ``model_store_runtime`` component
        """
        from app.services.model_store.runtime_probe import probe_store_runtime

        start_time = time.perf_counter()
        probe = await probe_store_runtime()
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        if not probe.configured:
            # Feature off in this deployment. Not a fault, and excluded from
            # the overall status, exactly like a disabled NLP chat service.
            return ComponentHealth(
                status="disabled",
                details=ModelStoreRuntimeDetails(configured=False).model_dump(
                    exclude_none=True
                ),
            )

        last_success = (
            probe.last_success_at.isoformat() if probe.last_success_at else None
        )
        ready_ids = [
            mid for mid in probe.model_ids if mid not in probe.not_ready_ids
        ]
        details = ModelStoreRuntimeDetails(
            configured=True,
            reachable=probe.reachable,
            runtime_id=probe.runtime_id or None,
            url=probe.runtime_url or None,
            models_ready=probe.ready,
            models_total=probe.total,
            models_loaded=ready_ids or None,
            models_not_ready=list(probe.not_ready_ids) or None,
            last_success_at=last_success,
        ).model_dump(exclude_none=True)

        if not probe.reachable:
            return ComponentHealth(
                status="degraded",
                latency_ms=latency_ms,
                error=probe.error or "Model store runtime unreachable",
                details=details,
            )

        if probe.partially_ready:
            return ComponentHealth(
                status="degraded",
                latency_ms=latency_ms,
                error=f"{probe.ready}/{probe.total} models ready",
                details=details,
            )

        return ComponentHealth(
            status="healthy",
            latency_ms=latency_ms,
            details=details,
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

        If NLP Chat is intentionally disabled in this deployment
        (``nlp_chat_enabled=False``), the check returns status
        ``"disabled"`` without performing any network calls. Disabled
        components do not contribute to the overall health status.

        Args:
            timeout_seconds: Maximum time to wait for response

        Returns:
            ComponentHealth with status, latency, and service info
        """
        if not self._settings.nlp_chat_enabled:
            return ComponentHealth(
                status="disabled",
                error=None,
                details=NLPChatDetails(enabled=False).model_dump(exclude_none=True),
            )

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
            # Own timeout lives in the probe (PROBE_TIMEOUT_SECONDS); it
            # never raises, so it cannot delay or break the others.
            self.check_model_store_runtime(),
            self.check_camera_models(),
            return_exceptions=True,
        )

        components: dict[str, ComponentHealth] = {}

        # Process results (handle any unexpected exceptions)
        component_names = [
            "database",
            "redis",
            "ai_runtime",
            "vas",
            "nlp_chat",
            "model_store_runtime",
            "camera_models",
        ]
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

        Priority: unhealthy > degraded > healthy.

        Components with status ``"disabled"`` are intentionally not part
        of this deployment and do not contribute to the overall result.

        Args:
            components: Dictionary of component health statuses

        Returns:
            Overall health status
        """
        statuses = [
            c.status for c in components.values() if c.status != "disabled"
        ]

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
