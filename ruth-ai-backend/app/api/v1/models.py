"""Models API endpoints.

From API Contract - Models APIs:
- GET    /models/status

Provides AI model status information for the frontend.
Aligned with F6 §4.3 Models Domain.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, status
from sqlalchemy import func, or_, select

from app.core.logging import get_logger
from app.deps import DBSession
from app.models import StreamSession, StreamState
from app.schemas import ErrorResponse, ModelStatusInfo, ModelsStatusResponse
from app.integrations.unified_runtime.client import (
    UnifiedRuntimeClient,
    UnifiedRuntimeConnectionError,
)
from app.integrations.unified_runtime.config import get_unified_runtime_config
from app.services.model_store.enabled import enabled_store_models
from app.services.model_store.ids import RESERVED_MODEL_IDS

router = APIRouter(tags=["Models"])
logger = get_logger(__name__)


@router.get(
    "/models/status",
    response_model=ModelsStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get AI models status",
    description="Returns status of all registered AI models.",
    responses={
        200: {"model": ModelsStatusResponse, "description": "Models status"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
    # Omit fields an entry doesn't set: built-in entries set exactly the
    # original fields, so they serialize as before; store entries add theirs.
    response_model_exclude_unset=True,
)
async def get_models_status(
    db: DBSession,
) -> ModelsStatusResponse:
    """Get status of all AI models.

    Returns operational status, health, and activity metrics for each
    registered AI model. Queries unified runtime for available models
    and enriches with usage data from stream sessions.

    Args:
        db: Database session

    Returns:
        List of model statuses
    """
    config = get_unified_runtime_config()
    models = []

    # Query unified runtime for available models
    runtime_models = {}
    if config.enable_unified_runtime:
        try:
            async with UnifiedRuntimeClient() as client:
                capabilities = await client.get_capabilities()
                runtime_models = {
                    model["model_id"]: model
                    for model in capabilities.get("models", [])
                }
                logger.info(
                    "Retrieved unified runtime models",
                    count=len(runtime_models),
                )
        except UnifiedRuntimeConnectionError as e:
            logger.warning(
                "Failed to connect to unified runtime",
                error=str(e),
            )
        except Exception as e:
            logger.error(
                "Unexpected error querying unified runtime",
                error=str(e),
            )

    # Filter out test/development models
    test_model_prefixes = ["broken_", "dummy_", "test_"]
    production_models = {
        model_id: model_info
        for model_id, model_info in runtime_models.items()
        if not any(model_id.startswith(prefix) for prefix in test_model_prefixes)
        and model_info.get("state") != "invalid"  # Also filter invalid models
    }

    logger.info(
        "Filtered models",
        total=len(runtime_models),
        production=len(production_models),
        filtered_out=len(runtime_models) - len(production_models),
    )

    # Build model status for each discovered model
    for model_id, model_info in production_models.items():
        # Count active cameras using this model
        active_sessions_stmt = (
            select(func.count())
            .select_from(StreamSession)
            .where(StreamSession.state == StreamState.LIVE)
            .where(StreamSession.model_id == model_id)
        )
        result = await db.execute(active_sessions_stmt)
        cameras_active = result.scalar() or 0

        # Get most recent inference time
        last_session_stmt = (
            select(StreamSession.started_at)
            .where(StreamSession.model_id == model_id)
            .order_by(StreamSession.started_at.desc())
            .limit(1)
        )
        result = await db.execute(last_session_stmt)
        last_started = result.scalar()

        # Map unified runtime state to API status
        runtime_state = model_info.get("state", "unknown")
        runtime_health = model_info.get("health", "unknown")

        # Determine status based on runtime state and activity
        if runtime_state == "ready":
            model_status = "active" if cameras_active > 0 else "idle"
        elif runtime_state == "loading":
            model_status = "starting"
        elif runtime_state == "failed":
            model_status = "error"
        else:
            model_status = "idle"

        # Map runtime health to API health
        if runtime_health == "healthy":
            health_status = "healthy"
        elif runtime_health == "degraded":
            health_status = "degraded"
        elif runtime_health == "unknown":
            # Unknown health treated as healthy if model is ready
            health_status = "healthy" if runtime_state == "ready" else "unhealthy"
        else:
            health_status = "unhealthy"

        models.append(
            ModelStatusInfo(
                model_id=model_id,
                version=model_info.get("version", "1.0.0"),
                status=model_status,
                health=health_status,
                cameras_active=cameras_active,
                last_inference_at=last_started,
                started_at=last_started,
            )
        )

    # Uploaded models served by the model store runtime, appended after the
    # built-in ones. Off (and the response exactly as above) unless
    # MODEL_STORE_RUNTIME_URL is set.
    if config.model_store_runtime_url:
        models.extend(
            await _store_model_statuses(
                db,
                config.model_store_runtime_url,
                skip=set(production_models),
                test_model_prefixes=test_model_prefixes,
            )
        )

    logger.info(
        "Retrieved model statuses",
        count=len(models),
        unified_runtime_count=len(runtime_models),
    )

    return ModelsStatusResponse(models=models)


#: Short: a hung store runtime must not hold up the model list.
STORE_RUNTIME_STATUS_TIMEOUT_S = 5.0


async def _store_model_statuses(
    db,
    store_runtime_url: str,
    skip: set[str],
    test_model_prefixes: list[str],
) -> list[ModelStatusInfo]:
    """Status entries for store models: installed (enabled/) and reported by
    the store runtime. Any failure gives no entries, never an error."""
    try:
        async with UnifiedRuntimeClient(
            runtime_url=store_runtime_url, timeout=STORE_RUNTIME_STATUS_TIMEOUT_S
        ) as client:
            capabilities = await client.get_capabilities()
    except Exception as e:  # noqa: BLE001 - the built-in list must still be returned
        logger.warning("Model store runtime unavailable for status", error=str(e))
        return []

    installed = enabled_store_models()
    entries: list[ModelStatusInfo] = []
    for model_info in capabilities.get("models", []):
        model_id = model_info.get("model_id")
        if (
            not model_id
            or model_id in skip
            or model_id in RESERVED_MODEL_IDS
            or model_id not in installed
            or any(model_id.startswith(prefix) for prefix in test_model_prefixes)
            or model_info.get("state") == "invalid"
        ):
            continue
        skip.add(model_id)
        info = installed[model_id]

        # A store model runs as any entry of a multi-model session (or as a
        # legacy session's model_id), so count both.
        uses_model = or_(
            StreamSession.model_id == model_id,
            StreamSession.models.contains([{"model_id": model_id}]),
        )
        result = await db.execute(
            select(func.count())
            .select_from(StreamSession)
            .where(StreamSession.state == StreamState.LIVE)
            .where(uses_model)
        )
        cameras_active = result.scalar() or 0
        result = await db.execute(
            select(StreamSession.started_at)
            .where(uses_model)
            .order_by(StreamSession.started_at.desc())
            .limit(1)
        )
        last_started = result.scalar()

        entries.append(
            ModelStatusInfo(
                model_id=model_id,
                version=model_info.get("version", info.version),
                status=_api_status(model_info.get("state", "unknown"), cameras_active),
                health=_api_health(model_info.get("state", "unknown"), model_info.get("health", "unknown")),
                cameras_active=cameras_active,
                last_inference_at=last_started,
                started_at=last_started,
                source="store",
                display_name=info.display_name,
                zone_required_rules=list(info.zone_required_rules),
                all_rules_need_zone=info.all_rules_need_zone,
                reports_ppe=info.reports_ppe,
            )
        )
    return entries


def _api_status(runtime_state: str, cameras_active: int) -> str:
    """Runtime state -> API status (same mapping as the built-in loop)."""
    if runtime_state == "ready":
        return "active" if cameras_active > 0 else "idle"
    if runtime_state == "loading":
        return "starting"
    if runtime_state == "failed":
        return "error"
    return "idle"


def _api_health(runtime_state: str, runtime_health: str) -> str:
    """Runtime health -> API health (same mapping as the built-in loop)."""
    if runtime_health == "healthy":
        return "healthy"
    if runtime_health == "degraded":
        return "degraded"
    if runtime_health == "unknown":
        return "healthy" if runtime_state == "ready" else "unhealthy"
    return "unhealthy"
