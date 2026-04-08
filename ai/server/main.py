"""
Ruth AI Unified Runtime - FastAPI Server

This is the main entry point for the unified AI runtime HTTP API.
It exposes health, capabilities, and inference endpoints.

Design Principles:
- Model-agnostic request handling
- No VAS integration (backend resolves frames)
- Strict contract validation
- Graceful startup/shutdown
"""

import asyncio
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

# Add ai/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.runtime.discovery import DiscoveryScanner
from ai.runtime.registry import ModelRegistry
from ai.runtime.loader import ModelLoader
from ai.runtime.models import LoadState, HealthStatus
from ai.runtime.validator import ContractValidator
from ai.runtime.sandbox import SandboxManager
from ai.runtime.pipeline import InferencePipeline
from ai.runtime.concurrency import ConcurrencyManager, AdmissionController
from ai.runtime.gpu_manager import GPUManager
from ai.runtime.reporting import (
    CapabilityPublisher,
    HealthAggregator,
    RuntimeCapacityTracker,
    create_reporting_stack,
)
from ai.runtime.backend_client import HTTPBackendClient, BackendClientConfig

from ai.server import dependencies
from ai.server.config import get_config
from ai.server.routes import health, capabilities, inference, metrics

from ai.observability.logging import configure_logging, get_logger, set_request_id, clear_request_id
from ai.observability.metrics import (
    set_model_load_status,
    set_model_health_status,
    update_gpu_metrics,
)

# Will be configured by configure_logging()
logger = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle manager - handles startup and shutdown."""
    global logger

    # Load configuration
    config = get_config()

    # Configure structured logging
    configure_logging(
        level=config.log_level,
        format=config.log_format,
        redact_fields=config.redact_log_fields
    )
    logger = get_logger(__name__)

    logger.info("🚀 Ruth AI Unified Runtime starting...", extra={
        "runtime_id": config.runtime_id,
        "version": "1.0.0"
    })

    # Get models root from config
    models_path = Path(config.models_root)

    if not models_path.exists():
        logger.error("Models directory not found", extra={"path": str(models_path)})
        logger.info("Creating empty models directory")
        models_path.mkdir(parents=True, exist_ok=True)

    logger.info("Models root configured", extra={"path": str(models_path)})

    # Initialize GPU manager
    gpu_manager = GPUManager(
        enable_gpu=config.enable_gpu,
        memory_reserve_mb=config.gpu_memory_reserve_mb,
        fallback_to_cpu=config.gpu_fallback_to_cpu
    )

    gpu_stats = gpu_manager.get_stats()
    logger.info("GPU manager initialized", extra={
        "status": gpu_stats["status"],
        "device_count": gpu_stats["device_count"],
        "cuda_available": gpu_stats["cuda_available"]
    })

    # Update GPU metrics
    if config.metrics_enabled:
        for device in gpu_stats["devices"]:
            update_gpu_metrics(device["device_id"], device)

    # Initialize core components
    registry = ModelRegistry()
    validator = ContractValidator()
    loader = ModelLoader()
    sandbox_manager = SandboxManager()

    # Concurrency management (limit concurrent inferences)
    concurrency_manager = ConcurrencyManager(
        global_limit=config.max_concurrent_inferences,
        default_model_limit=1
    )
    admission_controller = AdmissionController(manager=concurrency_manager)

    # Inference pipeline
    pipeline = InferencePipeline(
        registry=registry,
        sandbox_manager=sandbox_manager,
        admission_controller=admission_controller,
    )

    # ==========================================================================
    # Backend Integration - Capability Publisher
    # ==========================================================================

    backend_client = None
    capability_publisher = None

    if config.backend_integration_enabled:
        logger.info("Initializing backend integration...", extra={
            "backend_url": config.backend_url
        })

        # Create backend client
        backend_client_config = BackendClientConfig(
            backend_url=config.backend_url,
            api_key=config.backend_api_key,
            service_token=config.backend_service_token,
            connect_timeout=config.backend_connect_timeout_seconds,
            read_timeout=config.backend_read_timeout_seconds,
        )

        backend_client = HTTPBackendClient(
            config=backend_client_config,
            runtime_id=config.runtime_id,
        )

        # Create reporting stack with actual backend client
        capability_publisher, health_reporter, capacity_tracker = create_reporting_stack(
            registry=registry,
            backend_client=backend_client,
            max_concurrent=config.max_concurrent_inferences,
            runtime_id=config.runtime_id,
            concurrency_manager=concurrency_manager,
        )

        # Store in dependencies
        dependencies.set_backend_client(backend_client)
        dependencies.set_capability_publisher(capability_publisher)
        dependencies.set_reporter(health_reporter)

        logger.info("Backend integration initialized")
    else:
        logger.info("Backend integration disabled by configuration")

    # Store in global dependencies
    dependencies.set_registry(registry)
    dependencies.set_pipeline(pipeline)
    dependencies.set_sandbox_manager(sandbox_manager)

    # Store GPU manager
    app.state.gpu_manager = gpu_manager
    app.state.config = config

    # Discover and load models
    logger.info("Scanning for model plugins...")
    scanner = DiscoveryScanner(
        models_root=models_path,
        validator=validator,
    )

    try:
        discovery_result = scanner.scan()
        logger.info(
            f"Discovery complete: {discovery_result.models_found} models, "
            f"{discovery_result.versions_found} versions, "
            f"{discovery_result.versions_valid} valid"
        )

        # Register discovered models first
        for version_desc in discovery_result.discovered_versions:
            registry.register_version(version_desc)
            logger.info("Registered model version", extra={
                "model_id": version_desc.model_id,
                "version": version_desc.version
            })

        # Load valid models
        if discovery_result.versions_valid > 0:
            logger.info("Loading valid models...", extra={
                "valid_count": discovery_result.versions_valid
            })

            for version_desc in discovery_result.discovered_versions:
                # Discovered versions are already validated
                model_id = version_desc.model_id
                version = version_desc.version

                try:
                    logger.info("Loading model", extra={
                        "model_id": model_id,
                        "version": version
                    })

                    load_result = loader.load(version_desc)

                    if load_result.success and load_result.loaded_model:
                        # Create sandbox for the loaded model
                        sandbox_manager.create_sandbox(load_result.loaded_model, version_desc)

                        # Update registry state to READY
                        registry.update_state(
                            model_id,
                            version,
                            LoadState.READY
                        )

                        # Update registry health to HEALTHY
                        registry.update_health(
                            model_id,
                            version,
                            HealthStatus.HEALTHY
                        )

                        # Update metrics
                        if config.metrics_enabled:
                            set_model_load_status(model_id, version, loaded=True)
                            set_model_health_status(model_id, version, "healthy")

                        logger.info("Model loaded successfully", extra={
                            "model_id": model_id,
                            "version": version,
                            "load_time_ms": load_result.load_time_ms
                        })
                    else:
                        error_msg = load_result.error.message if load_result.error else "Unknown error"

                        # Update metrics
                        if config.metrics_enabled:
                            set_model_load_status(model_id, version, loaded=False)

                        logger.error("Model load failed", extra={
                            "model_id": model_id,
                            "version": version,
                            "error": error_msg
                        })
                except Exception as e:
                    if config.metrics_enabled:
                        set_model_load_status(model_id, version, loaded=False)

                    logger.error("Model load exception", extra={
                        "model_id": model_id,
                        "version": version,
                        "error": str(e)
                    }, exc_info=True)

        # Report final state
        all_versions = registry.get_all_versions()
        ready_count = sum(1 for v in all_versions if v.state.is_available())

        logger.info(
            f"✅ Runtime ready: {ready_count}/{len(all_versions)} models available for inference"
        )

        if ready_count == 0:
            logger.warning("⚠️  No models ready for inference!")

    except Exception as e:
        logger.error(f"Error during model discovery/loading: {e}", exc_info=True)

    # ==========================================================================
    # Start Capability Publisher (after models loaded)
    # ==========================================================================

    if capability_publisher is not None:
        logger.info("Starting capability publisher...")
        capability_publisher.start()
        logger.info("Capability publisher started - will register with backend")

    yield  # Server runs

    # ==========================================================================
    # Graceful Shutdown
    # ==========================================================================
    # This runs when SIGTERM/SIGINT is received or server is stopped
    # uvicorn --timeout-graceful-shutdown handles in-flight request draining

    logger.info("🛑 Runtime shutting down - beginning graceful cleanup...")

    shutdown_start = asyncio.get_event_loop().time()

    # Step 1: Stop capability publisher and deregister from backend
    try:
        if capability_publisher is not None:
            logger.info("Stopping capability publisher...")
            capability_publisher.stop(timeout=5.0)
            logger.info("Capability publisher stopped")

        if backend_client is not None:
            logger.info("Deregistering from backend...")
            correlation_id = str(uuid.uuid4())
            backend_client.deregister(correlation_id)
            backend_client.close()
            logger.info("Backend client closed")
    except Exception as e:
        logger.error(f"Error during backend deregistration: {e}")

    # Step 2: Stop accepting new inference requests
    # (uvicorn handles this automatically via readiness probe returning 503)

    # Step 3: Wait for in-flight requests to complete
    # (uvicorn's --timeout-graceful-shutdown handles this)

    # Step 4: Shutdown sandbox executors
    try:
        if sandbox_manager:
            logger.info("Shutting down sandbox executors...")
            sandbox_manager.shutdown_all()
            logger.info("Sandbox executors shut down")
    except Exception as e:
        logger.error(f"Error during sandbox shutdown: {e}")

    # Step 5: Unload models and release GPU memory
    try:
        all_versions = registry.get_all_versions()
        for version_info in all_versions:
            model_id = version_info.model_id
            version = version_info.version

            try:
                # Update state to UNLOADING
                registry.update_state(model_id, version, LoadState.UNLOADING)

                # Update metrics
                if config.metrics_enabled:
                    set_model_load_status(model_id, version, loaded=False)

                logger.info("Model unloaded", extra={
                    "model_id": model_id,
                    "version": version
                })
            except Exception as e:
                logger.warning(f"Error unloading model {model_id}:{version}: {e}")
    except Exception as e:
        logger.error(f"Error during model cleanup: {e}")

    # Step 6: Release GPU resources
    try:
        if gpu_manager:
            gpu_manager.release_all()
            logger.info("GPU resources released")
    except Exception as e:
        logger.error(f"Error releasing GPU resources: {e}")

    # Step 7: Clear dependencies
    dependencies.clear_all()

    shutdown_duration = asyncio.get_event_loop().time() - shutdown_start
    logger.info(f"✅ Shutdown complete in {shutdown_duration:.2f}s")


# Create FastAPI app
app = FastAPI(
    title="Ruth AI Unified Runtime",
    version="1.0.0",
    description="Multi-model AI inference platform for Ruth AI",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Configure based on environment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request ID middleware
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Add request ID to context and response headers."""
    config = get_config()

    # Get request ID from header or generate new one
    request_id = request.headers.get(config.request_id_header, str(uuid.uuid4()))

    # Set in logging context
    set_request_id(request_id)

    try:
        response = await call_next(request)
        response.headers[config.request_id_header] = request_id
        return response
    finally:
        # Clear request ID from context
        clear_request_id()


# Include route modules
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(capabilities.router, prefix="/capabilities", tags=["capabilities"])
app.include_router(inference.router, prefix="/inference", tags=["inference"])
app.include_router(metrics.router, prefix="/metrics", tags=["metrics"])


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors gracefully."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": exc.errors(),
            "body": exc.body,
        },
    )


@app.get("/", tags=["root"])
async def root():
    """Root endpoint - basic service information."""
    return {
        "service": "Ruth AI Unified Runtime",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "capabilities": "/capabilities",
            "inference": "/inference",
            "docs": "/docs",
        }
    }


if __name__ == "__main__":
    # Get configuration from environment
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8000"))
    log_level = os.getenv("LOG_LEVEL", "info").lower()

    uvicorn.run(
        "ai.server.main:app",
        host=host,
        port=port,
        log_level=log_level,
        access_log=True,
        reload=False,  # Disable in production
    )
