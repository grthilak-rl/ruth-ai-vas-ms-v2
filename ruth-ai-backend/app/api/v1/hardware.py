"""Hardware monitoring endpoint for Ruth AI Backend.

Provides:
- GET /api/v1/system/hardware - Real-time hardware utilization metrics

Returns GPU, CPU, RAM, loaded AI models, and capacity estimates
for the Ruth AI dashboard.
"""

from fastapi import APIRouter, status

from app.core.logging import get_logger
from app.schemas.hardware import HardwareResponse
from app.services.hardware_service import HardwareService

router = APIRouter(tags=["System"])
logger = get_logger(__name__)


def _get_hardware_service() -> HardwareService:
    """Create a HardwareService instance."""
    return HardwareService()


@router.get(
    "/system/hardware",
    response_model=HardwareResponse,
    status_code=status.HTTP_200_OK,
    summary="Hardware status",
    description="Returns real-time hardware utilization metrics including GPU, CPU, RAM, loaded AI models, and capacity estimates.",
    responses={
        200: {
            "description": "Hardware metrics collected successfully",
            "content": {
                "application/json": {
                    "example": {
                        "timestamp": "2025-01-17T14:30:00Z",
                        "gpu": {
                            "available": True,
                            "name": "NVIDIA RTX 3090",
                            "vram_total_gb": 24.0,
                            "vram_used_gb": 18.7,
                            "vram_percent": 78,
                            "utilization_percent": 45,
                            "temperature_c": 62,
                        },
                        "cpu": {
                            "model": "Intel i7-12700K",
                            "cores": 12,
                            "usage_percent": 32.5,
                        },
                        "ram": {
                            "total_gb": 64.0,
                            "used_gb": 31.0,
                            "percent": 48.4,
                        },
                        "models": {
                            "loaded_count": 2,
                            "services": [
                                {
                                    "name": "fall-detection",
                                    "models": 1,
                                    "status": "healthy",
                                },
                                {
                                    "name": "ppe-detection",
                                    "models": 1,
                                    "status": "healthy",
                                },
                            ],
                        },
                        "capacity": {
                            "current_cameras": 2,
                            "estimated_max_cameras": 12,
                            "headroom_percent": 83,
                        },
                    }
                }
            },
        }
    },
)
async def get_hardware_status() -> HardwareResponse:
    """Get real-time hardware utilization metrics.

    Collects GPU, CPU, RAM, AI model service status, and calculates
    capacity estimates based on available resources.

    This endpoint never fails - it always returns partial data if
    full metrics are unavailable. For example:
    - If no GPU: gpu.available=False with null metrics
    - If model service unreachable: status="unknown" with models=0

    Returns:
        HardwareResponse with all hardware metrics
    """
    hardware_service = _get_hardware_service()

    response = await hardware_service.get_hardware_status()

    logger.debug(
        "Hardware status collected",
        gpu_available=response.gpu.available,
        cpu_usage=response.cpu.usage_percent,
        ram_percent=response.ram.percent,
        models_loaded=response.models.loaded_count,
        estimated_max_cameras=response.capacity.estimated_max_cameras,
    )

    return response
