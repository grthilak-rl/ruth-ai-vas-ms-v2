"""Per-model inference rates for multi-model sessions.

A model's default rate is its runtime-declared recommended_fps (from model.yaml,
pushed to the backend by the runtime's capability registration), capped at the
loop's TARGET_FPS so defaults pace like today's single-model sessions. A
per-camera fps_override wins over both.
"""

from typing import Any, Optional

#: Allowed range for a per-camera fps_override.
MIN_OVERRIDE_FPS = 0.05
MAX_OVERRIDE_FPS = 15.0


def recommended_fps(model_id: str, model_version: Optional[str] = None) -> Optional[float]:
    """recommended_fps the runtime declared for this model, or None if unknown."""
    # Read-only use of the in-memory registry that /internal/v1/ai-runtime/register
    # maintains. Imported lazily: the inference loop imports this module, and
    # the API package must not be pulled in at its import time.
    from app.api.internal.ai_runtime import _registered_runtimes

    for registration in _registered_runtimes.values():
        for model in registration.models:
            if model.get("model_id") != model_id:
                continue
            for version in model.get("versions", []):
                if model_version and version.get("version") != model_version:
                    continue
                fps = (version.get("performance") or {}).get("recommended_fps")
                if fps:
                    return float(fps)
    return None


def desired_fps(entry: dict[str, Any], target_fps: float) -> float:
    """The rate a model entry asks for, before the GPU budget applies."""
    override = entry.get("fps_override")
    if override:
        return float(override)
    declared = recommended_fps(entry["model_id"], entry.get("model_version"))
    return min(declared, target_fps) if declared else target_fps
