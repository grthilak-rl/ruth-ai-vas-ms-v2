# PPE Detection Model

Multi-model Personal Protective Equipment (PPE) detection service for Ruth AI using YOLOv8.

## Overview

This model service detects PPE compliance and violations using 12 specialized YOLOv8 models. Each model is trained for optimal accuracy on specific PPE items, providing better detection than a single multi-class model.

### Supported PPE Items

**Presence Detection (both_classes models):**
- Hardhat
- Safety Vest
- Goggles
- Gloves
- Boots
- Person

**Violation Detection (no_classes models):**
- No Hardhat
- No Vest
- No Goggles
- No Gloves
- No Boots
- No Mask

## Detection Modes

| Mode | Description | Models Used |
|------|-------------|-------------|
| `presence` | Detect PPE items that are worn | both_classes (6 models) |
| `violation` | Detect missing PPE items | no_classes (6 models) |
| `full` | Complete analysis (default) | All 12 models |

## Directory Structure

```
ppe-detection-model/
├── app.py                 # FastAPI application
├── detector.py            # Multi-model PPE inference logic
├── Dockerfile             # Container configuration
├── model.yaml             # Ruth AI model contract
├── requirements.txt       # Python dependencies
├── run_local.sh           # Local development script
├── README.md              # This file
└── weights/
    ├── both_classes/      # Presence detection models
    │   ├── boots.pt
    │   ├── gloves.pt
    │   ├── goggles.pt
    │   ├── hardhat.pt
    │   ├── person.pt
    │   └── vest.pt
    └── no_classes/        # Violation detection models
        ├── no_boots.pt
        ├── no_gloves.pt
        ├── no_goggles.pt
        ├── no_hardhat.pt
        ├── no_mask.pt
        └── no_vest.pt
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Service information |
| `/health` | GET | Health check |
| `/info` | GET | Model information and capabilities |
| `/models` | GET | Status of all loaded models |
| `/detect` | POST | Single image detection |
| `/detect/batch` | POST | Batch image detection |
| `/threshold` | PUT | Update confidence threshold |
| `/thresholds` | GET | Get all confidence thresholds |
| `/docs` | GET | Swagger documentation |

## Quick Start

### Local Development

```bash
# Make script executable
chmod +x run_local.sh

# Run locally
./run_local.sh
```

The service will start on `http://localhost:8001`.

### Docker

```bash
# Build image
docker build -t ppe-detection-model:1.0.0 .

# Run container
docker run -d \
  --name ppe-detection \
  -p 8001:8001 \
  -e AI_DEVICE=auto \
  -e PPE_CONFIDENCE_THRESHOLD=0.5 \
  ppe-detection-model:1.0.0
```

### Docker with GPU

```bash
docker run -d \
  --name ppe-detection \
  --gpus all \
  -p 8001:8001 \
  -e AI_DEVICE=cuda \
  ppe-detection-model:1.0.0
```

## Usage Examples

### Health Check

```bash
curl http://localhost:8001/health
```

Response:
```json
{
  "status": "healthy",
  "service": "ppe-detection-model",
  "version": "1.0.0",
  "model_loaded": true,
  "models_count": 12,
  "device": "cuda"
}
```

### Single Image Detection

```bash
# Full mode (default)
curl -X POST "http://localhost:8001/detect" \
  -F "file=@/path/to/image.jpg"

# Presence mode only
curl -X POST "http://localhost:8001/detect?mode=presence" \
  -F "file=@/path/to/image.jpg"

# Violation mode only
curl -X POST "http://localhost:8001/detect?mode=violation" \
  -F "file=@/path/to/image.jpg"

# With custom confidence threshold
curl -X POST "http://localhost:8001/detect?mode=full&confidence=0.6" \
  -F "file=@/path/to/image.jpg"
```

Response:
```json
{
  "success": true,
  "model": "ppe-detection",
  "violation_detected": true,
  "violation_type": "ppe_violation",
  "severity": "medium",
  "confidence": 0.78,
  "detections": [
    {
      "item": "hardhat",
      "status": "present",
      "confidence": 0.92,
      "bbox": [180.0, 55.0, 270.0, 120.0],
      "class_id": 0,
      "class_name": "hardhat",
      "model_source": "hardhat"
    },
    {
      "item": "goggles",
      "status": "missing",
      "confidence": 0.72,
      "bbox": [150.0, 60.0, 300.0, 200.0],
      "class_id": 0,
      "class_name": "no_goggles",
      "model_source": "no_goggles"
    }
  ],
  "persons_detected": 1,
  "violations": ["goggles"],
  "ppe_present": ["hardhat", "vest"],
  "detection_count": 4,
  "model_name": "ppe_detector",
  "model_version": "1.0.0",
  "mode": "full",
  "inference_time_ms": 145.32,
  "timestamp": "2026-01-17T10:30:00Z"
}
```

### Batch Detection

```bash
curl -X POST "http://localhost:8001/detect/batch" \
  -F "files=@/path/to/image1.jpg" \
  -F "files=@/path/to/image2.jpg" \
  -F "files=@/path/to/image3.jpg"
```

### Update Threshold

```bash
curl -X PUT "http://localhost:8001/threshold" \
  -H "Content-Type: application/json" \
  -d '{"model_name": "hardhat", "threshold": 0.6}'
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_DEVICE` | `auto` | Device for inference (`cpu`, `cuda`, `auto`) |
| `PPE_CONFIDENCE_THRESHOLD` | `0.5` | Global confidence threshold |
| `ENVIRONMENT` | `production` | Set to `development` for hot reload |

### Per-Item Thresholds

Default thresholds are optimized per PPE item:

| Item | Default Threshold | Notes |
|------|-------------------|-------|
| hardhat | 0.50 | High visibility item |
| vest | 0.50 | High visibility item |
| goggles | 0.45 | Smaller, harder to detect |
| gloves | 0.40 | Small, often occluded |
| boots | 0.45 | Often partially visible |
| mask | 0.45 | Face-level detection |
| person | 0.50 | Standard detection |

## Severity Calculation

The severity of a violation is calculated based on:

| Severity | Condition |
|----------|-----------|
| `critical` | 2+ critical items missing (hardhat, vest) |
| `high` | 1 critical item missing OR 3+ items missing |
| `medium` | 1-2 non-critical items missing |
| `low` | No violations |

## Integration with Ruth AI

This model follows the Ruth AI Model Contract Specification (v1.0.0). The `model.yaml` file declares:

- Model identity and version
- Input/output specifications
- Hardware compatibility
- Performance hints
- Capabilities

The model can be integrated into the Ruth AI runtime by placing it in the models directory:

```
ai/models/
└── ppe_detection/
    └── 1.0.0/
        ├── model.yaml
        ├── detector.py
        ├── weights/
        │   ├── both_classes/
        │   └── no_classes/
        └── ...
```

## Requirements

- Python 3.9+
- PyTorch 2.1.0+
- Ultralytics 8.0.200+
- FastAPI 0.104.1+
- NVIDIA GPU (optional, for faster inference)

## GPU Memory Requirements

| Configuration | Approximate Memory |
|---------------|-------------------|
| All 12 models (full mode) | ~4GB VRAM |
| 6 models (presence/violation) | ~2GB VRAM |
| CPU mode | ~8GB RAM |

## Performance

Typical inference times on different hardware:

| Hardware | Full Mode | Single Mode |
|----------|-----------|-------------|
| NVIDIA RTX 3080 | ~50ms | ~25ms |
| NVIDIA RTX 2060 | ~100ms | ~50ms |
| Intel i7 (CPU) | ~500ms | ~250ms |

## License

Proprietary - Ruth AI
