"""
Ruth AI Runtime - GPU Memory Manager

Manages GPU memory allocation, tracks usage per model, and provides
graceful degradation to CPU when GPU resources are exhausted.

Design Principles:
- Proactive OOM prevention (check before allocating)
- Automatic CPU fallback when GPU unavailable/full
- Per-model memory tracking
- Multi-GPU support (future-proofing)
- No crashes on GPU errors

Usage:
    gpu_manager = GPUManager()

    # Check if can load model to GPU
    if gpu_manager.can_allocate(model_id, required_mb=2048):
        device = gpu_manager.allocate(model_id, version, required_mb=2048)
        # Load model to device
    else:
        # Fall back to CPU
        device = "cpu"

    # Release when unloading
    gpu_manager.release(model_id, version)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# GPU STATUS
# =============================================================================


class GPUStatus(Enum):
    """GPU availability status."""

    AVAILABLE = "available"  # GPU available and working
    UNAVAILABLE = "unavailable"  # No GPU detected
    ERROR = "error"  # GPU detected but errors occurred


@dataclass
class GPUDevice:
    """Information about a GPU device."""

    device_id: int
    name: str
    total_memory_mb: float
    used_memory_mb: float = 0.0
    reserved_memory_mb: float = 0.0  # Memory allocated to models
    utilization_percent: float = 0.0
    temperature_c: Optional[float] = None

    @property
    def available_memory_mb(self) -> float:
        """Calculate available memory."""
        return self.total_memory_mb - self.used_memory_mb

    @property
    def free_memory_mb(self) -> float:
        """Calculate free memory (excluding reservations)."""
        return self.total_memory_mb - self.used_memory_mb - self.reserved_memory_mb


@dataclass
class ModelAllocation:
    """GPU memory allocation for a model."""

    model_id: str
    version: str
    device_id: int
    allocated_mb: float
    allocated_at: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# GPU MANAGER
# =============================================================================


class GPUManager:
    """
    Manages GPU memory allocation and provides CPU fallback.

    Features:
    - Detect GPU availability
    - Track memory per model
    - Proactive OOM prevention
    - Automatic CPU fallback
    - Memory release on unload
    """

    def __init__(
        self,
        enable_gpu: bool = True,
        memory_reserve_mb: float = 512.0,  # Reserve for PyTorch overhead
        fallback_to_cpu: bool = True,
    ):
        """
        Initialize GPU manager.

        Args:
            enable_gpu: Whether to attempt GPU usage
            memory_reserve_mb: Memory to reserve for PyTorch overhead
            fallback_to_cpu: Whether to fall back to CPU when GPU unavailable
        """
        self.enable_gpu = enable_gpu
        self.memory_reserve_mb = memory_reserve_mb
        self.fallback_to_cpu = fallback_to_cpu

        self._lock = threading.Lock()
        self._devices: Dict[int, GPUDevice] = {}
        self._allocations: Dict[str, ModelAllocation] = {}  # qualified_id -> allocation
        self._torch_available = False
        self._cuda_available = False
        self._status = GPUStatus.UNAVAILABLE

        # Initialize GPU detection
        self._detect_gpus()

    def _detect_gpus(self) -> None:
        """Detect available GPUs and their properties."""
        if not self.enable_gpu:
            logger.info("GPU disabled by configuration")
            self._status = GPUStatus.UNAVAILABLE
            return

        try:
            import torch
            self._torch_available = True

            if torch.cuda.is_available():
                self._cuda_available = True
                device_count = torch.cuda.device_count()

                logger.info(f"Detected {device_count} CUDA device(s)")

                for device_id in range(device_count):
                    props = torch.cuda.get_device_properties(device_id)
                    total_memory_mb = props.total_memory / (1024 * 1024)

                    device = GPUDevice(
                        device_id=device_id,
                        name=props.name,
                        total_memory_mb=total_memory_mb,
                    )

                    self._devices[device_id] = device

                    logger.info(
                        f"GPU {device_id}: {device.name}, "
                        f"{total_memory_mb:.0f} MB total memory"
                    )

                self._status = GPUStatus.AVAILABLE
            else:
                logger.warning("PyTorch available but CUDA not available")
                self._status = GPUStatus.UNAVAILABLE

        except ImportError:
            logger.warning("PyTorch not installed, GPU support disabled")
            self._status = GPUStatus.UNAVAILABLE

        except Exception as e:
            logger.error(f"Error detecting GPUs: {e}", exc_info=True)
            self._status = GPUStatus.ERROR

    @property
    def is_available(self) -> bool:
        """Check if GPU is available."""
        return self._status == GPUStatus.AVAILABLE and len(self._devices) > 0

    @property
    def status(self) -> GPUStatus:
        """Get GPU status."""
        return self._status

    @property
    def device_count(self) -> int:
        """Get number of available GPUs."""
        return len(self._devices)

    def get_devices(self) -> List[GPUDevice]:
        """Get list of GPU devices."""
        with self._lock:
            return list(self._devices.values())

    def get_device(self, device_id: int) -> Optional[GPUDevice]:
        """Get specific GPU device info."""
        with self._lock:
            return self._devices.get(device_id)

    def update_device_stats(self) -> None:
        """Update GPU device statistics (memory usage, utilization)."""
        if not self.is_available or not self._torch_available:
            return

        try:
            import torch

            with self._lock:
                for device_id, device in self._devices.items():
                    # Get current memory stats
                    used_memory = torch.cuda.memory_allocated(device_id) / (1024 * 1024)
                    device.used_memory_mb = used_memory

                    # Get utilization if pynvml available
                    try:
                        import pynvml
                        handle = pynvml.nvmlDeviceGetHandleByIndex(device_id)
                        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                        device.utilization_percent = util.gpu

                        temp = pynvml.nvmlDeviceGetTemperature(
                            handle, pynvml.NVML_TEMPERATURE_GPU
                        )
                        device.temperature_c = temp
                    except (ImportError, Exception):
                        # pynvml not available or failed, skip
                        pass

        except Exception as e:
            logger.error(f"Error updating GPU stats: {e}")

    def can_allocate(
        self,
        model_id: str,
        required_mb: float,
        device_id: Optional[int] = None
    ) -> bool:
        """
        Check if GPU memory can be allocated for a model.

        Args:
            model_id: Model identifier
            required_mb: Required memory in MB
            device_id: Specific device ID (None = auto-select)

        Returns:
            True if allocation is possible
        """
        if not self.is_available:
            return False

        with self._lock:
            if device_id is not None:
                # Check specific device
                device = self._devices.get(device_id)
                if not device:
                    return False

                free_memory = device.free_memory_mb - self.memory_reserve_mb
                return free_memory >= required_mb
            else:
                # Check any device
                for device in self._devices.values():
                    free_memory = device.free_memory_mb - self.memory_reserve_mb
                    if free_memory >= required_mb:
                        return True
                return False

    def allocate(
        self,
        model_id: str,
        version: str,
        required_mb: float,
        device_id: Optional[int] = None
    ) -> str:
        """
        Allocate GPU memory for a model.

        Args:
            model_id: Model identifier
            version: Model version
            required_mb: Required memory in MB
            device_id: Specific device ID (None = auto-select)

        Returns:
            Device string ("cuda:0", "cuda:1", or "cpu" if fallback)

        Raises:
            RuntimeError: If allocation fails and fallback disabled
        """
        qualified_id = f"{model_id}:{version}"

        # Check if already allocated
        with self._lock:
            if qualified_id in self._allocations:
                existing = self._allocations[qualified_id]
                logger.warning(
                    f"Model {qualified_id} already allocated on device {existing.device_id}"
                )
                return f"cuda:{existing.device_id}"

        # Try GPU allocation
        if self.is_available:
            with self._lock:
                # Find suitable device
                target_device = None

                if device_id is not None:
                    # Use specific device if requested
                    device = self._devices.get(device_id)
                    if device and device.free_memory_mb - self.memory_reserve_mb >= required_mb:
                        target_device = device
                else:
                    # Auto-select device with most free memory
                    for device in self._devices.values():
                        free_memory = device.free_memory_mb - self.memory_reserve_mb
                        if free_memory >= required_mb:
                            if target_device is None or device.free_memory_mb > target_device.free_memory_mb:
                                target_device = device

                if target_device:
                    # Allocate
                    allocation = ModelAllocation(
                        model_id=model_id,
                        version=version,
                        device_id=target_device.device_id,
                        allocated_mb=required_mb,
                    )

                    self._allocations[qualified_id] = allocation
                    target_device.reserved_memory_mb += required_mb

                    logger.info(
                        f"Allocated {required_mb:.0f}MB GPU memory for {qualified_id} "
                        f"on device {target_device.device_id}"
                    )

                    return f"cuda:{target_device.device_id}"

        # GPU allocation failed or unavailable
        if self.fallback_to_cpu:
            logger.warning(
                f"GPU allocation failed for {qualified_id}, falling back to CPU"
            )
            return "cpu"
        else:
            raise RuntimeError(
                f"GPU memory allocation failed for {qualified_id} "
                f"(required: {required_mb:.0f}MB)"
            )

    def release(self, model_id: str, version: str) -> bool:
        """
        Release GPU memory allocated to a model.

        Args:
            model_id: Model identifier
            version: Model version

        Returns:
            True if memory was released, False if not allocated
        """
        qualified_id = f"{model_id}:{version}"

        with self._lock:
            allocation = self._allocations.pop(qualified_id, None)

            if allocation:
                device = self._devices.get(allocation.device_id)
                if device:
                    device.reserved_memory_mb -= allocation.allocated_mb

                logger.info(
                    f"Released {allocation.allocated_mb:.0f}MB GPU memory for {qualified_id}"
                )

                # Try to clear CUDA cache
                if self._torch_available and self._cuda_available:
                    try:
                        import torch
                        torch.cuda.empty_cache()
                    except Exception as e:
                        logger.warning(f"Failed to empty CUDA cache: {e}")

                return True
            else:
                logger.debug(f"No GPU allocation found for {qualified_id}")
                return False

    def get_allocation(self, model_id: str, version: str) -> Optional[ModelAllocation]:
        """Get allocation info for a model."""
        qualified_id = f"{model_id}:{version}"
        with self._lock:
            return self._allocations.get(qualified_id)

    def get_all_allocations(self) -> List[ModelAllocation]:
        """Get all current allocations."""
        with self._lock:
            return list(self._allocations.values())

    def get_stats(self) -> Dict[str, any]:
        """
        Get GPU manager statistics.

        Returns:
            Dictionary with GPU stats and allocations
        """
        self.update_device_stats()

        with self._lock:
            return {
                "status": self._status.value,
                "torch_available": self._torch_available,
                "cuda_available": self._cuda_available,
                "device_count": len(self._devices),
                "devices": [
                    {
                        "device_id": d.device_id,
                        "name": d.name,
                        "total_memory_mb": d.total_memory_mb,
                        "used_memory_mb": d.used_memory_mb,
                        "reserved_memory_mb": d.reserved_memory_mb,
                        "available_memory_mb": d.available_memory_mb,
                        "utilization_percent": d.utilization_percent,
                        "temperature_c": d.temperature_c,
                    }
                    for d in self._devices.values()
                ],
                "allocations": [
                    {
                        "model_id": a.model_id,
                        "version": a.version,
                        "device_id": a.device_id,
                        "allocated_mb": a.allocated_mb,
                        "allocated_at": a.allocated_at.isoformat(),
                    }
                    for a in self._allocations.values()
                ],
                "total_allocated_mb": sum(a.allocated_mb for a in self._allocations.values()),
            }
