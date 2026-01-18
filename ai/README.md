# Ruth AI Unified Runtime

**Status:** Phase 1 MVP Complete ✅
**Version:** 1.0.0
**Build Date:** 2026-01-18

---

## Overview

The Ruth AI Unified Runtime is a **multi-model AI inference platform** that treats models as self-describing plugins. It provides a model-agnostic execution environment where models declare their capabilities through contracts and are loaded, validated, and executed in isolation.

**Key Features:**
- ✅ **Model-Agnostic** - Runtime knows nothing about what models do
- ✅ **Plugin Architecture** - Models are self-contained directories with contracts
- ✅ **Failure Isolation** - One model's crash doesn't affect others
- ✅ **Zero-Disruption Integration** - Add new models without runtime changes
- ✅ **HTTP/REST API** - FastAPI-based endpoints for health, capabilities, inference

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  UNIFIED AI RUNTIME                         │
├─────────────────────────────────────────────────────────────┤
│  FastAPI Server (ai/server/)                                │
│  ├── /health          Health status & model counts          │
│  ├── /capabilities    Available models & specs              │
│  └── /inference       Submit inference requests             │
├─────────────────────────────────────────────────────────────┤
│  Runtime Core (ai/runtime/)                                 │
│  ├── ModelRegistry     Track loaded models                  │
│  ├── DiscoveryScanner  Find model plugins                   │
│  ├── ContractValidator Validate model.yaml                  │
│  ├── ModelLoader       Load weights & code                  │
│  ├── InferencePipeline Route requests to models             │
│  └── SandboxManager    Isolate model execution              │
├─────────────────────────────────────────────────────────────┤
│  Model Plugins (ai/models/)                                 │
│  └── <model_id>/<version>/                                  │
│      ├── model.yaml       Model contract                    │
│      ├── inference.py     Inference entry point             │
│      ├── preprocess.py    Input preprocessing (optional)    │
│      └── weights/         Model weights directory           │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 1 MVP Deliverables

### ✅ Completed

1. **FastAPI Server** ([ai/server/](server/))
   - `main.py` - Application entry point with lifespan management
   - `routes/health.py` - Health endpoint
   - `routes/capabilities.py` - Capabilities endpoint
   - `routes/inference.py` - Inference endpoint (stub for MVP)
   - `dependencies.py` - Dependency injection

2. **Sample Model Plugin** ([ai/models/fall_detection/1.0.0/](models/fall_detection/1.0.0/))
   - `model.yaml` - Complete contract specification
   - `inference.py` - MVP stub (returns valid schema)
   - `preprocess.py` - Image preprocessing logic
   - `weights/` - Placeholder directory

3. **Docker Configuration**
   - `Dockerfile` - Multi-stage build (CPU-only for MVP)
   - `docker-compose.unified.yml` - Standalone compose file
   - `requirements.txt` - Python dependencies

4. **Runtime Integration**
   - Existing `ai/runtime/` components (11,198 lines) fully integrated
   - Model discovery, validation, loading, and execution working

### 🚧 Deferred to Phase 2

- **Frame Resolution**: Backend sends frame references, but actual frame data resolution not yet implemented
- **Real Inference**: fall_detection model uses stub responses (contract validated, weights loading stubbed)
- **Backend Routing**: New backend router to route requests to unified runtime vs containers

---

## Quick Start

### Local Development (Without Docker)

```bash
cd ai

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run server
python -m uvicorn server.main:app --reload --port 8012

# Test endpoints
curl http://localhost:8012/health
curl http://localhost:8012/capabilities
curl -X POST http://localhost:8012/inference \
  -H "Content-Type: application/json" \
  -d '{
    "stream_id": "550e8400-e29b-41d4-a716-446655440000",
    "frame_reference": "test",
    "timestamp": "2026-01-18T12:00:00Z",
    "model_id": "fall_detection"
  }'
```

### Docker (Production)

```bash
# Build and run unified runtime only
docker-compose -f ai/docker-compose.unified.yml up --build

# Or integrate with main stack
docker-compose -f docker-compose.yml -f ai/docker-compose.unified.yml up

# Test endpoints
curl http://localhost:8012/health
curl http://localhost:8012/capabilities
```

### Accessing the API

- **Base URL**: `http://localhost:8012`
- **Interactive Docs**: `http://localhost:8012/docs` (Swagger UI)
- **ReDoc**: `http://localhost:8012/redoc`

---

## Endpoints

### `GET /health`

Returns runtime health status and model counts.

**Response:**
```json
{
  "status": "healthy",
  "runtime_id": "unified-runtime-abc123",
  "models_loaded": 1,
  "models_healthy": 1,
  "models_degraded": 0,
  "models_unhealthy": 0,
  "models_ready": 1
}
```

### `GET /capabilities`

Lists all loaded models and their capabilities.

**Response:**
```json
{
  "runtime_id": "unified-runtime-abc123",
  "runtime_version": "1.0.0",
  "timestamp": "2026-01-18T12:00:00Z",
  "hardware_type": "cpu",
  "models": [
    {
      "model_id": "fall_detection",
      "version": "1.0.0",
      "display_name": "Fall Detection",
      "state": "ready",
      "health": "healthy",
      "input_type": "frame",
      "supports_cpu": true,
      "supports_gpu": true,
      "inference_time_hint_ms": 200
    }
  ],
  "total_models": 1,
  "ready_models": 1
}
```

### `POST /inference`

Submit inference request (MVP returns stub responses).

**Request:**
```json
{
  "stream_id": "550e8400-e29b-41d4-a716-446655440000",
  "device_id": "660e8400-e29b-41d4-a716-446655440001",
  "frame_reference": "vas://frame/123456",
  "timestamp": "2026-01-18T12:00:00Z",
  "model_id": "fall_detection",
  "model_version": "1.0.0",
  "priority": 5
}
```

**Response:**
```json
{
  "request_id": "770e8400-e29b-41d4-a716-446655440002",
  "status": "success",
  "model_id": "fall_detection",
  "model_version": "1.0.0",
  "inference_time_ms": 0.0,
  "result": {
    "event_type": "no_detection",
    "confidence": 0.0,
    "bounding_boxes": [],
    "metadata": {
      "note": "MVP stub response"
    }
  }
}
```

---

## Adding New Models

To add a new model to the unified runtime:

1. **Create model directory:**
   ```bash
   mkdir -p ai/models/<model_id>/<version>/weights
   ```

2. **Create model.yaml contract:**
   ```yaml
   contract_schema_version: "1.0.0"
   model_id: "your_model"
   version: "1.0.0"
   display_name: "Your Model"

   input:
     type: "frame"
     format: "raw_bgr"
     # ... see models/fall_detection/1.0.0/model.yaml for full schema

   output:
     schema_version: "1.0"
     schema:
       # ... define your output schema

   hardware:
     supports_cpu: true
     supports_gpu: true

   performance:
     inference_time_hint_ms: 100
   ```

3. **Create inference.py:**
   ```python
   import numpy as np
   from typing import Dict, Any

   def infer(frame: np.ndarray, **kwargs) -> Dict[str, Any]:
       """Run inference on frame."""
       # Your inference logic here
       return {
           # Return data matching your output schema
       }
   ```

4. **Restart runtime:**
   ```bash
   docker-compose -f ai/docker-compose.unified.yml restart
   ```

The model will be automatically discovered, validated, and loaded!

---

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MODELS_ROOT` | `/app/ai/models` | Root directory for model plugins |
| `SERVER_HOST` | `0.0.0.0` | Server bind address |
| `SERVER_PORT` | `8000` | Server port |
| `LOG_LEVEL` | `info` | Logging level (debug, info, warning, error) |
| `MAX_CONCURRENT_INFERENCES` | `10` | Max concurrent inference requests |
| `RUNTIME_ID` | Auto-generated | Unique runtime instance ID |

---

## Known Limitations (MVP)

1. **No Frame Resolution**: Backend sends opaque frame references, but runtime doesn't yet resolve them to actual image data. Phase 2 will add frame resolver.

2. **Stub Inference**: fall_detection model returns valid schema but doesn't run actual inference. Phase 2 will integrate real YOLOv7-Pose model.

3. **CPU Only**: MVP uses CPU-only PyTorch. Phase 3 will add GPU support with CUDA.

4. **No Backend Integration**: Backend doesn't yet route requests to unified runtime. Phase 2 will add routing logic.

5. **No Metrics**: Prometheus metrics deferred to Phase 3.

---

## Next Steps: Phase 2

1. **Frame Resolver** - Resolve `vas://frame/uuid` to actual pixel data
2. **Real Inference** - Load actual YOLOv7-Pose weights and run inference
3. **Backend Router** - Route model requests to unified runtime vs containers
4. **Integration Testing** - End-to-end validation with backend

---

## Troubleshooting

**Models not loading?**
- Check `docker logs ruth-ai-unified-runtime`
- Verify model.yaml is valid YAML
- Ensure model_id and version match directory names

**Server won't start?**
- Check port 8012 is not in use: `lsof -i :8012`
- Verify Python 3.11 is installed
- Check requirements.txt dependencies installed

**Health endpoint returns 503?**
- Runtime still initializing (wait for health check to pass)
- Check model discovery logs

---

## Documentation

- **Architecture Design**: `docs/ai-runtime-architecture.md`
- **Model Contract Spec**: `docs/ai-model-contract.md`
- **Implementation Spec**: `RUTHAI_UNIFIED_RUNTIME_SPECIFICATION.md`

---

## License

Ruth AI Unified Runtime - Part of the Ruth AI VAS-MS-V2 project.
