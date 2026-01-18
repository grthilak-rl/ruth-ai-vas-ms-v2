"""
Ruth AI Backend - Unified Runtime Integration

This module provides integration with the Unified AI Runtime for model inference.
It handles frame fetching from VAS, base64 encoding, and routing to the unified runtime.

Usage:
    from app.integrations.unified_runtime import UnifiedRuntimeClient, FrameFetcher

    # Initialize
    runtime_client = UnifiedRuntimeClient(runtime_url="http://unified-ai-runtime:8000")
    frame_fetcher = FrameFetcher(vas_client)

    # Fetch and encode frame
    frame_data = await frame_fetcher.fetch_and_encode(device_id)

    # Send to unified runtime
    result = await runtime_client.submit_inference(
        model_id="fall_detection",
        frame_base64=frame_data.base64_data,
        ...
    )
"""

from .client import UnifiedRuntimeClient
from .frame_fetcher import FrameFetcher, FrameData
from .router import RuntimeRouter, RoutingDecision
from .config import UnifiedRuntimeConfig

__all__ = [
    "UnifiedRuntimeClient",
    "FrameFetcher",
    "FrameData",
    "RuntimeRouter",
    "RoutingDecision",
    "UnifiedRuntimeConfig",
]
