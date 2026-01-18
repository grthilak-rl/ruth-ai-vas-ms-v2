"""
Ruth AI Unified Runtime - Observability

Provides metrics, logging, and monitoring capabilities.
"""

from .metrics import (
    metrics_registry,
    record_inference,
    record_inference_latency,
    record_frame_decode_latency,
    set_model_load_status,
    set_model_health_status,
    set_concurrent_requests,
    set_inference_queue_size,
    update_gpu_metrics,
)

__all__ = [
    "metrics_registry",
    "record_inference",
    "record_inference_latency",
    "record_frame_decode_latency",
    "set_model_load_status",
    "set_model_health_status",
    "set_concurrent_requests",
    "set_inference_queue_size",
    "update_gpu_metrics",
]
