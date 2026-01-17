# PPE Detection Model Container
# Uses YOLOv8 with ultralytics for multi-model PPE detection

FROM python:3.10-slim

WORKDIR /app

# Install system dependencies for OpenCV and PyTorch
RUN apt-get update && apt-get install -y \
    build-essential \
    libgl1-mesa-dev \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .
COPY detector.py .

# Copy weights (both_classes and no_classes subdirectories)
# Note: Weights should be mounted as volume in production
COPY weights/ ./weights/

# Create non-root user for security
RUN useradd -m -u 1000 aiuser && chown -R aiuser:aiuser /app
USER aiuser

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV AI_DEVICE=auto
ENV PPE_CONFIDENCE_THRESHOLD=0.5

# Expose port (internal container port - mapped to 8011 on host via docker-compose)
EXPOSE 8000

# Health check (longer start-period for multi-model loading - 12 models)
HEALTHCHECK --interval=30s --timeout=30s --start-period=180s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Start the API server
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
