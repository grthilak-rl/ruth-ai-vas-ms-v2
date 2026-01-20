# AI Runtime Hardening - Phase 1, 2, 3, 4 Implementation

**Branch:** `ai-runtime-fix`
**Date:** January 2026
**Status:** Complete

---

## Overview

This document describes the implementation of four phases of AI Runtime hardening based on the code review findings. These changes prepare the unified runtime for production containerization without affecting the currently running Ruth AI system.

---

## Phase 1: Core Integration Fixes

**Goal:** Fix critical integration issues identified in code review.

### 1.1 GPU Manager Integration with Model Loader

**File:** `ai/runtime/loader.py`

**Problem:** GPU manager existed but wasn't integrated with the model loading process.

**Solution:**
- Added optional `gpu_manager` parameter to `ModelLoader.__init__()`
- Added `_allocate_device()` method to request GPU memory before loading
- Added `_release_device()` method to free GPU memory on unload
- Added `device` field to `LoadedModel` dataclass to track allocation

**Key Code:**
```python
class ModelLoader:
    def __init__(
        self,
        gpu_manager: Optional["GPUManager"] = None,
        default_memory_estimate_mb: float = 2048.0,
    ):
        self.gpu_manager = gpu_manager
        self._gpu_allocations: dict[str, str] = {}  # qualified_id -> device
```

### 1.2 Model Coordinator for Atomic State Transitions

**File:** `ai/runtime/coordinator.py` (NEW)

**Problem:** Registry state and sandbox creation weren't atomic, leading to potential inconsistencies.

**Solution:**
- Created `ModelCoordinator` class that wraps Registry and SandboxManager
- Ensures atomic transitions: sandbox creation + state update happen together
- Added `verify_invariants()` and `repair_invariants()` for crash recovery

**Key Classes:**
```python
class CoordinationResult:
    success: bool
    model_id: str
    version: str
    action: str
    previous_state: Optional[LoadState]
    new_state: Optional[LoadState]
    error: Optional[str]
    timestamp: datetime

class ModelCoordinator:
    def activate_model(self, ...) -> CoordinationResult
    def deactivate_model(self, ...) -> CoordinationResult
    def get_ready_sandbox(self, ...) -> Optional[ExecutionSandbox]
    def verify_invariants(self) -> dict[str, Any]
    def repair_invariants(self) -> dict[str, Any]
```

### 1.3 Thread Pool Cancellation Improvements

**File:** `ai/runtime/sandbox.py`

**Problem:** ThreadPoolExecutor can't truly cancel running tasks, leading to potential zombie tasks.

**Solution:**
- Added `ExecutorMode` enum (THREAD vs PROCESS) for future ProcessPoolExecutor support
- Added zombie task detection via `get_zombie_tasks(threshold_seconds)`
- Added `get_stats()` method for monitoring pending task counts
- Enhanced `SandboxManager` with `get_all_zombie_tasks()` and `get_total_pending_tasks()`

**Key Code:**
```python
class ExecutorMode(Enum):
    THREAD = "thread"
    PROCESS = "process"

class TimeoutExecutor:
    def get_zombie_tasks(self, threshold_seconds: float = 60.0) -> list[dict]
    def get_stats(self) -> dict[str, Any]
```

### Phase 1 Test Coverage

**File:** `ai/tests/test_runtime_phase1.py`

- 27 unit tests covering GPU integration, coordinator, and executor enhancements
- All tests passing

---

## Phase 2: Server & Observability

**Goal:** Enable container health checks and monitoring.

### 2.1 Container Health Probe Endpoints

**File:** `ai/server/routes/health.py`

**Added Endpoints:**

| Endpoint | Purpose | Response |
|----------|---------|----------|
| `GET /health/live` | Kubernetes liveness probe | Always 200 if server running |
| `GET /health/ready` | Kubernetes readiness probe | 200 if models loaded, 503 otherwise |
| `GET /health` | Detailed health (existing) | Model counts, GPU info |

**Liveness Probe:**
```python
@router.get("/live")
async def liveness_probe() -> LivenessResponse:
    return LivenessResponse(
        status="alive",
        timestamp=datetime.now(timezone.utc).isoformat()
    )
```

**Readiness Probe:**
- Checks registry is initialized
- Checks at least one model is READY
- Checks sandbox manager is available
- Returns "degraded" status if some models unhealthy

### 2.2 Prometheus Metrics

**File:** `ai/observability/metrics.py` (already existed)

Already implemented with:
- `inference_requests_total` - Counter by model and status
- `inference_duration_seconds` - Histogram by model
- `model_load_status` - Gauge (1=loaded, 0=unloaded)
- `model_health_status` - Gauge (1=healthy, 0=degraded, -1=unhealthy)
- `gpu_memory_used_bytes` - Gauge per device
- `gpu_utilization_percent` - Gauge per device

### 2.3 Dockerfile Health Check Update

**File:** `ai/Dockerfile`

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=90s \
    CMD curl -f http://localhost:8000/health/ready || exit 1
```

### Phase 2 Test Coverage

**File:** `ai/tests/test_runtime_phase2.py`

- 18 tests covering liveness, readiness, health, metrics, and container simulation
- All tests passing

---

## Phase 3: Containerization

**Goal:** Enable multi-architecture container builds and graceful shutdown.

### 3.1 Multi-Stage Dockerfile with GPU/CPU/Jetson Variants

**File:** `ai/Dockerfile`

**Build Variants:**

| Variant | Base Image | Use Case |
|---------|------------|----------|
| `cpu` (default) | `python:3.11-slim` | Development, CI, CPU-only servers |
| `gpu` | `nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04` | NVIDIA discrete GPUs |
| `jetson` | `nvcr.io/nvidia/l4t-pytorch:r35.2.1-pth2.0-py3` | NVIDIA Jetson edge devices |

**Build Commands:**
```bash
# CPU build (default)
docker build -t ruth-ai-runtime:cpu --build-arg VARIANT=cpu ai/

# GPU build
docker build -t ruth-ai-runtime:gpu --build-arg VARIANT=gpu ai/

# Jetson build
docker build -t ruth-ai-runtime:jetson --build-arg VARIANT=jetson ai/
```

**Security:**
- Runs as non-root user (`ruth`)
- Uses `STOPSIGNAL SIGTERM` for graceful shutdown

### 3.2 GPU Requirements File

**File:** `ai/requirements-gpu.txt`

Separate requirements for CUDA builds:
```
--extra-index-url https://download.pytorch.org/whl/cu121
torch==2.1.2+cu121
torchvision==0.16.2+cu121
```

### 3.3 Graceful Shutdown Handling

**File:** `ai/server/main.py`

**6-Step Shutdown Sequence:**

1. **Stop accepting new requests** - Handled by uvicorn
2. **Wait for in-flight requests** - `--timeout-graceful-shutdown 30`
3. **Shutdown sandbox executors** - `sandbox_manager.shutdown_all()`
4. **Unload models** - Update registry state, clear metrics
5. **Release GPU resources** - `gpu_manager.release_all()`
6. **Clear dependencies** - `dependencies.clear_all()`

**New Methods:**

`ai/runtime/gpu_manager.py`:
```python
def release_all(self) -> int:
    """Release all GPU memory allocations during shutdown."""
```

`ai/server/dependencies.py`:
```python
def clear_all() -> None:
    """Clear all global instances during shutdown."""
```

### 3.4 12-Factor Configuration

**File:** `ai/server/config.py`

**New Environment Variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `RUTH_AI_ENV` | `production` | Environment (development, test, production) |
| `RUTH_AI_PROFILE` | `prod-cpu` | Deployment profile |
| `AI_RUNTIME_HARDWARE` | `auto` | Hardware mode (auto, cpu, gpu, jetson) |
| `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS` | `30` | Shutdown timeout |

**Dockerfile Environment Variables:**
```dockerfile
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8000
ENV LOG_LEVEL=info
ENV LOG_FORMAT=json
ENV MODELS_ROOT=/app/ai/models
ENV MAX_CONCURRENT_INFERENCES=10
ENV ENABLE_GPU=true
ENV GPU_FALLBACK_TO_CPU=true
ENV METRICS_ENABLED=true
```

### Phase 3 Test Coverage

**File:** `ai/tests/test_runtime_phase3.py`

- 27 tests covering configuration, shutdown, GPU release, Dockerfile validation
- All tests passing

---

## Phase 4: Production Hardening

**Goal:** Add production-grade resilience and security hardening.

### 4.1 Circuit Breaker Persistence

**File:** `ai/runtime/recovery.py`

**Problem:** Circuit breaker state was lost on container restarts, causing previously tripped breakers to reset.

**Solution:**
- Added `CircuitBreakerPersistence` class for file-based state persistence
- Atomic writes using temp file + rename pattern
- State persisted on every state transition

**Key Code:**
```python
class CircuitBreakerPersistence:
    """File-based persistence for circuit breaker state."""
    DEFAULT_STATE_FILE = "/app/data/circuit_breaker_state.json"

    def save_state(self, states: dict[str, CircuitBreakerState]) -> bool:
        """Save circuit breaker states to file (atomic write)."""

    def load_state(self) -> dict[str, dict[str, Any]]:
        """Load circuit breaker states from file."""

    def clear_state(self) -> bool:
        """Delete the state file."""
```

**CircuitBreaker Integration:**
```python
class CircuitBreaker:
    def __init__(
        self,
        persistence: Optional[CircuitBreakerPersistence] = None,
        enable_persistence: bool = False,
    ):
        self._persistence = persistence
        self._enable_persistence = enable_persistence
        self._load_persisted_state()  # Restore on startup
```

### 4.2 Fair RWLock (Writer Starvation Fix)

**File:** `ai/runtime/registry.py`

**Problem:** Original RWLock allowed continuous readers to indefinitely block waiting writers.

**Solution:**
- Implemented writer-preference locking
- Writers waiting causes new readers to block
- Prevents writer starvation while still allowing concurrent reads

**Key Code:**
```python
class _RWLock:
    """Fair read-write lock with writer-preference."""

    def __init__(self):
        self._lock = threading.Lock()
        self._readers_ok = threading.Condition(self._lock)
        self._writers_ok = threading.Condition(self._lock)
        self._readers = 0
        self._writers_waiting = 0
        self._writer_active = False

    def _acquire_read(self) -> None:
        with self._lock:
            # Wait if writer active OR writers waiting (writer-preference)
            while self._writer_active or self._writers_waiting > 0:
                self._readers_ok.wait()
            self._readers += 1
```

### 4.3 Input Validation on Frame Metadata

**File:** `ai/server/routes/inference.py`

**Problem:** No validation on inference request inputs, potential for DoS via large payloads or malformed data.

**Solution:**
- Added comprehensive Pydantic validators for all fields
- UUID validation for stream_id
- Semantic version validation for model_version
- Frame dimension limits (64-7680 pixels)
- Metadata depth limit (5 levels) and size limit (64KB)
- Timestamp drift detection (±24 hours)
- Base64 validation before decode

**Validation Constants:**
```python
MAX_FRAME_BASE64_SIZE = 50 * 1024 * 1024  # 50MB max
MAX_FRAME_WIDTH = 7680   # 8K resolution max
MIN_FRAME_WIDTH = 64     # Minimum frame dimension
MAX_METADATA_SIZE = 65536  # 64KB max
MAX_METADATA_DEPTH = 5   # Max nesting depth
MAX_TIMESTAMP_DRIFT_HOURS = 24
```

**Key Validators:**
```python
class InferenceRequest(BaseModel):
    @field_validator("stream_id")
    def validate_stream_id(cls, v: str) -> str:
        if not UUID_PATTERN.match(v):
            raise ValueError("stream_id must be a valid UUID")
        return v

    @model_validator(mode="after")
    def validate_timestamp_drift(self) -> "InferenceRequest":
        drift = abs((datetime.now(timezone.utc) - self.timestamp).total_seconds())
        if drift > MAX_TIMESTAMP_DRIFT_HOURS * 3600:
            raise ValueError(f"timestamp drift too large: {drift}s")
        return self
```

### Phase 4 Test Coverage

**File:** `ai/tests/test_runtime_phase4.py`

- 24 tests covering:
  - Circuit breaker persistence (save, load, clear, restore on init)
  - Fair RWLock (concurrent readers, exclusive writer, writer not starved)
  - Input validation (UUID, model_id, version, frame format, timestamp, metadata)
  - Frame decoding security
  - Registry concurrent access
- All tests passing

---

## Test Summary

| Phase | Tests | Status |
|-------|-------|--------|
| Phase 1: Core Integration | 27 | ✅ Passing |
| Phase 2: Server & Observability | 18 | ✅ Passing |
| Phase 3: Containerization | 27 | ✅ Passing |
| Phase 4: Production Hardening | 24 | ✅ Passing |
| **Total** | **96** | ✅ **All Passing** |

**Run Tests:**
```bash
source ai/venv/bin/activate
python -m pytest ai/tests/test_runtime_phase1.py ai/tests/test_runtime_phase2.py ai/tests/test_runtime_phase3.py ai/tests/test_runtime_phase4.py -v
```

---

## Files Changed

### Phase 1
| File | Change |
|------|--------|
| `ai/runtime/loader.py` | GPU manager integration |
| `ai/runtime/sandbox.py` | Executor improvements, zombie detection |
| `ai/runtime/coordinator.py` | NEW - Atomic state coordination |
| `ai/tests/test_runtime_phase1.py` | NEW - 27 tests |

### Phase 2
| File | Change |
|------|--------|
| `ai/server/routes/health.py` | Added /live and /ready endpoints |
| `ai/Dockerfile` | Updated HEALTHCHECK to use /health/ready |
| `ai/tests/test_runtime_phase2.py` | NEW - 18 tests |

### Phase 3
| File | Change |
|------|--------|
| `ai/Dockerfile` | Multi-stage build, GPU/CPU/Jetson variants |
| `ai/requirements-gpu.txt` | NEW - CUDA dependencies |
| `ai/server/main.py` | Graceful shutdown sequence |
| `ai/server/config.py` | 12-factor configuration |
| `ai/server/dependencies.py` | Added clear_all() |
| `ai/runtime/gpu_manager.py` | Added release_all() |
| `ai/tests/test_runtime_phase3.py` | NEW - 27 tests |

### Phase 4
| File | Change |
|------|--------|
| `ai/runtime/recovery.py` | Added CircuitBreakerPersistence class |
| `ai/runtime/registry.py` | Fixed RWLock writer starvation |
| `ai/server/routes/inference.py` | Added comprehensive input validation |
| `ai/tests/test_runtime_phase4.py` | NEW - 24 tests |

---

## Deployment Notes

### Container Health Checks

**Docker Compose:**
```yaml
services:
  ruth-ai-runtime:
    image: ruth-ai-runtime:cpu
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health/ready"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 90s
```

**Kubernetes:**
```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 15

readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  initialDelaySeconds: 60
  periodSeconds: 10
```

### GPU Deployment

```yaml
services:
  ruth-ai-runtime:
    image: ruth-ai-runtime:gpu
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - AI_RUNTIME_HARDWARE=gpu
```

---

## Next Steps

The AI Runtime is now ready for containerization. Remaining work:

1. **CI/CD Integration** - Add Docker build to pipeline
2. **Registry Push** - Push images to container registry
3. **Integration Testing** - Test with backend in Docker Compose
4. **Production Deployment** - Deploy alongside existing containers

---

## References

- [Infrastructure Deployment Design](../docs/infrastructure-deployment-design.md)
- [AI Runtime Architecture](../docs/ai-runtime-architecture.md)
- [Code Review Findings](../RUTHAI_UNIFIED_RUNTIME_SPECIFICATION.md)
