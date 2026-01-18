# Ruth AI Unified Runtime - Quick Start Guide

**Phase 1 MVP** - Get the unified runtime running in 5 minutes

---

## Prerequisites

- Python 3.11
- Docker & Docker Compose (for container deployment)
- curl (for testing)

---

## Option 1: Local Development (Fastest)

```bash
# 1. Navigate to ai directory
cd /home/ruth-ai-vas-ms-v2/ai

# 2. Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run server (takes ~10 seconds to start)
python -m uvicorn server.main:app --reload --port 8012
```

**Expected output:**
```
INFO:     Ruth AI Unified Runtime starting...
INFO:     Models root: /home/ruth-ai-vas-ms-v2/ai/models
INFO:     Scanning for model plugins...
INFO:     Discovery complete: 1 models, 1 versions, 1 valid
INFO:     Loading fall_detection:1.0.0...
INFO:     ✓ Loaded fall_detection:1.0.0
INFO:     ✅ Runtime ready: 1/1 models available for inference
INFO:     Uvicorn running on http://0.0.0.0:8012
```

---

## Option 2: Docker (Production-like)

```bash
# From repository root
cd /home/ruth-ai-vas-ms-v2

# Build and start
docker-compose -f ai/docker-compose.unified.yml up --build

# In another terminal, test:
curl http://localhost:8012/health
```

---

## Testing the Endpoints

### 1. Health Check

```bash
curl http://localhost:8012/health
```

**Expected:**
```json
{
  "status": "healthy",
  "runtime_id": "unified-runtime-...",
  "models_loaded": 1,
  "models_ready": 1
}
```

### 2. Capabilities

```bash
curl http://localhost:8012/capabilities
```

**Expected:**
```json
{
  "runtime_id": "unified-runtime-...",
  "models": [
    {
      "model_id": "fall_detection",
      "version": "1.0.0",
      "state": "ready",
      "health": "healthy"
    }
  ]
}
```

### 3. Inference (Stub)

```bash
curl -X POST http://localhost:8012/inference \
  -H "Content-Type: application/json" \
  -d '{
    "stream_id": "550e8400-e29b-41d4-a716-446655440000",
    "frame_reference": "test",
    "timestamp": "2026-01-18T12:00:00Z",
    "model_id": "fall_detection"
  }'
```

**Expected:**
```json
{
  "request_id": "...",
  "status": "success",
  "model_id": "fall_detection",
  "result": {
    "violation_detected": false,
    "confidence": 0.0,
    "metadata": {
      "note": "MVP stub response"
    }
  }
}
```

### 4. Interactive API Docs

Open in browser: http://localhost:8012/docs

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'fastapi'"
- You're not in the virtual environment
- Run: `source ai/.venv/bin/activate`

### "Port 8012 already in use"
- Check what's using the port: `lsof -i :8012`
- Change port: `uvicorn server.main:app --port 8013`

### "Models not loading"
- Check logs for errors
- Verify `ai/models/fall_detection/1.0.0/model.yaml` exists
- Check model.yaml is valid YAML

### Server starts but endpoints return 503
- Wait a few seconds (model loading in progress)
- Check logs for errors

---

## What You Should See

1. **Startup logs:** Model discovery, validation, loading
2. **Health:** Status "healthy", 1 model loaded
3. **Capabilities:** fall_detection listed
4. **Inference:** Returns stub response with valid schema

---

## Next Steps

- ✅ Phase 1 MVP is working!
- ⏭️ Phase 2: Add frame resolution and real inference
- ⏭️ Phase 3: Add GPU support and metrics
- ⏭️ Phase 4: Add multiple models

---

**Need Help?**
- Check `ai/README.md` for detailed documentation
- Check `PHASE_1_MVP_COMPLETE.md` for implementation details
- Review server logs for errors
