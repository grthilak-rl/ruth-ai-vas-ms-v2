# Ruth AI Unified Runtime - Multi-stage Dockerfile
# Supports CPU, GPU (CUDA), and Jetson (L4T) builds via build args
#
# Build variants:
#   CPU:    docker build -t ruth-ai-runtime:cpu --build-arg VARIANT=cpu .
#   GPU:    docker build -t ruth-ai-runtime:gpu --build-arg VARIANT=gpu .
#   Jetson: docker build -t ruth-ai-runtime:jetson --build-arg VARIANT=jetson .
#
# Default build is CPU for development/CI compatibility

# =============================================================================
# Build Arguments
# =============================================================================
ARG VARIANT=cpu
ARG PYTHON_VERSION=3.11

# =============================================================================
# Stage 1: Base images per variant
# =============================================================================

# CPU base image
FROM python:${PYTHON_VERSION}-slim AS base-cpu
ENV AI_RUNTIME_HARDWARE=cpu
ENV TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

# GPU base image (CUDA 12.1)
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04 AS base-gpu
ENV AI_RUNTIME_HARDWARE=gpu
ENV TORCH_INDEX_URL=https://download.pytorch.org/whl/cu121
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
# Install Python for GPU base
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3-pip \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && rm -rf /var/lib/apt/lists/*

# Jetson base image (L4T - JetPack 5.x)
FROM nvcr.io/nvidia/l4t-pytorch:r35.2.1-pth2.0-py3 AS base-jetson
ENV AI_RUNTIME_HARDWARE=jetson
ENV TORCH_INDEX_URL=""
# Jetson already has PyTorch installed via JetPack

# Select base image based on variant
FROM base-${VARIANT} AS base

WORKDIR /app

# =============================================================================
# Stage 2: Install system dependencies
# =============================================================================
FROM base AS system-deps

# Install common system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# =============================================================================
# Stage 3: Install Python dependencies
# =============================================================================
FROM system-deps AS dependencies

# Re-declare ARG for this stage
ARG VARIANT=cpu

# Copy requirements
COPY requirements.txt /tmp/requirements.txt
COPY requirements-gpu.txt /tmp/requirements-gpu.txt

# Install Python packages based on variant
RUN if [ "$VARIANT" = "cpu" ]; then \
        pip install --no-cache-dir -r /tmp/requirements.txt; \
    elif [ "$VARIANT" = "gpu" ]; then \
        pip install --no-cache-dir -r /tmp/requirements-gpu.txt; \
    elif [ "$VARIANT" = "jetson" ]; then \
        # Jetson has PyTorch pre-installed, install remaining deps
        pip install --no-cache-dir \
            fastapi==0.109.0 \
            uvicorn[standard]==0.27.0 \
            pydantic==2.5.3 \
            pydantic-settings==2.1.0 \
            httpx==0.26.0 \
            pyyaml==6.0.1 \
            opencv-python-headless==4.9.0.80 \
            pillow==10.2.0 \
            prometheus-client==0.19.0 \
            python-multipart==0.0.6; \
    fi

# =============================================================================
# Stage 4: Runtime image
# =============================================================================
FROM system-deps AS runtime

# Re-declare for this stage
ARG VARIANT=cpu

# Copy installed packages from dependencies stage
COPY --from=dependencies /usr/local/lib/python3*/dist-packages /usr/local/lib/python3.11/dist-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# For Jetson, packages are in different location
RUN if [ "$VARIANT" = "jetson" ]; then \
        cp -r /usr/lib/python3/dist-packages/* /usr/local/lib/python3.11/dist-packages/ 2>/dev/null || true; \
    fi

# Copy application code
COPY runtime/ /app/ai/runtime/
COPY server/ /app/ai/server/
COPY observability/ /app/ai/observability/
COPY models/ /app/ai/models/
COPY __init__.py /app/ai/__init__.py

# Create models directory (will be mounted as volume in production)
RUN mkdir -p /app/ai/models

# =============================================================================
# Environment Configuration (12-Factor Compliant)
# =============================================================================

# Python environment
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Server configuration
ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8000
ENV LOG_LEVEL=info
ENV LOG_FORMAT=json

# Runtime configuration
ENV MODELS_ROOT=/app/ai/models
ENV MAX_CONCURRENT_INFERENCES=10
ENV MODEL_WARMUP_ENABLED=true
ENV MODEL_LOAD_TIMEOUT_MS=60000

# GPU configuration (defaults, overridden by hardware detection)
ENV ENABLE_GPU=true
ENV GPU_MEMORY_RESERVE_MB=512
ENV GPU_FALLBACK_TO_CPU=true

# Metrics configuration
ENV METRICS_ENABLED=true
ENV METRICS_UPDATE_INTERVAL_SECONDS=15

# Observability
ENV REQUEST_ID_HEADER=X-Request-ID

# =============================================================================
# Container Configuration
# =============================================================================

# Create non-root user for security
RUN groupadd -r ruth && useradd -r -g ruth ruth \
    && chown -R ruth:ruth /app

# Switch to non-root user
USER ruth

# Expose HTTP port
EXPOSE 8000

# Health check - uses /health/ready for proper readiness validation
# start-period allows 90s for model loading before health checks begin
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=90s \
    CMD curl -f http://localhost:8000/health/ready || exit 1

# Graceful shutdown: uvicorn handles SIGTERM, 30s timeout for in-flight requests
STOPSIGNAL SIGTERM

# Run server with graceful shutdown support
# --timeout-graceful-shutdown: wait for in-flight requests before terminating
CMD ["python", "-m", "uvicorn", "ai.server.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--timeout-graceful-shutdown", "30"]
