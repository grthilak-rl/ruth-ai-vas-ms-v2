"""
Ruth AI Unified Runtime - Metrics Endpoint

Exposes Prometheus-compatible metrics for monitoring.
"""

from fastapi import APIRouter, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from ai.observability.metrics import metrics_registry

router = APIRouter()


@router.get("", tags=["metrics"])
async def get_metrics():
    """
    Get Prometheus metrics.

    Returns:
        Metrics in Prometheus text format
    """
    metrics_data = generate_latest(metrics_registry)
    return Response(content=metrics_data, media_type=CONTENT_TYPE_LATEST)
