Ruth AI Unified Runtime - Architecture Completion Specification
1. PROTECTED CODE INVENTORY (DO NOT MODIFY)
Critical Constraint
The following code is PRODUCTION-READY FOR DEMO and must NOT be modified:

Model Container Directories (Completely Off-Limits)

✗ fall-detection-model/               (Entire directory - demo critical)
  ├── Dockerfile
  ├── app.py
  ├── detector.py
  ├── models/
  ├── utils/
  └── weights/

✗ ppe-detection-model/                (Entire directory - demo critical)
  ├── Dockerfile
  ├── app.py
  ├── detector.py
  ├── model.yaml
  └── weights/
Backend Integration Code (Protected)

✗ ruth-ai-backend/app/core/config.py
  - Lines 77-79: ai_runtime_url (fall-detection-model endpoint)
  - Lines 95-97: ppe_detection_url (ppe-detection-model endpoint)

✗ ruth-ai-backend/app/services/hardware_service.py
  - Lines 314-322: _get_ai_model_status() queries fall/ppe services

✗ ruth-ai-backend/app/api/v1/hardware.py
  - Lines 61-66: Hardcoded model service status for demo

✗ ruth-ai-backend/.env.example
  - Lines 24, 29: AI_RUNTIME_URL, PPE_DETECTION_URL
Docker Compose Services (Protected)

✗ docker-compose.yml
  - Lines 83-110: fall-detection-model service definition
  - Lines 116-149: ppe-detection-model service definition
  - Line 185: AI_RUNTIME_URL=http://fall-detection-model:8000
  - Line 189: PPE_DETECTION_URL=http://ppe-detection-model:8000
  - Line 209: Backend depends_on fall-detection-model
Migration Files (Do Not Modify Enums)

✗ ruth-ai-backend/alembic/versions/2026_01_18_0002_add_ppe_event_types.py
  - PPE event type definitions

✗ ruth-ai-backend/app/models/enums.py
  - EventType enum with fall_detected, ppe_violation, etc.
2. GAP ANALYSIS - Unified AI Runtime Implementation Status
Existing Implementation (ai/runtime/ - 11,198 lines)
Component	File	Status	Lines	Notes
Model Registry	registry.py	✅ COMPLETE	~500	Thread-safe, event-based, full lifecycle
Model Loader	loader.py	✅ COMPLETE	~600	Dynamic import, weight loading, warmup
Validator	validator.py	✅ COMPLETE	~800	model.yaml schema validation
Discovery	discovery.py	✅ COMPLETE	~400	Filesystem scanning, version enumeration
Versioning	versioning.py	✅ COMPLETE	~600	Semver resolution, eligibility rules
Execution Sandbox	sandbox.py	✅ COMPLETE	~900	Isolation, timeout enforcement, exception handling
Frame Pipeline	pipeline.py	✅ COMPLETE	~1100	Request routing, backpressure, admission control
Concurrency	concurrency.py	✅ COMPLETE	~700	Admission controller, slot management
Recovery	recovery.py	✅ COMPLETE	~500	Auto-recovery, cooldown, retry logic
Capability Reporter	reporting.py	✅ COMPLETE	~600	Capability aggregation, health reporting
Error Handling	errors.py	✅ COMPLETE	~400	Exception hierarchy, error codes
Data Models	models.py	✅ COMPLETE	~800	All Pydantic/dataclass definitions
Missing Components (Critical for Production)
Component	Status	Priority	Effort	Blocker?
Runtime HTTP/gRPC Server	❌ MISSING	CRITICAL	3-4 days	YES
Frame Resolver	❌ MISSING	CRITICAL	2-3 days	YES
Model Weight Management	⚠️ PARTIAL	HIGH	2 days	NO
GPU Memory Manager	❌ MISSING	HIGH	2-3 days	NO
Metrics & Observability	❌ MISSING	MEDIUM	1-2 days	NO
Unified Runtime Dockerfile	❌ MISSING	CRITICAL	1 day	YES
Backend Integration (NEW)	❌ MISSING	CRITICAL	2 days	YES
Docker Compose Service	❌ MISSING	CRITICAL	1 day	YES
3. DETAILED GAP DESCRIPTIONS
3.1 Runtime HTTP/gRPC Server (CRITICAL - BLOCKER)
What's Missing:

No FastAPI or gRPC server to expose endpoints
No /health, /capabilities, /inference REST endpoints
No protobuf definitions for gRPC (optional but referenced in backend client)
Why It's a Blocker:
The unified runtime cannot receive requests from the backend without a server.

What Needs to Exist:


ai/
└── server/
    ├── __init__.py
    ├── main.py               # FastAPI app entry point
    ├── routes/
    │   ├── __init__.py
    │   ├── health.py         # GET /health
    │   ├── capabilities.py   # GET /capabilities
    │   └── inference.py      # POST /inference
    ├── middleware.py         # Logging, CORS, error handling
    └── lifecycle.py          # Startup/shutdown hooks
Dependencies:

FastAPI, uvicorn, pydantic
Integration with ai.runtime.pipeline.InferencePipeline
Integration with ai.runtime.reporting.CapabilityReporter
3.2 Frame Resolver (CRITICAL - BLOCKER)
What's Missing:
The backend sends opaque frame references (e.g., "vas://frame/uuid"), but the unified runtime needs actual frame pixel data to run inference.

Current Problem:

ai/runtime/pipeline.py accepts FrameReference objects
No code exists to resolve these references to actual image data
The runtime must NOT talk to VAS directly (architectural violation)
Design Conflict:
The architecture document states:

"Runtime MUST NOT accept raw frames"
"Runtime MUST NOT talk to VAS"

But models need pixel data to run inference.

Resolution Strategy:
The backend must resolve frame references BEFORE sending to unified runtime, OR the runtime needs a Frame Resolver Service that acts as an adapter.

Proposed Solution (NEW Component):


ai/
└── frame_resolver/
    ├── __init__.py
    ├── resolver.py           # FrameResolver interface
    ├── vas_resolver.py       # VAS implementation (via VAS snapshot API)
    └── cache.py              # LRU cache for resolved frames
Alternative: Backend fetches frames from VAS and sends base64-encoded image data in InferenceRequest.

3.3 Model Weight Management (PARTIAL)
What Exists:

ai/runtime/loader.py can load weights from ai/models/<model_id>/<version>/weights/
Weights are currently part of model plugin directory
What's Missing:

No weight download/versioning system
No checksum verification
No weight caching for multi-runtime deployments
No weight pruning for space management
Current Workaround:
Weights are baked into model directories (works for demo, but not scalable).

Future Enhancement (POST-DEMO):


ai/
└── weights/
    ├── __init__.py
    ├── manager.py            # Weight lifecycle management
    ├── downloader.py         # Fetch from S3/registry
    └── verifier.py           # Checksum validation
3.4 GPU Memory Manager (MISSING)
What's Missing:

No automatic GPU memory allocation per model
No GPU OOM detection and recovery
No CPU fallback when GPU exhausted
No model unloading when memory pressure high
Current State:
Models load into GPU if available (via PyTorch default behavior), no explicit management.

Needed for Production:


ai/
└── runtime/
    └── gpu_manager.py
        - track_gpu_memory()
        - allocate_for_model()
        - release_model_memory()
        - fallback_to_cpu()
3.5 Metrics & Observability (MISSING)
What's Missing:

No Prometheus metrics export
No structured logging (partially exists but incomplete)
No request tracing (request_id propagation incomplete)
No health degradation alerting
Needed Metrics:

inference_requests_total{model_id, status}
inference_duration_seconds{model_id, quantile}
model_health_status{model_id, state}
gpu_memory_used_bytes
concurrent_requests_active
Implementation:


ai/
└── observability/
    ├── __init__.py
    ├── metrics.py            # Prometheus metrics
    ├── logging.py            # Structured logging
    └── tracing.py            # OpenTelemetry (optional)
3.6 Unified Runtime Dockerfile (MISSING - BLOCKER)
What's Missing:
There is NO Dockerfile for the unified runtime container.

Needed:


ai/
└── Dockerfile
    - Base image: python:3.11-slim
    - Install PyTorch, FastAPI, etc.
    - COPY ai/ to /app/ai/
    - COPY ai/models/ to /app/ai/models/
    - Expose port 8000
    - CMD: uvicorn ai.server.main:app
Critical Decisions:

Multi-arch support (CPU vs GPU base images)
Model weights: baked in vs mounted volume
Jetson compatibility
3.7 Backend Integration (NEW - BLOCKER)
What's Missing:
The backend has AIRuntimeClient that expects to talk to a unified runtime, but:

No configuration to point to unified runtime
No routing logic: "use unified runtime for model X, use container for model Y"
No fallback strategy if unified runtime unavailable
Needed (NEW FILES ONLY - DO NOT MODIFY EXISTING):


ruth-ai-backend/
└── app/
    ├── integrations/
    │   └── ai_runtime_unified/      # NEW
    │       ├── __init__.py
    │       ├── client.py            # Unified runtime-specific client
    │       └── router.py            # Route to unified vs container
    └── core/
        └── runtime_config.py        # NEW: routing configuration
Configuration Strategy:


# NEW config file: ruth-ai-backend/runtime_routing.yaml
models:
  fall_detection:
    provider: "container"           # Use existing container
    url: "http://fall-detection-model:8000"
  
  ppe_detection:
    provider: "container"           # Use existing container
    url: "http://ppe-detection-model:8000"
  
  helmet_detection:
    provider: "unified_runtime"     # NEW model → unified runtime
    url: "http://unified-ai-runtime:8000"
  
  fire_detection:
    provider: "unified_runtime"
    url: "http://unified-ai-runtime:8000"
3.8 Docker Compose Service (MISSING - BLOCKER)
What's Missing:
No docker-compose service definition for unified-ai-runtime.

Needed (ADDITIVE - append to docker-compose.yml):


# NEW SERVICE (add after ppe-detection-model)
unified-ai-runtime:
  build:
    context: ./ai
    dockerfile: Dockerfile
  container_name: ruth-ai-unified-runtime
  restart: unless-stopped
  ports:
    - "8012:8000"                    # NEW port (don't conflict with 8010, 8011)
  volumes:
    - ./ai/models:/app/ai/models:ro  # Mount model plugins
  environment:
    - ENVIRONMENT=production
    - LOG_LEVEL=info
    - MODELS_ROOT=/app/ai/models
    - ENABLE_GPU=true
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 90s
  networks:
    - ruth-ai-internal
  deploy:
    resources:
      limits:
        memory: 8G
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
        memory: 4G
4. PARALLEL INTEGRATION STRATEGY
4.1 Coexistence Model

┌────────────────────────────────────────────────────────────────┐
│                      RUTH AI BACKEND                           │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │           NEW: Runtime Router Service                    │  │
│  │  (decides which runtime to use per model_id)             │  │
│  └────────────┬────────────────────────────┬────────────────┘  │
│               │                            │                   │
│               │                            │                   │
└───────────────┼────────────────────────────┼───────────────────┘
                │                            │
    ┌───────────▼────────────┐   ┌───────────▼────────────────┐
    │  EXISTING CONTAINERS   │   │  NEW: UNIFIED RUNTIME      │
    │  (DEMO-CRITICAL)       │   │  (FUTURE MODELS)           │
    │                        │   │                            │
    │  fall-detection:8000   │   │  unified-runtime:8000      │
    │  ppe-detection:8000    │   │                            │
    │                        │   │  Models:                   │
    │  ✓ Production ready    │   │  - helmet_detection        │
    │  ✓ Do not touch        │   │  - fire_detection          │
    │  ✓ Used for demo       │   │  - (future models)         │
    └────────────────────────┘   └────────────────────────────┘
4.2 Routing Decision Logic (NEW)

# ruth-ai-backend/app/integrations/ai_runtime_unified/router.py

class RuntimeRouter:
    """Routes inference requests to appropriate runtime."""
    
    async def route_inference(
        self,
        model_id: str,
        stream_id: UUID,
        frame_reference: str,
    ) -> InferenceResponse:
        """Route request to correct runtime based on model_id."""
        
        # Check routing configuration
        if model_id in ["fall_detection", "ppe_detection"]:
            # Use existing container-based models (PROTECTED)
            return await self._route_to_container(model_id, ...)
        else:
            # Use new unified runtime
            return await self._route_to_unified(model_id, ...)
4.3 Feature Flag Configuration (NEW)

# ruth-ai-backend/app/core/runtime_config.py

class RuntimeConfig(BaseSettings):
    """Configuration for AI Runtime routing."""
    
    use_unified_runtime: bool = Field(
        default=False,
        description="Enable unified runtime for supported models"
    )
    
    unified_runtime_url: str = Field(
        default="http://unified-ai-runtime:8000",
        description="Unified runtime endpoint"
    )
    
    # Model-specific routing
    model_routing: dict[str, str] = Field(
        default_factory=lambda: {
            "fall_detection": "container",
            "ppe_detection": "container",
            "helmet_detection": "unified",
            "fire_detection": "unified",
        }
    )
5. IMPLEMENTATION PLAN (Phased Roadmap)
Phase 1: Minimal Viable Runtime (MVP) - 5-7 days
Goal: Get unified runtime running with ONE new model (e.g., helmet_detection).

Task	Files to Create	Effort	Priority
1. Create FastAPI server skeleton	ai/server/main.py, ai/server/routes/*.py	1 day	P0
2. Implement /health endpoint	ai/server/routes/health.py	0.5 day	P0
3. Implement /capabilities endpoint	ai/server/routes/capabilities.py	0.5 day	P0
4. Implement /inference endpoint	ai/server/routes/inference.py	1 day	P0
5. Create Dockerfile for unified runtime	ai/Dockerfile	1 day	P0
6. Add docker-compose service	docker-compose.yml (append)	0.5 day	P0
7. Create sample helmet_detection model	ai/models/helmet_detection/1.0.0/	1 day	P0
8. Manual testing (curl, Postman)	-	0.5 day	P0
Deliverables:

Unified runtime container running on port 8012
Health endpoint returns 200 OK
Capabilities endpoint lists helmet_detection
Inference endpoint accepts requests (may return stub responses initially)
Validation:


curl http://localhost:8012/health
curl http://localhost:8012/capabilities
curl -X POST http://localhost:8012/inference \
  -H "Content-Type: application/json" \
  -d '{"model_id": "helmet_detection", "frame_reference": "test", ...}'
Phase 2: Frame Resolution & Backend Integration - 3-4 days
Goal: Backend can route new models to unified runtime.

Task	Files to Create	Effort	Priority
9. Implement Frame Resolver (VAS adapter)	ai/frame_resolver/*.py	1.5 days	P0
10. Create Runtime Router in backend	ruth-ai-backend/app/integrations/ai_runtime_unified/router.py	1 day	P0
11. Add routing configuration	ruth-ai-backend/app/core/runtime_config.py	0.5 day	P0
12. Update backend to use router	ruth-ai-backend/app/services/stream_service.py (NEW methods)	1 day	P1
13. Integration testing	-	1 day	P0
Deliverables:

Backend can send requests to unified runtime for helmet_detection
Frame references are resolved to actual images
End-to-end inference works
Validation:


# Start stream for helmet_detection (should use unified runtime)
curl -X POST http://localhost:8080/api/v1/streams/start \
  -d '{"device_id": "...", "model_id": "helmet_detection"}'
Phase 3: GPU Management & Production Hardening - 3-4 days
Goal: Production-ready performance and reliability.

Task	Files to Create	Effort	Priority
14. Implement GPU memory manager	ai/runtime/gpu_manager.py	2 days	P1
15. Add Prometheus metrics	ai/observability/metrics.py	1 day	P1
16. Structured logging	ai/observability/logging.py	0.5 day	P1
17. Load testing & optimization	-	1 day	P1
Deliverables:

GPU memory tracked and managed
Prometheus metrics exposed at /metrics
Structured JSON logs
Phase 4: Multi-Model Deployment - 2-3 days
Goal: Add 2-3 more models to unified runtime.

Task	Files to Create	Effort	Priority
18. Create fire_detection model	ai/models/fire_detection/1.0.0/	1 day	P2
19. Create intrusion_detection model	ai/models/intrusion_detection/1.0.0/	1 day	P2
20. Multi-model concurrent inference testing	-	1 day	P2
6. CODE SKELETONS
6.1 FastAPI Server Entry Point
File: ai/server/main.py


"""
Ruth AI Unified Runtime - FastAPI Server

This is the main entry point for the unified AI runtime.
It exposes HTTP endpoints for health, capabilities, and inference.

Design Principles:
- Model-agnostic request handling
- No VAS integration (backend resolves frames)
- Strict contract validation
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from ai.runtime.discovery import ModelDiscovery
from ai.runtime.registry import ModelRegistry
from ai.runtime.loader import ModelLoader
from ai.runtime.validator import ModelValidator
from ai.runtime.sandbox import SandboxManager
from ai.runtime.pipeline import InferencePipeline
from ai.runtime.reporting import CapabilityReporter
from ai.runtime.concurrency import AdmissionController
from ai.server import routes

logger = logging.getLogger(__name__)


# Global runtime components (initialized at startup)
registry: ModelRegistry | None = None
pipeline: InferencePipeline | None = None
reporter: CapabilityReporter | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle manager."""
    global registry, pipeline, reporter
    
    logger.info("🚀 Ruth AI Unified Runtime starting...")
    
    # Initialize components
    registry = ModelRegistry()
    validator = ModelValidator()
    loader = ModelLoader()
    sandbox_manager = SandboxManager()
    admission_controller = AdmissionController(max_concurrent=10)
    
    pipeline = InferencePipeline(
        registry=registry,
        sandbox_manager=sandbox_manager,
        admission_controller=admission_controller,
    )
    
    reporter = CapabilityReporter(registry=registry)
    
    # Discover and load models
    discovery = ModelDiscovery(
        models_root="./ai/models",
        registry=registry,
        validator=validator,
        loader=loader,
    )
    
    await discovery.discover_and_load_all()
    
    # Report capabilities
    capabilities = reporter.generate_capability_declaration()
    logger.info(
        "✅ Runtime ready",
        models=[m.model_id for m in capabilities.supported_models],
    )
    
    yield  # Server runs
    
    # Cleanup
    logger.info("🛑 Runtime shutting down...")
    # Unload models, close resources
    

app = FastAPI(
    title="Ruth AI Unified Runtime",
    version="1.0.0",
    description="Multi-model AI inference platform",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure based on environment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(routes.health.router, prefix="/health", tags=["health"])
app.include_router(routes.capabilities.router, prefix="/capabilities", tags=["capabilities"])
app.include_router(routes.inference.router, prefix="/inference", tags=["inference"])


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors gracefully."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )


if __name__ == "__main__":
    uvicorn.run(
        "ai.server.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True,
    )
6.2 Health Endpoint
File: ai/server/routes/health.py


"""Health check endpoint."""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ai.server.main import registry, reporter

router = APIRouter()


class HealthResponse(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    runtime_id: str
    models_loaded: int
    models_healthy: int
    models_degraded: int
    models_unhealthy: int


@router.get("", response_model=HealthResponse)
async def health_check(include_models: bool = Query(False)):
    """Check runtime health."""
    if not registry or not reporter:
        return HealthResponse(
            status="unhealthy",
            runtime_id="unknown",
            models_loaded=0,
            models_healthy=0,
            models_degraded=0,
            models_unhealthy=0,
        )
    
    health_summary = reporter.get_health_summary()
    
    return HealthResponse(
        status=health_summary.status.value,
        runtime_id=reporter.runtime_id,
        models_loaded=health_summary.total_models,
        models_healthy=health_summary.healthy_models,
        models_degraded=health_summary.degraded_models,
        models_unhealthy=health_summary.unhealthy_models,
    )
6.3 Inference Endpoint
File: ai/server/routes/inference.py


"""Inference endpoint."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ai.server.main import pipeline
from ai.runtime.errors import ModelError, PipelineError
from ai.runtime.pipeline import FrameReference, InferenceRequest

router = APIRouter()


class InferRequest(BaseModel):
    """Inference request from backend."""
    stream_id: str
    device_id: str | None = None
    frame_reference: str  # Opaque reference
    timestamp: datetime
    model_id: str = "helmet_detection"
    model_version: str | None = None
    priority: int = Field(default=0, ge=0, le=10)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InferResponse(BaseModel):
    """Inference response to backend."""
    request_id: str
    status: str  # "success" | "failed"
    model_id: str
    model_version: str
    inference_time_ms: float
    result: dict[str, Any] | None = None
    error: str | None = None


@router.post("", response_model=InferResponse)
async def infer(request: InferRequest):
    """Submit inference request."""
    if not pipeline:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime not ready",
        )
    
    # TODO: Resolve frame_reference to actual image data
    # This is where Frame Resolver would be called
    frame_data = None  # Placeholder
    
    frame_ref = FrameReference(
        reference=request.frame_reference,
        stream_id=uuid.UUID(request.stream_id),
        device_id=uuid.UUID(request.device_id) if request.device_id else None,
        timestamp=request.timestamp,
        metadata=request.metadata,
    )
    
    try:
        result = await pipeline.submit_inference(
            frame_reference=frame_ref,
            model_id=request.model_id,
            model_version=request.model_version,
            priority=request.priority,
        )
        
        return InferResponse(
            request_id=str(result.request_id),
            status="success",
            model_id=result.model_id,
            model_version=result.model_version,
            inference_time_ms=result.inference_time_ms,
            result=result.output,
        )
    
    except ModelError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model not found: {e}",
        )
    
    except PipelineError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inference failed: {e}",
        )
6.4 Unified Runtime Dockerfile
File: ai/Dockerfile


# Ruth AI Unified Runtime - Multi-stage build
# Supports CPU and GPU deployments

# ============================================
# Stage 1: Base image with Python
# ============================================
FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ============================================
# Stage 2: Install Python dependencies
# ============================================
FROM base AS dependencies

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================
# Stage 3: Runtime image
# ============================================
FROM base AS runtime

# Copy installed packages from dependencies stage
COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# Copy application code
COPY ai/ /app/ai/

# Create models directory (will be mounted as volume)
RUN mkdir -p /app/ai/models

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=90s \
    CMD curl -f http://localhost:8000/health || exit 1

# Run server
CMD ["python", "-m", "uvicorn", "ai.server.main:app", "--host", "0.0.0.0", "--port", "8000"]
File: ai/requirements.txt


fastapi==0.109.0
uvicorn[standard]==0.27.0
pydantic==2.5.3
pydantic-settings==2.1.0
torch==2.1.2
torchvision==0.16.2
opencv-python-headless==4.9.0.80
numpy==1.26.3
pillow==10.2.0
pyyaml==6.0.1
httpx==0.26.0
prometheus-client==0.19.0
structlog==24.1.0
6.5 Sample Model: Helmet Detection
File: ai/models/helmet_detection/1.0.0/model.yaml


# Helmet Detection Model Contract
contract_schema_version: "1.0.0"

# Model identity
model_id: "helmet_detection"
version: "1.0.0"
display_name: "Helmet Detection"
description: "Detects presence or absence of safety helmets on workers"
author: "Ruth AI Team"

# Input specification
input:
  type: "frame"
  format: "raw_bgr"
  min_width: 320
  min_height: 240
  max_width: 1920
  max_height: 1080
  channels: 3

# Output specification
output:
  schema_version: "1.0"
  schema:
    event_type:
      type: "string"
      enum:
        - "no_helmet_detected"
        - "helmet_present"
        - "no_detection"
    confidence:
      type: "number"
      min: 0.0
      max: 1.0
    bounding_boxes:
      type: "array"
      items:
        bbox: { type: "array", items: "number" }
        label: { type: "string" }
        confidence: { type: "number" }

# Hardware compatibility
hardware:
  supports_cpu: true
  supports_gpu: true
  supports_jetson: true
  min_ram_mb: 1024
  min_gpu_memory_mb: 256

# Performance hints
performance:
  inference_time_hint_ms: 100
  recommended_fps: 10
  max_fps: 30
  recommended_batch_size: 1
  warmup_iterations: 1

# Resource limits
limits:
  max_memory_mb: 2048
  inference_timeout_ms: 3000
  preprocessing_timeout_ms: 500
  postprocessing_timeout_ms: 500
  max_concurrent_inferences: 4

# Entry points
entry_points:
  inference: "inference.py"
  preprocess: "preprocess.py"
File: ai/models/helmet_detection/1.0.0/inference.py


"""Helmet detection inference implementation."""

import numpy as np
from typing import Any

# Placeholder - replace with actual model
def infer(frame: np.ndarray, **kwargs) -> dict[str, Any]:
    """Run helmet detection inference.
    
    Args:
        frame: BGR image as numpy array (H, W, 3)
        
    Returns:
        Detection results matching output schema
    """
    # TODO: Replace with actual YOLOv8/YOLOv7 helmet detection model
    
    # Stub response
    return {
        "event_type": "no_detection",
        "confidence": 0.0,
        "bounding_boxes": [],
    }
7. TIMELINE ESTIMATE
Conservative Estimate (Single Developer)
Phase	Duration	Deliverable
Phase 1: MVP	5-7 days	Unified runtime running, 1 model
Phase 2: Integration	3-4 days	Backend routes to unified runtime
Phase 3: Hardening	3-4 days	GPU management, metrics
Phase 4: Multi-model	2-3 days	3+ models deployed
Total	13-18 days	Production-ready unified runtime
Parallel Development (2-3 Developers)
Phase	Duration	Parallelization
Phase 1: MVP	3-4 days	Split: server + Dockerfile + sample model
Phase 2: Integration	2-3 days	Split: frame resolver + backend router
Phase 3: Hardening	2-3 days	Split: GPU mgr + metrics + logging
Phase 4: Multi-model	1-2 days	Parallel model creation
Total	8-12 days	Production-ready unified runtime
8. MIGRATION PATH (POST-DEMO)
Future: Migrating fall_detection & ppe_detection to Unified Runtime
Phase 1: Preparation (No Downtime)

Create ai/models/fall_detection/2.0.0/ (copy from existing container)
Create ai/models/ppe_detection/2.0.0/ (copy from existing container)
Update model.yaml contracts
Test in unified runtime (parallel deployment)
Phase 2: Gradual Migration

Update backend routing config:

fall_detection:
  provider: "unified"  # Switch from "container"
  url: "http://unified-ai-runtime:8000"
Monitor performance, rollback if issues
After 1 week stable: deprecate fall-detection-model container
Remove docker-compose service
Rollback Strategy:

Keep container images for 30 days
Toggle routing config to switch back instantly
No data loss (stateless services)
9. VALIDATION CRITERIA
Phase 1 Success Criteria
 docker compose up unified-ai-runtime starts successfully
 curl http://localhost:8012/health returns 200 OK
 curl http://localhost:8012/capabilities lists helmet_detection
 Inference request accepts JSON, returns response (even if stub)
Phase 2 Success Criteria
 Backend can start stream with model_id="helmet_detection"
 Backend routes request to unified runtime (not container)
 Frame reference resolves to image data
 Inference completes end-to-end
Phase 3 Success Criteria
 GPU memory usage tracked via Prometheus
 Concurrent requests don't OOM GPU
 Metrics visible at /metrics
 Load test: 10 concurrent streams stable
Phase 4 Success Criteria
 3+ models loaded simultaneously
 Each model isolated (one failure doesn't affect others)
 Automatic recovery from model crashes
10. CONCLUSION
Summary
The Ruth AI Unified Runtime architecture is well-designed but incomplete. Approximately 70% of the core runtime logic exists (11,000+ lines in ai/runtime/), but critical infrastructure components are missing:

No HTTP/gRPC server to expose endpoints
No Frame Resolver to convert references to pixel data
No Dockerfile to build the runtime container
No backend integration to route requests
The existing demo-critical code (fall-detection-model, ppe-detection-model containers) is fully functional and protected. The unified runtime will run in parallel as a separate service for new models.

Next Steps
Immediate (Week 1): Implement Phase 1 (MVP server + Dockerfile)
Week 2: Implement Phase 2 (Backend integration + routing)
Week 3: Implement Phase 3 (GPU management + observability)
Week 4: Implement Phase 4 (Multi-model deployment)
Risk Assessment
Risk	Mitigation
Frame resolution unclear	Backend sends base64 images (simple) OR create VAS adapter
GPU OOM with multiple models	Implement admission control + memory tracking (Phase 3)
Performance worse than containers	Profile and optimize (Phase 3), acceptable for non-demo models
Integration breaks demo	Routing config ensures demo models untouched
Document Version: 1.0

Author: Claude (Analysis Agent)

Date: 2026-01-18