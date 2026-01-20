# Ruth AI Unified Runtime - Multi-stage Dockerfile
# Phase 1 MVP - CPU-only build
# Phase 3 will add GPU support with CUDA base images

# ============================================
# Stage 1: Base image with Python
# ============================================
FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    libgomp1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# ============================================
# Stage 2: Install Python dependencies
# ============================================
FROM base AS dependencies

# Copy requirements first for better caching
COPY requirements.txt /tmp/requirements.txt

# Install Python packages
# Note: torch CPU version is used for MVP
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ============================================
# Stage 3: Runtime image
# ============================================
FROM base AS runtime

# Copy installed packages from dependencies stage
COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# Copy application code
COPY runtime/ /app/ai/runtime/
COPY server/ /app/ai/server/
COPY models/ /app/ai/models/
COPY __init__.py /app/ai/__init__.py

# Create models directory (will be mounted as volume in production)
RUN mkdir -p /app/ai/models

# Set environment variables
ENV PYTHONPATH=/app
ENV MODELS_ROOT=/app/ai/models
ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8000
ENV LOG_LEVEL=info
ENV MAX_CONCURRENT_INFERENCES=10

# Expose HTTP port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=90s \
    CMD curl -f http://localhost:8000/health || exit 1

# Run server
CMD ["python", "-m", "uvicorn", "ai.server.main:app", "--host", "0.0.0.0", "--port", "8000"]
