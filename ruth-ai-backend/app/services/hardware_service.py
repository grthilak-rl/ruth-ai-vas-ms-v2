"""Hardware monitoring service for Ruth AI Backend.

Provides real-time hardware metrics including:
- GPU (NVIDIA via pynvml)
- CPU (via psutil)
- RAM (via psutil)
- AI model service status
- System capacity estimates

All operations are async with proper error handling.
"""

import asyncio
import platform
from datetime import datetime, timezone
from typing import Any

import httpx
import psutil

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.schemas.hardware import (
    CapacityMetrics,
    CPUMetrics,
    GPUMetrics,
    HardwareResponse,
    ModelServiceStatus,
    ModelsMetrics,
    RAMMetrics,
)

logger = get_logger(__name__)

# Try to import pynvml for NVIDIA GPU monitoring
# This is optional - gracefully handle if not available
try:
    import pynvml

    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False
    pynvml = None  # type: ignore[assignment]


class HardwareService:
    """Service for collecting hardware metrics.

    Provides async methods for collecting GPU, CPU, RAM, and model
    service information. All methods handle errors gracefully and
    return partial data when full metrics are unavailable.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
    ) -> None:
        """Initialize hardware service.

        Args:
            settings: Application settings (uses get_settings() if not provided)
        """
        self._settings = settings or get_settings()
        self._nvml_initialized = False

    def _init_nvml(self) -> bool:
        """Initialize NVML for GPU monitoring.

        Returns:
            True if NVML is initialized successfully, False otherwise
        """
        if not PYNVML_AVAILABLE:
            return False

        if self._nvml_initialized:
            return True

        try:
            pynvml.nvmlInit()
            self._nvml_initialized = True
            logger.debug("NVML initialized successfully")
            return True
        except Exception as e:
            logger.debug("Failed to initialize NVML", error=str(e))
            return False

    def _shutdown_nvml(self) -> None:
        """Shutdown NVML if initialized."""
        if self._nvml_initialized and PYNVML_AVAILABLE:
            try:
                pynvml.nvmlShutdown()
                self._nvml_initialized = False
            except Exception:
                pass

    async def get_gpu_metrics(self) -> GPUMetrics:
        """Get GPU metrics using NVIDIA pynvml.

        Returns:
            GPUMetrics with GPU information, or available=False if no GPU
        """
        if not self._init_nvml():
            return GPUMetrics(
                available=False,
                name=None,
                vram_total_gb=None,
                vram_used_gb=None,
                vram_percent=None,
                utilization_percent=None,
                temperature_c=None,
            )

        try:
            # Get the first GPU (device 0)
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)

            # Get device name
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8")

            # Get memory info
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            vram_total_gb = round(mem_info.total / (1024**3), 1)
            vram_used_gb = round(mem_info.used / (1024**3), 1)
            vram_percent = int((mem_info.used / mem_info.total) * 100)

            # Get utilization
            utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
            utilization_percent = utilization.gpu

            # Get temperature
            try:
                temperature = pynvml.nvmlDeviceGetTemperature(
                    handle, pynvml.NVML_TEMPERATURE_GPU
                )
            except Exception:
                temperature = None

            return GPUMetrics(
                available=True,
                name=name,
                vram_total_gb=vram_total_gb,
                vram_used_gb=vram_used_gb,
                vram_percent=vram_percent,
                utilization_percent=utilization_percent,
                temperature_c=temperature,
            )

        except Exception as e:
            logger.warning("Failed to get GPU metrics", error=str(e))
            return GPUMetrics(
                available=False,
                name=None,
                vram_total_gb=None,
                vram_used_gb=None,
                vram_percent=None,
                utilization_percent=None,
                temperature_c=None,
            )

    async def get_cpu_metrics(self) -> CPUMetrics:
        """Get CPU metrics using psutil.

        Returns:
            CPUMetrics with CPU information
        """
        try:
            # Get CPU model name
            try:
                # Try to get CPU brand string
                import subprocess

                result = subprocess.run(
                    ["cat", "/proc/cpuinfo"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                cpu_model = None
                for line in result.stdout.split("\n"):
                    if "model name" in line.lower():
                        cpu_model = line.split(":")[1].strip()
                        break
                if not cpu_model:
                    cpu_model = platform.processor() or "Unknown"
            except Exception:
                cpu_model = platform.processor() or "Unknown"

            # Get core count
            cores = psutil.cpu_count(logical=True)

            # Get CPU usage (non-blocking average over interval)
            # Use a short interval to avoid blocking
            usage_percent = psutil.cpu_percent(interval=0.1)

            return CPUMetrics(
                model=cpu_model,
                cores=cores,
                usage_percent=round(usage_percent, 1),
            )

        except Exception as e:
            logger.warning("Failed to get CPU metrics", error=str(e))
            return CPUMetrics(
                model=None,
                cores=None,
                usage_percent=0.0,
            )

    async def get_ram_metrics(self) -> RAMMetrics:
        """Get RAM metrics using psutil.

        Returns:
            RAMMetrics with memory information
        """
        try:
            mem = psutil.virtual_memory()

            return RAMMetrics(
                total_gb=round(mem.total / (1024**3), 1),
                used_gb=round(mem.used / (1024**3), 1),
                percent=round(mem.percent, 1),
            )

        except Exception as e:
            logger.warning("Failed to get RAM metrics", error=str(e))
            return RAMMetrics(
                total_gb=0.0,
                used_gb=0.0,
                percent=0.0,
            )

    async def _query_model_service(
        self,
        name: str,
        url: str,
        timeout_seconds: float = 5.0,
    ) -> ModelServiceStatus:
        """Query a model service for its status.

        Args:
            name: Service name for display
            url: Base URL of the model service
            timeout_seconds: Request timeout

        Returns:
            ModelServiceStatus with service health and model count
        """
        try:
            async with asyncio.timeout(timeout_seconds):
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{url}/info")
                    response.raise_for_status()
                    data = response.json()

            # Try to extract model count from response
            # Common patterns: "models", "model_count", "loaded_models"
            models_count = 1  # Default assumption
            if isinstance(data, dict):
                if "models" in data:
                    models_value = data["models"]
                    if isinstance(models_value, list):
                        models_count = len(models_value)
                    elif isinstance(models_value, int):
                        models_count = models_value
                elif "model_count" in data:
                    models_count = data.get("model_count", 1)
                elif "loaded_models" in data:
                    models_count = len(data.get("loaded_models", []))

            return ModelServiceStatus(
                name=name,
                models=models_count,
                status="healthy",
            )

        except asyncio.TimeoutError:
            logger.warning(
                f"Model service {name} timed out",
                url=url,
                timeout_seconds=timeout_seconds,
            )
            return ModelServiceStatus(name=name, models=0, status="unhealthy")

        except httpx.HTTPStatusError as e:
            logger.warning(
                f"Model service {name} returned error",
                url=url,
                status_code=e.response.status_code,
            )
            return ModelServiceStatus(name=name, models=0, status="unhealthy")

        except httpx.RequestError as e:
            logger.debug(
                f"Model service {name} unreachable",
                url=url,
                error=str(e),
            )
            return ModelServiceStatus(name=name, models=0, status="unknown")

        except Exception as e:
            logger.warning(
                f"Unexpected error querying model service {name}",
                url=url,
                error=str(e),
            )
            return ModelServiceStatus(name=name, models=0, status="unknown")

    async def get_models_metrics(self) -> ModelsMetrics:
        """Get AI model service metrics.

        Queries fall-detection and ppe-detection services for their status.

        Returns:
            ModelsMetrics with loaded model counts and service statuses
        """
        # Define model services to query
        services_config = [
            ("fall-detection", self._settings.ai_runtime_url),
            ("ppe-detection", self._settings.ppe_detection_url),
        ]

        # Query all services concurrently with configured timeout
        timeout = self._settings.hardware_model_service_timeout
        tasks = [
            self._query_model_service(name, url, timeout_seconds=timeout)
            for name, url in services_config
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        services: list[ModelServiceStatus] = []
        total_models = 0

        for i, result in enumerate(results):
            service_name = services_config[i][0]
            if isinstance(result, Exception):
                logger.warning(
                    f"Failed to query model service {service_name}",
                    error=str(result),
                )
                services.append(
                    ModelServiceStatus(name=service_name, models=0, status="unknown")
                )
            else:
                services.append(result)
                if result.status == "healthy":
                    total_models += result.models

        return ModelsMetrics(
            loaded_count=total_models,
            services=services,
        )

    async def get_capacity_metrics(
        self,
        gpu_metrics: GPUMetrics,
        ram_metrics: RAMMetrics,
    ) -> CapacityMetrics:
        """Calculate system capacity estimates.

        Uses GPU VRAM (if available) or RAM to estimate maximum camera capacity.
        Formula: max_cameras = (available_vram / avg_vram_per_camera) * 0.8

        Args:
            gpu_metrics: GPU metrics for VRAM-based calculation
            ram_metrics: RAM metrics for fallback calculation

        Returns:
            CapacityMetrics with capacity estimates
        """
        # Use configuration values for capacity estimation
        avg_vram_per_camera_gb = self._settings.hardware_avg_vram_per_camera_gb
        avg_ram_per_camera_gb = self._settings.hardware_avg_ram_per_camera_gb
        safety_factor = self._settings.hardware_capacity_safety_factor

        current_cameras = 2  # Default, should ideally come from device service

        if gpu_metrics.available and gpu_metrics.vram_total_gb:
            # GPU-based calculation
            available_vram = gpu_metrics.vram_total_gb - (gpu_metrics.vram_used_gb or 0)
            max_cameras = int((available_vram / avg_vram_per_camera_gb) * safety_factor)
            # Add back current cameras since they're already using resources
            max_cameras = max(max_cameras + current_cameras, current_cameras)
        else:
            # RAM-based calculation for CPU-only mode
            available_ram = ram_metrics.total_gb - ram_metrics.used_gb
            max_cameras = int((available_ram / avg_ram_per_camera_gb) * safety_factor)
            max_cameras = max(max_cameras + current_cameras, current_cameras)

        # Ensure max is at least current
        max_cameras = max(max_cameras, current_cameras)

        # Calculate headroom
        if max_cameras > 0:
            headroom_percent = int(
                ((max_cameras - current_cameras) / max_cameras) * 100
            )
        else:
            headroom_percent = 0

        return CapacityMetrics(
            current_cameras=current_cameras,
            estimated_max_cameras=max_cameras,
            headroom_percent=max(0, headroom_percent),
        )

    async def get_hardware_status(self) -> HardwareResponse:
        """Get complete hardware status.

        Collects all hardware metrics concurrently for efficiency.

        Returns:
            HardwareResponse with all hardware metrics
        """
        try:
            # Collect GPU, CPU, RAM, and models metrics concurrently
            gpu_task = self.get_gpu_metrics()
            cpu_task = self.get_cpu_metrics()
            ram_task = self.get_ram_metrics()
            models_task = self.get_models_metrics()

            gpu, cpu, ram, models = await asyncio.gather(
                gpu_task, cpu_task, ram_task, models_task
            )

            # Calculate capacity based on collected metrics
            capacity = await self.get_capacity_metrics(gpu, ram)

            return HardwareResponse(
                timestamp=datetime.now(timezone.utc),
                gpu=gpu,
                cpu=cpu,
                ram=ram,
                models=models,
                capacity=capacity,
            )

        except Exception as e:
            logger.error("Failed to collect hardware metrics", error=str(e))
            # Return minimal response on error
            return HardwareResponse(
                timestamp=datetime.now(timezone.utc),
                gpu=GPUMetrics(available=False),
                cpu=CPUMetrics(model=None, cores=None, usage_percent=0.0),
                ram=RAMMetrics(total_gb=0.0, used_gb=0.0, percent=0.0),
                models=ModelsMetrics(loaded_count=0, services=[]),
                capacity=CapacityMetrics(
                    current_cameras=0,
                    estimated_max_cameras=0,
                    headroom_percent=0,
                ),
            )
