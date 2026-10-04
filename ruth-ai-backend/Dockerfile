# Ruth AI Backend Dockerfile
# Python 3.11 FastAPI application
#
# Build: docker build -t ruth-ai-backend .
# Run:   docker run -p 8080:8080 ruth-ai-backend

FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files and README (required by hatch build)
COPY pyproject.toml README.md constraints.txt ./

# Install pip and upgrade (pinned to the versions in the running image).
# Constrained too: wheel depends on packaging, which would otherwise float.
RUN pip install --no-cache-dir --upgrade -c constraints.txt pip==26.1.2 setuptools==79.0.1 wheel==0.46.3

# Install dependencies. constraints.txt pins every transitive dependency to
# what production runs; pyproject.toml ranges alone let a rebuild drift.
RUN pip install --no-cache-dir -c constraints.txt .

# ============================================
# Production image
# ============================================
FROM python:3.11-slim-bookworm

WORKDIR /app
ENV PYTHONPATH=/app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser migrations/ ./migrations/
COPY --chown=appuser:appuser alembic.ini ./

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/api/v1/health || exit 1

# Start the application: run migrations, then exec uvicorn so it becomes PID 1
CMD ["bash", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8080"]