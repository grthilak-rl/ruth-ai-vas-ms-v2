# Ruth AI NLP Chat Service Dockerfile
# Standalone microservice for natural language database queries

FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Development stage
FROM base AS development

# Install development dependencies
COPY pyproject.toml README.md ./
RUN pip install -e ".[dev]"

# Copy application code
COPY app/ app/

# Expose port
EXPOSE 8081

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8081/health/live || exit 1

# Run with reload for development
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081", "--reload"]

# Production stage
FROM base AS production

# Create non-root user
RUN groupadd --gid 1000 nlpuser && \
    useradd --uid 1000 --gid 1000 --create-home nlpuser

# Install production dependencies only
COPY pyproject.toml README.md ./
RUN pip install .

# Copy application code
COPY --chown=nlpuser:nlpuser app/ app/

# Switch to non-root user
USER nlpuser

# Expose port
EXPOSE 8081

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8081/health/live || exit 1

# Run production server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "2"]
