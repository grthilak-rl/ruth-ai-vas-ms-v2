# Ruth AI Backend

Backend API for the Ruth AI Video Analytics Platform.

## Overview

FastAPI-based backend service that provides:
- Camera and device management
- Event and violation processing
- AI Runtime integration
- VAS (Video Analytics Service) integration

## Quick Start

```bash
# Install dependencies
pip install -e .

# Run development server
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

## Configuration

Configuration is loaded from environment variables. See `app/core/config.py` for available settings.

## API Documentation

When running in development mode, API docs are available at:
- Swagger UI: http://localhost:8080/docs
- ReDoc: http://localhost:8080/redoc
