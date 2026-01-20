"""
Runtime Router - Routes inference requests to unified runtime or containers

Decides whether to use:
- Unified Runtime (new models: fall_detection, helmet_detection, etc.)
- Existing Containers (demo models: fall_detection_container, ppe_detection_container)
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID

from app.core.logging import get_logger
from app.integrations.vas import VASClient

from .config import should_use_unified_runtime
from .client import UnifiedRuntimeClient
from .frame_fetcher import FrameFetcher

logger = get_logger(__name__)


class RoutingTarget(Enum):
    """Routing target for inference requests."""
    UNIFIED_RUNTIME = "unified_runtime"
    CONTAINER = "container"


@dataclass
class RoutingDecision:
    """Decision about where to route an inference request."""
    target: RoutingTarget
    model_id: str
    reason: str


class RuntimeRouter:
    """
    Routes inference requests to appropriate runtime.

    Usage:
        router = RuntimeRouter(vas_client)

        # Determine routing
        decision = router.decide_routing("fall_detection")

        # Execute inference
        result = await router.submit_inference(
            model_id="fall_detection",
            device_id=device_id,
            stream_id=stream_id,
            ...
        )
    """

    def __init__(
        self,
        vas_client: VASClient,
        unified_runtime_client: Optional[UnifiedRuntimeClient] = None,
    ):
        """
        Initialize runtime router.

        Args:
            vas_client: VAS client for frame fetching
            unified_runtime_client: Unified runtime client (created if not provided)
        """
        self.vas_client = vas_client
        self.unified_runtime_client = unified_runtime_client or UnifiedRuntimeClient()
        self.frame_fetcher = FrameFetcher(vas_client)

    def decide_routing(self, model_id: str) -> RoutingDecision:
        """
        Decide where to route an inference request.

        Args:
            model_id: Model identifier

        Returns:
            Routing decision with target and reason
        """
        if should_use_unified_runtime(model_id):
            return RoutingDecision(
                target=RoutingTarget.UNIFIED_RUNTIME,
                model_id=model_id,
                reason=f"Model {model_id} configured for unified runtime"
            )
        else:
            return RoutingDecision(
                target=RoutingTarget.CONTAINER,
                model_id=model_id,
                reason=f"Model {model_id} uses existing container deployment"
            )

    async def submit_inference(
        self,
        model_id: str,
        stream_id: UUID,
        device_id: Optional[UUID] = None,
        model_version: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        priority: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Submit inference request to appropriate runtime.

        Args:
            model_id: Target model identifier
            stream_id: Source stream UUID
            device_id: Source device UUID
            model_version: Specific model version
            timestamp: Frame capture timestamp
            priority: Request priority
            metadata: Additional metadata
            config: Model-specific configuration

        Returns:
            Inference results dictionary

        Raises:
            ValueError: If routing target not supported
            Exception: If inference fails
        """
        # Decide routing
        decision = self.decide_routing(model_id)

        logger.info(
            "Routing inference request",
            model_id=model_id,
            target=decision.target.value,
            reason=decision.reason,
        )

        if decision.target == RoutingTarget.UNIFIED_RUNTIME:
            return await self._submit_to_unified_runtime(
                model_id=model_id,
                stream_id=stream_id,
                device_id=device_id,
                model_version=model_version,
                timestamp=timestamp,
                priority=priority,
                metadata=metadata,
                config=config,
            )
        elif decision.target == RoutingTarget.CONTAINER:
            # For container-based models, delegate to existing integration
            # This preserves the demo-critical fall-detection-model and ppe-detection-model
            raise NotImplementedError(
                f"Container routing not yet implemented. "
                f"Use existing endpoints for {model_id}"
            )
        else:
            raise ValueError(f"Unsupported routing target: {decision.target}")

    async def _submit_to_unified_runtime(
        self,
        model_id: str,
        stream_id: UUID,
        device_id: Optional[UUID] = None,
        model_version: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        priority: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Submit inference to unified runtime.

        Workflow:
        1. Fetch frame from VAS
        2. Encode frame to base64
        3. Submit to unified runtime
        4. Return results

        Args:
            model_id: Target model identifier
            stream_id: Source stream UUID
            device_id: Source device UUID
            model_version: Specific model version
            timestamp: Frame capture timestamp
            priority: Request priority
            metadata: Additional metadata

        Returns:
            Inference results dictionary
        """
        # Step 1: Fetch frame from VAS and encode
        logger.debug("Fetching frame from VAS", device_id=str(device_id) if device_id else None)

        frame_data = await self.frame_fetcher.fetch_and_encode(
            device_id=device_id,
            stream_id=stream_id,
            timeout=10.0,
        )

        logger.debug(
            "Frame fetched and encoded",
            format=frame_data.format,
            dimensions=f"{frame_data.width}x{frame_data.height}",
            size_kb=f"{frame_data.size_kb:.1f}KB",
        )

        # Step 2: Submit to unified runtime
        response = await self.unified_runtime_client.submit_inference(
            model_id=model_id,
            frame_base64=frame_data.base64_data,
            stream_id=stream_id,
            device_id=device_id,
            model_version=model_version,
            frame_format=frame_data.format,
            frame_width=frame_data.width,
            frame_height=frame_data.height,
            timestamp=timestamp or datetime.utcnow(),
            priority=priority,
            metadata=metadata,
            config=config,
        )

        # Step 3: Convert response to dict and return
        return {
            "request_id": str(response.request_id),
            "status": response.status,
            "model_id": response.model_id,
            "model_version": response.model_version,
            "inference_time_ms": response.inference_time_ms,
            "result": response.result,
            "error": response.error,
        }
