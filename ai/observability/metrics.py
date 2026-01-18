"""
Ruth AI Unified Runtime - Prometheus Metrics

Provides Prometheus-compatible metrics for monitoring runtime performance,
model health, GPU usage, and inference statistics.

Metrics Exposed:
- inference_requests_total: Counter of inference requests by model and status
- inference_duration_seconds: Histogram of inference latencies by model
- inference_queue_size: Gauge of queued requests per model
- model_load_status: Gauge indicating if model is loaded (1) or not (0)
- model_health_status: Gauge for model health (1=healthy, 0=degraded, -1=unhealthy)
- gpu_memory_used_bytes: Gauge of GPU memory usage per device
- gpu_memory_total_bytes: Gauge of total GPU memory per device
- gpu_utilization_percent: Gauge of GPU compute utilization per device
- concurrent_requests_active: Gauge of currently executing requests
- frame_decode_duration_seconds: Histogram of frame decoding latencies

Usage:
    from ai.observability.metrics import record_inference, record_inference_latency

    # Record successful inference
    record_inference(model_id="fall_detection", status="success")

    # Record inference timing
    record_inference_latency(model_id="fall_detection", duration_seconds=0.15)

    # Export metrics (in /metrics endpoint)
    from prometheus_client import generate_latest
    metrics_data = generate_latest(metrics_registry)
"""

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    CollectorRegistry,
    REGISTRY,
)
from typing import Optional

# Use custom registry to avoid conflicts
metrics_registry = CollectorRegistry()

# =============================================================================
# INFERENCE METRICS
# =============================================================================

inference_requests_total = Counter(
    name="inference_requests_total",
    documentation="Total number of inference requests",
    labelnames=["model_id", "status"],
    registry=metrics_registry,
)

inference_duration_seconds = Histogram(
    name="inference_duration_seconds",
    documentation="Inference request duration in seconds",
    labelnames=["model_id"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=metrics_registry,
)

inference_queue_size = Gauge(
    name="inference_queue_size",
    documentation="Number of requests queued for inference",
    labelnames=["model_id"],
    registry=metrics_registry,
)

concurrent_requests_active = Gauge(
    name="concurrent_requests_active",
    documentation="Number of currently executing inference requests",
    registry=metrics_registry,
)

# =============================================================================
# MODEL METRICS
# =============================================================================

model_load_status = Gauge(
    name="model_load_status",
    documentation="Model load status (1=loaded, 0=unloaded)",
    labelnames=["model_id", "version"],
    registry=metrics_registry,
)

model_health_status = Gauge(
    name="model_health_status",
    documentation="Model health status (1=healthy, 0=degraded, -1=unhealthy)",
    labelnames=["model_id", "version"],
    registry=metrics_registry,
)

model_inference_count = Counter(
    name="model_inference_count",
    documentation="Total inferences per model",
    labelnames=["model_id", "version"],
    registry=metrics_registry,
)

model_error_count = Counter(
    name="model_error_count",
    documentation="Total errors per model",
    labelnames=["model_id", "version"],
    registry=metrics_registry,
)

# =============================================================================
# GPU METRICS
# =============================================================================

gpu_memory_used_bytes = Gauge(
    name="gpu_memory_used_bytes",
    documentation="GPU memory currently in use in bytes",
    labelnames=["device"],
    registry=metrics_registry,
)

gpu_memory_total_bytes = Gauge(
    name="gpu_memory_total_bytes",
    documentation="Total GPU memory available in bytes",
    labelnames=["device"],
    registry=metrics_registry,
)

gpu_memory_reserved_bytes = Gauge(
    name="gpu_memory_reserved_bytes",
    documentation="GPU memory reserved for models in bytes",
    labelnames=["device"],
    registry=metrics_registry,
)

gpu_utilization_percent = Gauge(
    name="gpu_utilization_percent",
    documentation="GPU compute utilization percentage",
    labelnames=["device"],
    registry=metrics_registry,
)

gpu_temperature_celsius = Gauge(
    name="gpu_temperature_celsius",
    documentation="GPU temperature in Celsius",
    labelnames=["device"],
    registry=metrics_registry,
)

# =============================================================================
# FRAME PROCESSING METRICS
# =============================================================================

frame_decode_duration_seconds = Histogram(
    name="frame_decode_duration_seconds",
    documentation="Frame decode duration in seconds",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25],
    registry=metrics_registry,
)

frame_size_bytes = Histogram(
    name="frame_size_bytes",
    documentation="Frame size in bytes (base64 encoded)",
    buckets=[1024, 10240, 51200, 102400, 512000, 1048576, 5242880],
    registry=metrics_registry,
)

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def record_inference(model_id: str, status: str) -> None:
    """
    Record an inference request.

    Args:
        model_id: Model identifier
        status: Request status ("success", "failed", "rejected")
    """
    inference_requests_total.labels(model_id=model_id, status=status).inc()


def record_inference_latency(model_id: str, duration_seconds: float) -> None:
    """
    Record inference latency.

    Args:
        model_id: Model identifier
        duration_seconds: Inference duration in seconds
    """
    inference_duration_seconds.labels(model_id=model_id).observe(duration_seconds)


def record_frame_decode_latency(duration_seconds: float) -> None:
    """
    Record frame decode latency.

    Args:
        duration_seconds: Decode duration in seconds
    """
    frame_decode_duration_seconds.observe(duration_seconds)


def record_frame_size(size_bytes: int) -> None:
    """
    Record frame size.

    Args:
        size_bytes: Frame size in bytes
    """
    frame_size_bytes.observe(size_bytes)


def set_model_load_status(model_id: str, version: str, loaded: bool) -> None:
    """
    Set model load status.

    Args:
        model_id: Model identifier
        version: Model version
        loaded: True if loaded, False if unloaded
    """
    model_load_status.labels(model_id=model_id, version=version).set(1 if loaded else 0)


def set_model_health_status(model_id: str, version: str, health: str) -> None:
    """
    Set model health status.

    Args:
        model_id: Model identifier
        version: Model version
        health: Health status ("healthy", "degraded", "unhealthy")
    """
    health_value = {
        "healthy": 1,
        "degraded": 0,
        "unhealthy": -1,
    }.get(health.lower(), 0)

    model_health_status.labels(model_id=model_id, version=version).set(health_value)


def increment_model_inference(model_id: str, version: str) -> None:
    """
    Increment model inference count.

    Args:
        model_id: Model identifier
        version: Model version
    """
    model_inference_count.labels(model_id=model_id, version=version).inc()


def increment_model_error(model_id: str, version: str) -> None:
    """
    Increment model error count.

    Args:
        model_id: Model identifier
        version: Model version
    """
    model_error_count.labels(model_id=model_id, version=version).inc()


def set_concurrent_requests(count: int) -> None:
    """
    Set number of concurrent requests.

    Args:
        count: Number of active requests
    """
    concurrent_requests_active.set(count)


def set_inference_queue_size(model_id: str, size: int) -> None:
    """
    Set inference queue size for a model.

    Args:
        model_id: Model identifier
        size: Queue size
    """
    inference_queue_size.labels(model_id=model_id).set(size)


def update_gpu_metrics(device_id: int, stats: dict) -> None:
    """
    Update GPU metrics for a device.

    Args:
        device_id: GPU device ID
        stats: Dictionary with GPU statistics
            - total_memory_mb: Total memory in MB
            - used_memory_mb: Used memory in MB
            - reserved_memory_mb: Reserved memory in MB
            - utilization_percent: GPU utilization (0-100)
            - temperature_c: Temperature in Celsius
    """
    device_label = str(device_id)

    # Memory metrics (convert MB to bytes)
    if "total_memory_mb" in stats:
        gpu_memory_total_bytes.labels(device=device_label).set(
            stats["total_memory_mb"] * 1024 * 1024
        )

    if "used_memory_mb" in stats:
        gpu_memory_used_bytes.labels(device=device_label).set(
            stats["used_memory_mb"] * 1024 * 1024
        )

    if "reserved_memory_mb" in stats:
        gpu_memory_reserved_bytes.labels(device=device_label).set(
            stats["reserved_memory_mb"] * 1024 * 1024
        )

    # Utilization
    if "utilization_percent" in stats and stats["utilization_percent"] is not None:
        gpu_utilization_percent.labels(device=device_label).set(
            stats["utilization_percent"]
        )

    # Temperature
    if "temperature_c" in stats and stats["temperature_c"] is not None:
        gpu_temperature_celsius.labels(device=device_label).set(
            stats["temperature_c"]
        )


def clear_model_metrics(model_id: str, version: str) -> None:
    """
    Clear metrics for an unloaded model.

    Args:
        model_id: Model identifier
        version: Model version
    """
    # Set load status to 0
    set_model_load_status(model_id, version, loaded=False)

    # Clear queue size
    set_inference_queue_size(model_id, 0)
