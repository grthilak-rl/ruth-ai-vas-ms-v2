"""Refuse a model ID that is not installed, the same way on every endpoint."""

from fastapi import HTTPException, status

from app.integrations.unified_runtime.client import UnifiedRuntimeError
from app.services.model_availability import ModelNotAvailableError, assert_model_available

#: OpenAPI entries for the two refusals.
MODEL_GUARD_RESPONSES = {
    422: {"description": "model_retired (names the replacement) or model_not_installed"},
    503: {"description": "ai_runtime_unreachable: the unified runtime is in use and cannot be asked"},
}


async def require_installed_model(model_id: str) -> None:
    """422 for a retired or uninstalled model; 503 if it cannot be decided."""
    try:
        await assert_model_available(model_id)
    except ModelNotAvailableError as e:
        raise HTTPException(422, detail=e.detail()) from e
    except UnifiedRuntimeError as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "ai_runtime_unreachable",
                "message": "The AI runtime is unreachable, so the model cannot be checked. Retry shortly.",
                "details": str(e),
            },
        ) from e
