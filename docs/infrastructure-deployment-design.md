# Ruth AI Infrastructure & Deployment Design

**Version:** 1.0
**Author:** Platform & Infrastructure Authority Agent
**Date:** January 2026
**Status:** PHASE 3 Deliverable - For Review

---

## Executive Summary

This document defines how Ruth AI is deployed, configured, and operated across all supported environments. It establishes deployment principles, container strategies, and operational procedures that enable Ruth AI to run identically on developer laptops, CI runners, GPU-equipped servers, and NVIDIA Jetson edge devices.

**Key Principles:**
- Docker-first deployment; Kubernetes is optional
- Same containers run across CPU, GPU, and ARM64/Jetson without code changes
- AI Runtime declares capabilities; Backend adapts scheduling accordingly
- VAS remains the single video gateway (ports: Backend 8085, Frontend 3200, MediaSoup 3002, PostgreSQL 5433, Redis 6380)
- No cloud-only assumptions; full on-premises support required

---

## Table of Contents

1. [Deployment Philosophy](#1-deployment-philosophy)
2. [Environment Profiles](#2-environment-profiles)
3. [Container & Image Strategy](#3-container--image-strategy)
4. [Docker Compose Reference Architecture](#4-docker-compose-reference-architecture)
5. [Optional Kubernetes Architecture](#5-optional-kubernetes-architecture)
6. [Hardware Adaptation Model](#6-hardware-adaptation-model)
7. [Secrets & Configuration Strategy](#7-secrets--configuration-strategy)
8. [Observability & Operations](#8-observability--operations)
9. [CI/CD Pipeline Design](#9-cicd-pipeline-design)
10. [Risks, Assumptions & Open Questions](#10-risks-assumptions--open-questions)

---

## 1. Deployment Philosophy

### 1.1 Guiding Principles

| Principle | Description | Rationale |
|-----------|-------------|-----------|
| **Docker-First** | Docker Compose is the primary and reference deployment model | Ensures reproducibility without orchestrator lock-in |
| **Kubernetes-Optional** | Kubernetes support is additive, never required | Many deployments are single-node or edge; K8s adds unnecessary complexity |
| **No Cloud Assumptions** | Must work fully on-premises without internet connectivity | Healthcare, industrial, and secure environments require air-gapped operation |
| **Hardware Agnostic Code** | Application code never checks for GPU/CPU/Jetson | Configuration drives behavior; runtime adapts based on declared capabilities |
| **Container Immutability** | Same container image runs in all environments | Eliminates "works on my machine" scenarios |
| **Environment via Configuration** | All environment-specific behavior is configuration-driven | No code branches for dev/test/prod |
| **VAS as External Dependency** | VAS-MS-V2 is treated as an external service, not co-deployed | Clear boundary between Ruth AI and VAS infrastructure |

### 1.2 Non-Negotiable Constraints

1. **Docker Compose must be sufficient** for any production deployment
2. **No Kubernetes-only features** in application code (no K8s API calls, no ConfigMaps in app logic)
3. **No GPU assumptions in Backend code** - Backend calls AI Runtime; it never knows what hardware executes inference
4. **Jetson compatibility preserved** - ARM64 support is mandatory, not optional
5. **VAS integration via documented APIs only** - No direct RTSP, MediaSoup, or VAS database access

### 1.3 Deployment Model Hierarchy

```
Priority 1: Docker Compose (Reference Model)
    - Self-contained deployment
    - All environments use the same compose structure
    - Environment differences via .env files and override files

Priority 2: Kubernetes (Production Multi-Node)
    - Optional for scale-out scenarios
    - Helm charts derived from Compose definitions
    - GPU scheduling via device plugins, not application logic

Priority 3: Raw Containers (Edge/IoT)
    - Direct container execution on Jetson
    - systemd or container runtime managed
    - Same images as Compose/K8s deployments
```

---

## 2. Environment Profiles

### 2.1 Profile Overview

| Profile | Description | GPU Required | Target Hardware | Use Case |
|---------|-------------|--------------|-----------------|----------|
| `dev` | Local development | No | Developer laptop | Daily development, debugging |
| `test` | Integration testing | No | CI runners (GitHub Actions, GitLab CI) | Automated testing, contract validation |
| `prod-cpu` | Production without GPU | No | Standard x86_64 servers | Deployments where GPU is unavailable |
| `prod-gpu` | Production with GPU | Yes | NVIDIA discrete GPU (RTX, Tesla, A-series) | Full performance production |
| `edge-jetson` | Edge deployment | Yes | NVIDIA Jetson (Orin, Xavier, Nano) | Edge AI, low-latency local processing |

### 2.2 Profile Specifications

#### 2.2.1 dev Profile

**Purpose:** Local development and debugging

**Services Running:**
| Service | Included | Notes |
|---------|----------|-------|
| ruth-ai-backend | Yes | Hot reload enabled |
| ruth-ai-runtime | Yes (CPU mode) | Lower FPS, no GPU |
| ruth-ai-portal | Yes | Development server with hot reload |
| PostgreSQL | Yes | Local instance |
| Redis | Yes | Local instance |

**Resource Configuration:**
| Resource | Value | Rationale |
|----------|-------|-----------|
| Backend Memory | 1GB | Sufficient for development |
| Runtime Memory | 2GB | CPU inference requires more memory |
| PostgreSQL Memory | 512MB | Development load is minimal |
| Redis Memory | 256MB | Minimal caching |
| Runtime Max FPS | 5 | Reduces CPU load during development |

**Restart Policy:** `no` (manual restart for debugging)

**Volume Mounts:**
- Source code mounted for hot reload
- Model weights mounted from local directory
- Database data persisted to local volume

**Environment Variables:**
```
RUTH_AI_ENV=development
RUTH_AI_LOG_LEVEL=debug
AI_RUNTIME_HARDWARE=cpu
AI_RUNTIME_MAX_FPS=5
AI_RUNTIME_INFERENCE_TIMEOUT_MS=2000
VAS_BASE_URL=http://10.30.250.245:8085
```

---

#### 2.2.2 test Profile

**Purpose:** CI/CD integration testing and contract validation

**Services Running:**
| Service | Included | Notes |
|---------|----------|-------|
| ruth-ai-backend | Yes | Production-like configuration |
| ruth-ai-runtime | Yes (CPU mode) | Mocked or lightweight model |
| ruth-ai-portal | Optional | Only for E2E tests |
| PostgreSQL | Yes | Ephemeral database |
| Redis | Yes | Ephemeral cache |

**Resource Configuration:**
| Resource | Value | Rationale |
|----------|-------|-----------|
| Backend Memory | 1GB | Match CI runner constraints |
| Runtime Memory | 2GB | CPU inference |
| PostgreSQL Memory | 512MB | Test data is small |
| Redis Memory | 256MB | Minimal caching |
| Runtime Max FPS | 10 | Balance speed and CI resources |

**Restart Policy:** `no` (fail fast for CI)

**Test Isolation:**
- Each test run gets fresh database state
- Network isolated from external services
- VAS can be mocked or pointed to test instance

**Environment Variables:**
```
RUTH_AI_ENV=test
RUTH_AI_LOG_LEVEL=info
AI_RUNTIME_HARDWARE=cpu
AI_RUNTIME_MAX_FPS=10
AI_RUNTIME_INFERENCE_TIMEOUT_MS=1000
VAS_BASE_URL=${VAS_TEST_URL:-http://vas-mock:8085}
DATABASE_URL=postgresql://ruth:ruth_test@postgres:5432/ruth_test
```

---

#### 2.2.3 prod-cpu Profile

**Purpose:** Production deployment without GPU acceleration

**Services Running:**
| Service | Included | Notes |
|---------|----------|-------|
| ruth-ai-backend | Yes | Production configuration |
| ruth-ai-runtime | Yes (CPU mode) | Full model, CPU execution |
| ruth-ai-portal | Yes | Production build |
| PostgreSQL | Yes (or external) | Persistent storage |
| Redis | Yes (or external) | Production caching |

**Resource Configuration:**
| Resource | Value | Rationale |
|----------|-------|-----------|
| Backend Memory | 2GB | Production headroom |
| Backend CPU | 2 cores | Handle concurrent requests |
| Runtime Memory | 4GB | CPU inference memory intensive |
| Runtime CPU | 4 cores | Maximize CPU inference throughput |
| PostgreSQL Memory | 2GB | Production workload |
| Redis Memory | 1GB | Session caching |
| Runtime Max FPS | 30 | Practical limit for CPU |

**Restart Policy:** `unless-stopped`

**Scaling Constraints:**
- Backend: 2 replicas recommended
- Runtime: 1 instance (model loaded once)
- Portal: 2 replicas behind reverse proxy

**Environment Variables:**
```
RUTH_AI_ENV=production
RUTH_AI_LOG_LEVEL=info
AI_RUNTIME_HARDWARE=cpu
AI_RUNTIME_MAX_FPS=30
AI_RUNTIME_INFERENCE_TIMEOUT_MS=500
AI_RUNTIME_MAX_CONCURRENT_STREAMS=5
VAS_BASE_URL=${VAS_BASE_URL}
DATABASE_URL=${DATABASE_URL}
REDIS_URL=${REDIS_URL}
```

---

#### 2.2.4 prod-gpu Profile

**Purpose:** Full performance production with GPU acceleration

**Services Running:**
| Service | Included | Notes |
|---------|----------|-------|
| ruth-ai-backend | Yes | Production configuration |
| ruth-ai-runtime | Yes (GPU mode) | Full model, GPU execution |
| ruth-ai-portal | Yes | Production build |
| PostgreSQL | Yes (or external) | Persistent storage |
| Redis | Yes (or external) | Production caching |

**Resource Configuration:**
| Resource | Value | Rationale |
|----------|-------|-----------|
| Backend Memory | 2GB | Production headroom |
| Backend CPU | 2 cores | Handle concurrent requests |
| Runtime Memory | 4GB | Model and GPU buffer management |
| Runtime GPU | 1 NVIDIA GPU | Full GPU allocation |
| Runtime GPU Memory | 4GB minimum | Depends on model size |
| PostgreSQL Memory | 2GB | Production workload |
| Redis Memory | 1GB | Session caching |
| Runtime Max FPS | 100 | GPU-accelerated throughput |

**Restart Policy:** `unless-stopped`

**GPU Requirements:**
- NVIDIA Driver 525+ installed on host
- NVIDIA Container Toolkit installed
- GPU with CUDA Compute Capability 7.0+ recommended

**Scaling Constraints:**
- Backend: 2+ replicas recommended
- Runtime: 1 instance per GPU (partition cameras if multiple GPUs)
- Portal: 2+ replicas behind reverse proxy

**Environment Variables:**
```
RUTH_AI_ENV=production
RUTH_AI_LOG_LEVEL=info
AI_RUNTIME_HARDWARE=gpu
AI_RUNTIME_MAX_FPS=100
AI_RUNTIME_INFERENCE_TIMEOUT_MS=100
AI_RUNTIME_MAX_CONCURRENT_STREAMS=10
AI_RUNTIME_BATCH_SIZE=4
VAS_BASE_URL=${VAS_BASE_URL}
DATABASE_URL=${DATABASE_URL}
REDIS_URL=${REDIS_URL}
NVIDIA_VISIBLE_DEVICES=all
```

---

#### 2.2.5 edge-jetson Profile

**Purpose:** Edge deployment on NVIDIA Jetson devices

**Services Running:**
| Service | Included | Notes |
|---------|----------|-------|
| ruth-ai-backend | Yes | Lightweight configuration |
| ruth-ai-runtime | Yes (Jetson GPU mode) | Optimized for Jetson |
| ruth-ai-portal | Optional | May run on separate device |
| PostgreSQL | Yes (SQLite alternative) | Embedded database option |
| Redis | Yes | Minimal configuration |

**Resource Configuration:**
| Resource | Value | Rationale |
|----------|-------|-----------|
| Backend Memory | 1GB | Jetson memory constrained |
| Runtime Memory | 2GB | Jetson GPU shared memory |
| Runtime Max FPS | 50 | Jetson GPU throughput |
| PostgreSQL Memory | 512MB | Embedded use case |
| Redis Memory | 256MB | Minimal caching |

**Restart Policy:** `unless-stopped`

**Jetson-Specific Requirements:**
- JetPack 5.0+ installed
- L4T base image for containers
- GPU accessed via Jetson runtime, not standard NVIDIA runtime

**Scaling Constraints:**
- Single-node deployment only
- Backend and Runtime co-located
- Portal may be external (cloud/central server)

**Environment Variables:**
```
RUTH_AI_ENV=production
RUTH_AI_LOG_LEVEL=info
AI_RUNTIME_HARDWARE=jetson
AI_RUNTIME_MAX_FPS=50
AI_RUNTIME_INFERENCE_TIMEOUT_MS=200
AI_RUNTIME_MAX_CONCURRENT_STREAMS=3
VAS_BASE_URL=${VAS_BASE_URL}
DATABASE_URL=${DATABASE_URL:-sqlite:///data/ruth.db}
REDIS_URL=${REDIS_URL:-redis://localhost:6379}
```

---

### 2.3 Profile Selection

Profile selection is determined by environment variables at container startup, not by different images:

```bash
# Development
RUTH_AI_PROFILE=dev docker-compose up

# Production with GPU
RUTH_AI_PROFILE=prod-gpu docker-compose up

# Edge deployment
RUTH_AI_PROFILE=edge-jetson docker-compose up
```

The same container images adapt behavior based on the selected profile.

---

## 3. Container & Image Strategy

### 3.1 Container Inventory

| Container | Purpose | Base Image | Port | GPU Support |
|-----------|---------|------------|------|-------------|
| `ruth-ai-backend` | API, stream management, violation lifecycle | Python 3.11 slim | 8080 | No |
| `ruth-ai-runtime` | AI inference engine | Python 3.11 + CUDA/L4T | 50051 (gRPC) | Yes |
| `ruth-ai-portal` | Operator web interface | Node.js 20 Alpine | 3000 | No |
| `postgres` | Relational database | PostgreSQL 15 Alpine | 5432 | No |
| `redis` | Caching and session store | Redis 7 Alpine | 6379 | No |

### 3.2 Multi-Architecture Strategy

Ruth AI must support two CPU architectures:

| Architecture | Target Hardware | Notes |
|--------------|-----------------|-------|
| `linux/amd64` | x86_64 servers, desktops, cloud VMs | Primary development and production target |
| `linux/arm64` | NVIDIA Jetson, ARM servers | Edge deployment, Apple Silicon development |

**Build Strategy:**

```
Multi-arch manifest approach using Docker Buildx:

ruth-ai-backend:1.0.0
  └── linux/amd64 → ruth-ai-backend:1.0.0-amd64
  └── linux/arm64 → ruth-ai-backend:1.0.0-arm64

ruth-ai-runtime:1.0.0-cpu
  └── linux/amd64 → ruth-ai-runtime:1.0.0-cpu-amd64
  └── linux/arm64 → ruth-ai-runtime:1.0.0-cpu-arm64

ruth-ai-runtime:1.0.0-gpu
  └── linux/amd64 → ruth-ai-runtime:1.0.0-gpu-amd64 (CUDA)
  └── linux/arm64 → ruth-ai-runtime:1.0.0-jetson-arm64 (L4T)
```

**Rationale for Multi-Arch Manifests:**
- `docker pull ruth-ai-backend:1.0.0` automatically selects correct architecture
- No architecture-specific configuration in docker-compose
- CI builds all architectures in parallel

### 3.3 Image Variants

#### 3.3.1 ruth-ai-runtime Variants

The AI Runtime has multiple variants to support different hardware:

| Variant Tag | Base Image | Hardware | Use Case |
|-------------|------------|----------|----------|
| `ruth-ai-runtime:X.Y.Z-cpu` | `python:3.11-slim` | CPU only | Development, CPU production |
| `ruth-ai-runtime:X.Y.Z-gpu` | `nvidia/cuda:12.1-runtime-ubuntu22.04` | NVIDIA discrete GPU | GPU production |
| `ruth-ai-runtime:X.Y.Z-jetson` | `nvcr.io/nvidia/l4t-pytorch:r35.2.1-pth2.0-py3` | NVIDIA Jetson | Edge deployment |

**Variant Selection:**
- Default tag `ruth-ai-runtime:X.Y.Z` is a multi-arch manifest pointing to CPU variant
- GPU and Jetson variants require explicit selection via docker-compose override

#### 3.3.2 Base Image Selection Rationale

| Container | Base Image | Rationale |
|-----------|------------|-----------|
| Backend | `python:3.11-slim-bookworm` | Minimal Python image, Debian stable, ARM64 support |
| Portal | `node:20-alpine` | Smallest Node.js image, excellent ARM64 support |
| Runtime (CPU) | `python:3.11-slim-bookworm` | Consistent with Backend, CPU-only dependencies |
| Runtime (GPU) | `nvidia/cuda:12.1-runtime-ubuntu22.04` | Official NVIDIA CUDA runtime, well-tested |
| Runtime (Jetson) | `nvcr.io/nvidia/l4t-pytorch:r35.2.1-pth2.0-py3` | Official Jetson PyTorch image with GPU support |

### 3.4 Image Tagging Strategy

**Tag Format:** `<registry>/<image>:<version>-<variant>-<arch>`

**Versioning:**
- Semantic versioning (X.Y.Z)
- `latest` tag points to latest stable release
- `main` tag points to latest CI build from main branch

**Examples:**
```
ghcr.io/ruth-ai/ruth-ai-backend:1.0.0
ghcr.io/ruth-ai/ruth-ai-backend:1.0.0-arm64
ghcr.io/ruth-ai/ruth-ai-runtime:1.0.0-cpu
ghcr.io/ruth-ai/ruth-ai-runtime:1.0.0-gpu
ghcr.io/ruth-ai/ruth-ai-runtime:1.0.0-jetson
ghcr.io/ruth-ai/ruth-ai-portal:1.0.0
```

### 3.5 Container Build Requirements

#### 3.5.1 ruth-ai-backend

**Build Requirements:**
- Python 3.11+
- No native compilation dependencies
- mediasoup-client (if Python WebRTC) or aiortc
- gRPC client libraries

**Security:**
- Non-root user execution
- No shell in production image (optional hardening)
- Read-only filesystem support

#### 3.5.2 ruth-ai-runtime

**Build Requirements (CPU):**
- Python 3.11+
- PyTorch CPU wheels
- ONNX Runtime (CPU)
- OpenCV (headless)

**Build Requirements (GPU):**
- CUDA 12.1+ runtime
- cuDNN 8+
- PyTorch CUDA wheels
- TensorRT (optional optimization)

**Build Requirements (Jetson):**
- JetPack 5.0+ base
- PyTorch Jetson wheels
- ONNX Runtime with CUDA EP

**Security:**
- Non-root user execution
- GPU device access only (no host filesystem)
- Read-only filesystem support

#### 3.5.3 ruth-ai-portal

**Build Requirements:**
- Node.js 20 LTS
- Static asset build (React/Next.js)
- nginx for production serving (alternative: serve via Node)

**Security:**
- Non-root user execution
- Static files only in production
- No Node runtime needed if using nginx

---

## 4. Docker Compose Reference Architecture

### 4.1 Service Topology

```
                                    ┌─────────────────────────────────────────────┐
                                    │            EXTERNAL: VAS-MS-V2              │
                                    │  (http://10.30.250.245:8085)                │
                                    └─────────────────────────────────────────────┘
                                                        │
                                                        │ REST API + WebRTC
                                                        │
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              RUTH AI DEPLOYMENT                                         │
│                                                                                         │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐                    │
│  │  ruth-ai-portal │     │ ruth-ai-backend │     │ ruth-ai-runtime │                    │
│  │                 │     │                 │     │                 │                    │
│  │  Port: 3000     │────>│  Port: 8080     │────>│  Port: 50051    │                    │
│  │  (HTTP)         │     │  (REST API)     │     │  (gRPC)         │                    │
│  │                 │     │                 │     │                 │                    │
│  └─────────────────┘     └────────┬────────┘     └─────────────────┘                    │
│                                   │                       │                              │
│                                   │                       │                              │
│                          ┌────────┴────────┐              │                              │
│                          │                 │              │                              │
│                   ┌──────┴──────┐   ┌──────┴──────┐       │                              │
│                   │  PostgreSQL │   │    Redis    │       │                              │
│                   │             │   │             │       │                              │
│                   │  Port: 5432 │   │  Port: 6379 │       │                              │
│                   └─────────────┘   └─────────────┘       │                              │
│                                                           │                              │
│  GPU Mode Only:                                          │                              │
│  ┌───────────────────────────────────────────────────────┤                              │
│  │  NVIDIA Container Runtime                             │                              │
│  │  GPU Device: /dev/nvidia0                             │                              │
│  └───────────────────────────────────────────────────────┘                              │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Network Architecture

**Network Segments:**

| Network | Purpose | Services |
|---------|---------|----------|
| `ruth-ai-frontend` | External access to Portal | ruth-ai-portal |
| `ruth-ai-internal` | Internal service communication | All services |

**Port Exposure:**

| Service | Internal Port | Exposed Port | Exposure Level |
|---------|---------------|--------------|----------------|
| ruth-ai-portal | 3000 | 3000 | External (operator access) |
| ruth-ai-backend | 8080 | 8080 | External (API access) |
| ruth-ai-runtime | 50051 | - | Internal only |
| PostgreSQL | 5432 | - | Internal only |
| Redis | 6379 | - | Internal only |

**VAS Integration (External):**

| VAS Service | Port | Ruth AI Access |
|-------------|------|----------------|
| VAS Backend API | 8085 | Backend connects via REST |
| VAS Frontend | 3200 | Portal may link/redirect |
| VAS MediaSoup | 3002 | Portal connects for video |
| VAS PostgreSQL | 5433 | No direct access (VAS internal) |
| VAS Redis | 6380 | No direct access (VAS internal) |

### 4.3 Volume Strategy

**Persistent Volumes:**

| Volume | Mount Point | Purpose | Backup Required |
|--------|-------------|---------|-----------------|
| `ruth-postgres-data` | `/var/lib/postgresql/data` | Database storage | Yes |
| `ruth-redis-data` | `/data` | Redis persistence | No (cache) |
| `ruth-model-weights` | `/app/weights` | AI model weights | Yes (or re-download) |
| `ruth-logs` | `/var/log/ruth-ai` | Application logs | Optional |

**Volume Ownership:**
- All volumes owned by container's non-root user
- UID/GID configurable via environment variables

### 4.4 Compose File Structure

```
ruth-ai/
├── docker-compose.yml              # Base composition (common services)
├── docker-compose.override.yml     # Local development overrides (default)
├── docker-compose.test.yml         # Test environment overrides
├── docker-compose.prod.yml         # Production base
├── docker-compose.gpu.yml          # GPU runtime override
├── docker-compose.jetson.yml       # Jetson runtime override
├── .env.example                    # Environment template
└── .env                            # Local environment (not committed)
```

**Composition Commands:**

```bash
# Development (default)
docker-compose up

# Test
docker-compose -f docker-compose.yml -f docker-compose.test.yml up

# Production CPU
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up

# Production GPU
docker-compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.gpu.yml up

# Edge Jetson
docker-compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.jetson.yml up
```

### 4.5 Health Check Configuration

**Backend Health Check:**
```
Endpoint: GET /api/v1/health
Interval: 30s
Timeout: 10s
Start Period: 30s
Retries: 3
```

**Runtime Health Check:**
```
Endpoint: gRPC HealthCheck or GET /health (REST fallback)
Interval: 15s
Timeout: 10s
Start Period: 60s (model loading time)
Retries: 3
```

**Database Health Check:**
```
Command: pg_isready -U ${POSTGRES_USER}
Interval: 30s
Timeout: 5s
Retries: 5
```

**Redis Health Check:**
```
Command: redis-cli ping
Interval: 30s
Timeout: 5s
Retries: 5
```

### 4.6 Dependency Management

**Service Startup Order:**

```
1. PostgreSQL (database)
   └── 2. Redis (cache)
       └── 3. ruth-ai-runtime (AI inference)
           └── 4. ruth-ai-backend (API + stream management)
               └── 5. ruth-ai-portal (UI)
```

**Dependency Configuration:**
- `depends_on` with `condition: service_healthy`
- Backend waits for PostgreSQL, Redis, and Runtime health
- Portal waits for Backend health

---

## 5. Optional Kubernetes Architecture

### 5.1 Design Philosophy

Kubernetes support is **additive** to Docker Compose, not a replacement. The following principles apply:

1. **No K8s-specific application code** - Applications remain unaware of orchestrator
2. **Same container images** - K8s uses identical images to Compose
3. **Configuration via environment variables** - Not ConfigMaps in application logic
4. **GPU scheduling via labels** - Not custom GPU detection code

### 5.2 When to Use Kubernetes

| Scenario | Docker Compose | Kubernetes |
|----------|----------------|------------|
| Single-node deployment | Recommended | Overkill |
| Development/testing | Recommended | Not recommended |
| Small production (1-3 cameras) | Recommended | Optional |
| Multi-node production | Possible | Recommended |
| Auto-scaling required | Not supported | Recommended |
| Multi-tenant deployment | Limited | Recommended |
| Enterprise compliance | Possible | Often required |

### 5.3 Kubernetes Resource Mapping

| Docker Compose Concept | Kubernetes Resource |
|------------------------|---------------------|
| Service | Deployment + Service |
| Volume | PersistentVolumeClaim |
| Network | NetworkPolicy (optional) |
| Environment variables | ConfigMap + Secret |
| GPU access | Node selector + Device plugin |

### 5.4 GPU Scheduling in Kubernetes

**Node Labeling:**
```yaml
# GPU nodes labeled for scheduling
metadata:
  labels:
    accelerator: nvidia-gpu
    nvidia.com/gpu.product: Tesla-T4
```

**Pod GPU Request:**
```yaml
resources:
  limits:
    nvidia.com/gpu: 1
nodeSelector:
  accelerator: nvidia-gpu
```

**Rationale:** GPU allocation is a scheduling decision, not application logic. The AI Runtime container is identical; Kubernetes schedules it to GPU nodes.

### 5.5 Helm Chart Structure (Optional)

```
ruth-ai-helm/
├── Chart.yaml
├── values.yaml
├── values-cpu.yaml
├── values-gpu.yaml
├── values-jetson.yaml
├── templates/
│   ├── backend-deployment.yaml
│   ├── backend-service.yaml
│   ├── runtime-deployment.yaml
│   ├── runtime-service.yaml
│   ├── portal-deployment.yaml
│   ├── portal-service.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   └── ingress.yaml
└── README.md
```

**Values Precedence:**
1. Base `values.yaml` (common configuration)
2. Profile-specific values (values-gpu.yaml)
3. Installation-specific overrides

---

## 6. Hardware Adaptation Model

### 6.1 Capability Declaration Contract

The AI Runtime declares its capabilities to the Backend at startup. This is the **sole mechanism** for hardware adaptation.

**Capability Declaration Endpoint:**

```
POST /api/internal/runtime/register

{
  "runtime_id": "ai-runtime-001",
  "hardware_type": "gpu",          // cpu | gpu | jetson
  "supports_gpu": true,
  "gpu_name": "NVIDIA Tesla T4",   // null for CPU
  "gpu_memory_mb": 16384,          // null for CPU
  "cuda_version": "12.1",          // null for CPU
  "supported_models": [
    {
      "model_id": "fall_detection",
      "version": "1.0.0",
      "loaded": true
    }
  ],
  "max_fps": 100,
  "max_concurrent_streams": 10,
  "inference_batch_size": 4,
  "memory_available_mb": 4096,
  "version": "1.0.0"
}
```

### 6.2 Backend Adaptation Rules

The Backend adapts scheduling based on declared capabilities:

| Declared `hardware_type` | FPS Strategy | Batch Size | Inference Timeout |
|--------------------------|--------------|------------|-------------------|
| `cpu` | Cap at 30 FPS total, 5 FPS per camera | 1 (no batching) | 2000ms |
| `gpu` | Use declared `max_fps` | Use declared `inference_batch_size` | 100ms |
| `jetson` | Cap at 50 FPS total | 2 | 200ms |

**Adaptation Flow:**

```
┌──────────────────┐       ┌──────────────────┐
│   AI Runtime     │       │   Backend        │
│   (Startup)      │       │                  │
└────────┬─────────┘       └────────┬─────────┘
         │                          │
         │ 1. Load model            │
         │ 2. Detect hardware       │
         │ 3. POST /register        │
         │─────────────────────────>│
         │                          │
         │ 4. Acknowledged          │ 5. Store capabilities
         │<─────────────────────────│ 6. Adjust Frame Scheduler
         │                          │
         │ [Inference requests      │
         │  follow adapted config]  │
         │<═════════════════════════│
         │                          │
```

### 6.3 Hardware Detection (AI Runtime Only)

The AI Runtime performs hardware detection at startup:

**GPU Detection (amd64):**
```python
def detect_hardware():
    try:
        import torch
        if torch.cuda.is_available():
            return {
                "hardware_type": "gpu",
                "supports_gpu": True,
                "gpu_name": torch.cuda.get_device_name(0),
                "gpu_memory_mb": torch.cuda.get_device_properties(0).total_memory // (1024*1024),
                "cuda_version": torch.version.cuda
            }
    except ImportError:
        pass
    return {"hardware_type": "cpu", "supports_gpu": False}
```

**Jetson Detection:**
```python
def detect_jetson():
    # Jetson devices have specific device files
    if os.path.exists("/etc/nv_tegra_release"):
        return True
    # Alternative: check for Tegra in /proc/device-tree/model
    try:
        with open("/proc/device-tree/model", "r") as f:
            if "Jetson" in f.read():
                return True
    except FileNotFoundError:
        pass
    return False
```

### 6.4 Zero Code Change Guarantee

**Backend Code Constraints:**
- Backend NEVER imports torch, CUDA, or GPU libraries
- Backend NEVER checks for GPU availability
- Backend only knows what Runtime declares via capabilities API

**Runtime Code Constraints:**
- Hardware detection is runtime initialization, not inference path
- Same inference code path for CPU/GPU/Jetson (PyTorch handles device)
- Model loading adapts to available device

**Verification:**
- Backend container does not include CUDA libraries
- Backend container works without GPU drivers installed
- Switching Runtime variant (CPU to GPU) requires no Backend changes

---

## 7. Secrets & Configuration Strategy

### 7.1 Configuration Hierarchy

```
Priority (highest to lowest):
1. Runtime environment variables (docker run -e)
2. Environment file (.env loaded by compose)
3. Container default values (set in image)
4. Application defaults (hardcoded fallbacks)
```

### 7.2 Environment Variable Catalog

#### 7.2.1 Ruth AI Backend

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RUTH_AI_ENV` | No | `development` | Environment: development, test, production |
| `RUTH_AI_LOG_LEVEL` | No | `info` | Log level: debug, info, warn, error |
| `RUTH_AI_LOG_FORMAT` | No | `json` | Log format: json, text |
| `DATABASE_URL` | Yes | - | PostgreSQL connection string |
| `REDIS_URL` | Yes | - | Redis connection string |
| `AI_RUNTIME_URL` | Yes | - | AI Runtime gRPC endpoint |
| `VAS_BASE_URL` | Yes | - | VAS Backend API URL |
| `VAS_CLIENT_ID` | Yes | - | VAS API client ID |
| `VAS_CLIENT_SECRET` | Yes | - | VAS API client secret |
| `JWT_SECRET_KEY` | Yes | - | Ruth AI JWT signing key |
| `JWT_ALGORITHM` | No | `HS256` | JWT algorithm |
| `JWT_EXPIRY_MINUTES` | No | `60` | Access token expiry |

#### 7.2.2 Ruth AI Runtime

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AI_RUNTIME_PORT` | No | `50051` | gRPC server port |
| `AI_RUNTIME_HARDWARE` | No | `auto` | Force hardware: auto, cpu, gpu, jetson |
| `AI_RUNTIME_MAX_FPS` | No | `100` | Maximum frames per second |
| `AI_RUNTIME_MAX_CONCURRENT_STREAMS` | No | `10` | Maximum camera streams |
| `AI_RUNTIME_INFERENCE_TIMEOUT_MS` | No | `100` | Inference timeout |
| `AI_RUNTIME_BATCH_SIZE` | No | `1` | Inference batch size |
| `MODEL_WEIGHTS_PATH` | No | `/app/weights` | Path to model weights |
| `MODEL_ID` | No | `fall_detection` | Model identifier |
| `CONFIDENCE_THRESHOLD` | No | `0.7` | Detection confidence threshold |

#### 7.2.3 Ruth AI Portal

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RUTH_AI_API_URL` | Yes | - | Ruth AI Backend URL |
| `VAS_WEBRTC_URL` | Yes | - | VAS WebRTC endpoint for video |
| `NEXT_PUBLIC_ENV` | No | `production` | Next.js environment |

### 7.3 Secrets Management

**Secret Categories:**

| Category | Examples | Handling |
|----------|----------|----------|
| Database credentials | `POSTGRES_PASSWORD`, `DATABASE_URL` | Docker/K8s secrets |
| API credentials | `VAS_CLIENT_SECRET`, `JWT_SECRET_KEY` | Docker/K8s secrets |
| TLS certificates | `TLS_CERT`, `TLS_KEY` | Mounted volumes or secrets |

**Docker Secrets (Compose):**
```yaml
secrets:
  db_password:
    file: ./secrets/db_password.txt
  vas_client_secret:
    file: ./secrets/vas_client_secret.txt

services:
  ruth-ai-backend:
    secrets:
      - db_password
      - vas_client_secret
    environment:
      DATABASE_PASSWORD_FILE: /run/secrets/db_password
```

**Kubernetes Secrets:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: ruth-ai-secrets
type: Opaque
stringData:
  database-url: postgresql://ruth:password@postgres:5432/ruth
  vas-client-secret: vas-secret-value
  jwt-secret-key: jwt-secret-value
```

### 7.4 Configuration Isolation

**VAS Credentials:**
- Stored separately from Ruth AI application secrets
- Never exposed to Portal or external API consumers
- Rotated via environment variable update, no code change

**Model Configuration:**
- Model weights path injected via environment
- Confidence threshold configurable without rebuild
- Model version tracked in capability declaration

### 7.5 Environment File Template

```bash
# .env.example - Copy to .env and fill in values

# Environment
RUTH_AI_ENV=development
RUTH_AI_LOG_LEVEL=info

# Database
POSTGRES_USER=ruth
POSTGRES_PASSWORD=changeme
POSTGRES_DB=ruth_ai
DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}

# Redis
REDIS_URL=redis://redis:6379

# AI Runtime
AI_RUNTIME_URL=ruth-ai-runtime:50051
AI_RUNTIME_HARDWARE=auto
AI_RUNTIME_MAX_FPS=100

# VAS Integration
VAS_BASE_URL=http://10.30.250.245:8085
VAS_CLIENT_ID=ruth-ai-production
VAS_CLIENT_SECRET=changeme

# Authentication
JWT_SECRET_KEY=changeme-generate-secure-key
JWT_EXPIRY_MINUTES=60

# Portal
RUTH_AI_API_URL=http://ruth-ai-backend:8080
VAS_WEBRTC_URL=ws://10.30.250.245:3002
```

---

## 8. Observability & Operations

### 8.1 Logging Strategy

**Log Format:** JSON (structured)

**Log Output:** stdout only (no file logging in containers)

**Log Fields:**

```json
{
  "timestamp": "2026-01-13T10:30:00.123Z",
  "level": "info",
  "service": "ruth-ai-backend",
  "trace_id": "abc123",
  "span_id": "def456",
  "message": "Violation created",
  "violation_id": "550e8400-e29b-41d4-a716-446655440000",
  "camera_id": "660e8400-e29b-41d4-a716-446655440001",
  "confidence": 0.92
}
```

**Log Levels:**

| Level | Usage |
|-------|-------|
| `error` | Unrecoverable errors, service failures |
| `warn` | Recoverable errors, degraded performance |
| `info` | Normal operations, key events |
| `debug` | Detailed debugging (development only) |

**Log Collection:**
- Docker logging driver (json-file, fluentd, etc.)
- Kubernetes: stdout collected by cluster logging
- External aggregation: Loki, Elasticsearch, CloudWatch

### 8.2 Metrics Strategy

**Metrics Format:** Prometheus exposition format

**Metrics Endpoints:**

| Service | Endpoint | Port |
|---------|----------|------|
| Backend | `/metrics` | 8080 |
| Runtime | `/metrics` | 8000 (HTTP sidecar) |
| Portal | N/A | (No metrics) |

**Backend Metrics:**

```
# Streams
ruth_ai_streams_active{camera_id}
ruth_ai_stream_state{camera_id, state}

# Frames
ruth_ai_frames_dispatched_total{camera_id}
ruth_ai_frames_dropped_total{camera_id, reason}
ruth_ai_frame_queue_depth{camera_id}

# Violations
ruth_ai_violations_created_total{camera_id, type}
ruth_ai_violations_by_status{status}

# Events
ruth_ai_events_created_total{camera_id, event_type}

# VAS Integration
ruth_ai_vas_api_requests_total{endpoint, status}
ruth_ai_vas_api_latency_seconds{endpoint}

# Health
ruth_ai_component_health{component}
```

**Runtime Metrics:**

```
# Inference
ruth_ai_inference_requests_total{model_id}
ruth_ai_inference_latency_seconds{model_id}
ruth_ai_inference_throughput_fps{model_id}
ruth_ai_inference_errors_total{model_id, error_type}

# Queue
ruth_ai_inference_queue_depth
ruth_ai_inference_queue_wait_seconds

# Hardware
ruth_ai_gpu_utilization_percent
ruth_ai_gpu_memory_used_bytes
ruth_ai_gpu_temperature_celsius

# Model
ruth_ai_model_loaded{model_id, version}
ruth_ai_model_health{model_id}
```

### 8.3 Health Check Endpoints

**Backend Health:**

```
GET /api/v1/health

Response:
{
  "status": "healthy",
  "service": "ruth-ai-backend",
  "version": "1.0.0",
  "timestamp": "2026-01-13T10:30:00.000Z",
  "components": {
    "database": "healthy",
    "redis": "healthy",
    "ai_runtime": "healthy",
    "vas": "healthy"
  }
}
```

**Runtime Health:**

```
gRPC: HealthCheck RPC
HTTP Fallback: GET /health

Response:
{
  "status": "healthy",
  "model_id": "fall_detection",
  "model_version": "1.0.0",
  "hardware_type": "gpu",
  "uptime_seconds": 3600,
  "frames_processed": 360000,
  "avg_inference_time_ms": 85
}
```

**Liveness vs Readiness:**

| Check | Liveness | Readiness |
|-------|----------|-----------|
| Purpose | Is the process alive? | Can it serve requests? |
| Backend | HTTP 200 from /health | Database + Redis + Runtime healthy |
| Runtime | HTTP 200 from /health | Model loaded and GPU available |

### 8.4 Restart and Recovery

**Restart Policies:**

| Environment | Policy | Rationale |
|-------------|--------|-----------|
| Development | `no` | Manual restart for debugging |
| Test | `no` | Fail fast for CI |
| Production | `unless-stopped` | Auto-recovery from crashes |

**Crash Recovery:**

| Failure Mode | Detection | Recovery |
|--------------|-----------|----------|
| Backend crash | Health check failure | Container restart, reconnect to DB/Redis |
| Runtime crash | gRPC unavailable | Container restart, Backend queues frames |
| Database crash | Connection error | Database container restart, Backend retries |
| GPU failure | CUDA error | Runtime restart, fallback to CPU if persistent |

**Recovery Timeouts:**

| Component | Health Check Interval | Failure Threshold | Restart Delay |
|-----------|----------------------|-------------------|---------------|
| Backend | 30s | 3 failures | Immediate |
| Runtime | 15s | 3 failures | Immediate |
| Database | 30s | 5 failures | 10s delay |
| Redis | 30s | 5 failures | 5s delay |

### 8.5 GPU Health Visibility

**GPU Monitoring (Runtime):**

```python
def get_gpu_health():
    import torch
    if torch.cuda.is_available():
        return {
            "gpu_available": True,
            "gpu_name": torch.cuda.get_device_name(0),
            "gpu_memory_total_mb": torch.cuda.get_device_properties(0).total_memory // (1024*1024),
            "gpu_memory_used_mb": torch.cuda.memory_allocated(0) // (1024*1024),
            "gpu_utilization_percent": get_nvidia_smi_utilization()  # via pynvml
        }
    return {"gpu_available": False}
```

**GPU Metrics Exposed:**
- `ruth_ai_gpu_utilization_percent`
- `ruth_ai_gpu_memory_used_bytes`
- `ruth_ai_gpu_memory_total_bytes`
- `ruth_ai_gpu_temperature_celsius`

**Jetson-Specific:**
- Tegra power consumption via `/sys/bus/i2c/drivers/ina3221x/`
- Thermal zones via `/sys/class/thermal/`

---

## 9. CI/CD Pipeline Design

### 9.1 Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              CI/CD PIPELINE STAGES                                       │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐              │
│  │  Lint   │───>│  Test   │───>│  Build  │───>│ Contract│───>│ Publish │              │
│  │         │    │         │    │         │    │  Check  │    │         │              │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘    └─────────┘              │
│       │              │              │              │              │                     │
│       │              │              │              │              │                     │
│       ▼              ▼              ▼              ▼              ▼                     │
│  [All code]    [Unit &       [Multi-arch   [API contract [Push to        ]             │
│  [linted  ]    Integration]   images   ]    validation]   registry  ]                  │
│                                                                                         │
│                                                                                         │
│  Deployment Promotion:                                                                  │
│                                                                                         │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐                                             │
│  │   Dev   │───>│  Test   │───>│  Prod   │                                             │
│  │ (auto)  │    │ (auto)  │    │ (manual)│                                             │
│  └─────────┘    └─────────┘    └─────────┘                                             │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 9.2 Stage Definitions

#### 9.2.1 Lint Stage

**Triggers:** All commits, all branches

**Actions:**
- Python: `ruff`, `black --check`, `mypy`
- TypeScript: `eslint`, `prettier --check`
- YAML: `yamllint`
- Dockerfile: `hadolint`

**Failure:** Blocks all subsequent stages

#### 9.2.2 Test Stage

**Triggers:** All commits, all branches

**Actions:**
- Unit tests (pytest, jest)
- Integration tests (Docker Compose test profile)
- Coverage reporting

**Requirements:**
- Minimum 80% code coverage
- All tests pass

**Failure:** Blocks build stage

#### 9.2.3 Build Stage

**Triggers:** Commits to `main`, tags

**Actions:**
- Build multi-arch images using Docker Buildx
- Build variants: cpu, gpu, jetson (for Runtime)
- Tag with commit SHA and version

**Outputs:**
- `ruth-ai-backend:<sha>-amd64`
- `ruth-ai-backend:<sha>-arm64`
- `ruth-ai-runtime:<sha>-cpu-amd64`
- `ruth-ai-runtime:<sha>-cpu-arm64`
- `ruth-ai-runtime:<sha>-gpu-amd64`
- `ruth-ai-runtime:<sha>-jetson-arm64`
- `ruth-ai-portal:<sha>-amd64`
- `ruth-ai-portal:<sha>-arm64`

#### 9.2.4 Contract Check Stage

**Triggers:** After build, before publish

**Actions:**
- Validate Backend API against OpenAPI spec
- Validate Runtime gRPC against protobuf definitions
- Run contract tests against VAS mock

**Failure:** Blocks publish stage

**Rationale:** No deployment proceeds if contracts are broken

#### 9.2.5 Publish Stage

**Triggers:** After contract check passes

**Actions:**
- Push images to container registry
- Create multi-arch manifests
- Tag as `latest` (for main branch) or version tag

**Outputs:**
- Published to `ghcr.io/ruth-ai/`
- Manifest tags for automatic architecture selection

### 9.3 Deployment Promotion

| Environment | Trigger | Approval | Rollback |
|-------------|---------|----------|----------|
| Dev | Auto on main merge | None | Auto on failure |
| Test | Auto after dev success | None | Auto on failure |
| Prod | Manual trigger | Required | Manual |

**Promotion Requirements:**

| Gate | Dev | Test | Prod |
|------|-----|------|------|
| Tests pass | Yes | Yes | Yes |
| Contracts valid | Yes | Yes | Yes |
| Coverage >= 80% | Yes | Yes | Yes |
| Security scan clean | No | Yes | Yes |
| Manual approval | No | No | Yes |

### 9.4 Rollback Strategy

**Automatic Rollback (Dev/Test):**
- Health check failure within 5 minutes of deploy
- Contract test failure post-deploy
- Error rate exceeds threshold

**Manual Rollback (Prod):**
- Triggered by operator
- Uses previous stable image tag
- Database migrations must be backward-compatible

**Rollback Command:**
```bash
# Docker Compose
docker-compose pull  # pulls previous version
docker-compose up -d

# Kubernetes
kubectl rollout undo deployment/ruth-ai-backend
kubectl rollout undo deployment/ruth-ai-runtime
```

### 9.5 Multi-Arch Build Strategy

**Build Matrix:**

| Image | amd64 | arm64 | Notes |
|-------|-------|-------|-------|
| ruth-ai-backend | Yes | Yes | Same image both archs |
| ruth-ai-portal | Yes | Yes | Same image both archs |
| ruth-ai-runtime-cpu | Yes | Yes | Same image both archs |
| ruth-ai-runtime-gpu | Yes | No | NVIDIA CUDA (x86 only) |
| ruth-ai-runtime-jetson | No | Yes | Jetson L4T (ARM only) |

**Buildx Commands (Conceptual):**
```bash
# Multi-arch backend
docker buildx build --platform linux/amd64,linux/arm64 \
  -t ghcr.io/ruth-ai/ruth-ai-backend:1.0.0 \
  --push .

# GPU runtime (amd64 only)
docker buildx build --platform linux/amd64 \
  -f Dockerfile.gpu \
  -t ghcr.io/ruth-ai/ruth-ai-runtime:1.0.0-gpu \
  --push .

# Jetson runtime (arm64 only)
docker buildx build --platform linux/arm64 \
  -f Dockerfile.jetson \
  -t ghcr.io/ruth-ai/ruth-ai-runtime:1.0.0-jetson \
  --push .
```

---

## 10. Risks, Assumptions & Open Questions

### 10.1 Assumptions

| ID | Assumption | Impact if False | Mitigation |
|----|------------|-----------------|------------|
| A1 | VAS-MS-V2 is available at documented ports (8085, 3200, 3002, 5433, 6380) | Ruth AI cannot function | VAS availability monitoring, graceful degradation |
| A2 | NVIDIA Container Toolkit is installed on GPU hosts | GPU containers fail to start | Pre-deployment validation scripts |
| A3 | JetPack 5.0+ is installed on Jetson devices | Jetson containers fail | Version check in deployment docs |
| A4 | Network allows gRPC (50051) between Backend and Runtime | AI inference unavailable | Configurable port, firewall documentation |
| A5 | Single AI Runtime can handle 10 cameras at 10 FPS | Need multiple Runtimes | Horizontal scaling design ready |
| A6 | PostgreSQL connection pooling sufficient for load | Database connection exhaustion | PgBouncer can be added if needed |
| A7 | Redis single instance is sufficient | Redis becomes bottleneck | Redis Cluster config available |
| A8 | Model weights fit in container image or volume mount | Deployment complexity | Support both embedded and mounted weights |

### 10.2 Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|------------|--------|------------|
| R1 | GPU driver mismatch between host and container | Medium | High | Document supported driver versions, test matrix |
| R2 | Jetson L4T version incompatibility | Medium | High | Pin L4T base image version, document requirements |
| R3 | Multi-arch build flakiness | Low | Medium | Retry logic in CI, fallback to per-arch builds |
| R4 | VAS API breaking changes | Medium | High | Contract tests gate deployment, VAS Guardian monitoring |
| R5 | Container image size too large for edge | Medium | Medium | Multi-stage builds, alpine bases where possible |
| R6 | gRPC connection instability | Low | Medium | Connection retry logic, health checks |
| R7 | Database migration failures | Low | High | Backward-compatible migrations, rollback tested |
| R8 | Secrets exposed in logs | Low | Critical | Log sanitization, secret masking |

### 10.3 Open Questions

| ID | Question | Blocking? | Owner | Resolution Path |
|----|----------|-----------|-------|-----------------|
| Q1 | Container registry: GitHub (ghcr.io) or self-hosted? | No | DevOps | Decision by deployment team |
| Q2 | TLS termination: at reverse proxy or per-service? | No | DevOps | Recommend reverse proxy for simplicity |
| Q3 | Database backup strategy for production? | Yes (prod) | DevOps | Require before production deployment |
| Q4 | Jetson JetPack version support matrix? | Yes (edge) | DevOps | Test on available hardware |
| Q5 | GPU memory requirements for production model? | Yes (GPU) | AI Team | Model profiling required |
| Q6 | Redis persistence required or cache-only? | No | DevOps | Recommend RDB snapshots for session recovery |
| Q7 | Log retention period and storage estimate? | No | DevOps | Depends on compliance requirements |
| Q8 | Network latency tolerance between Backend and VAS? | No | Platform | Document recommended < 50ms |

### 10.4 Conflict Detection

**Potential Conflict: Architecture specifies Node.js for Backend, existing code uses Python**

- Architecture Document (Section 9.1): "Node.js (or Python FastAPI) for Ruth AI Backend"
- Existing fall-detection-model: Python-based
- Resolution: Python FastAPI is explicitly allowed in architecture. No conflict.

**Potential Conflict: AI Runtime gRPC vs REST**

- API Contract Specification: gRPC for Backend to AI Runtime
- Existing fall-detection-model Dockerfile: Exposes port 8000 (HTTP/REST)
- Resolution: REST is acceptable fallback. Capability declaration works over REST. Implementation team decides transport.

**No blocking conflicts identified.**

### 10.5 Dependencies

| Dependency | Type | Owner | Status | Notes |
|------------|------|-------|--------|-------|
| NVIDIA Container Toolkit | External | NVIDIA | Available | Required for GPU profiles |
| Docker Buildx | External | Docker | Available | Required for multi-arch builds |
| JetPack SDK | External | NVIDIA | Available | Required for Jetson profile |
| VAS-MS-V2 | External | VAS Team | Running | Available at documented ports |
| Container Registry | Infrastructure | DevOps | Pending | GitHub, Docker Hub, or self-hosted |
| GPU Hardware (prod) | Infrastructure | DevOps | Pending | NVIDIA Tesla T4 or better recommended |
| Jetson Hardware (edge) | Infrastructure | DevOps | Pending | Jetson Orin or Xavier recommended |

---

## Appendix A: Environment Variable Reference

### Complete Variable List

```bash
# === Ruth AI Backend ===
RUTH_AI_ENV=production                    # Environment name
RUTH_AI_LOG_LEVEL=info                    # Logging level
RUTH_AI_LOG_FORMAT=json                   # Log output format

# Database
DATABASE_URL=postgresql://user:pass@host:5432/db
DATABASE_POOL_SIZE=10                     # Connection pool size
DATABASE_POOL_OVERFLOW=5                  # Max overflow connections

# Redis
REDIS_URL=redis://host:6379/0
REDIS_MAX_CONNECTIONS=50                  # Max Redis connections

# AI Runtime Connection
AI_RUNTIME_URL=ruth-ai-runtime:50051      # gRPC endpoint
AI_RUNTIME_TIMEOUT_MS=5000                # Request timeout
AI_RUNTIME_RETRY_COUNT=3                  # Retry attempts

# VAS Integration
VAS_BASE_URL=http://10.30.250.245:8085    # VAS Backend API
VAS_CLIENT_ID=ruth-ai-production          # VAS API client ID
VAS_CLIENT_SECRET=<secret>                # VAS API client secret
VAS_TOKEN_REFRESH_MARGIN_SEC=300          # Refresh token 5 min before expiry

# Authentication
JWT_SECRET_KEY=<secret>                   # JWT signing key
JWT_ALGORITHM=HS256                       # JWT algorithm
JWT_EXPIRY_MINUTES=60                     # Access token expiry

# === Ruth AI Runtime ===
AI_RUNTIME_PORT=50051                     # gRPC server port
AI_RUNTIME_HTTP_PORT=8000                 # HTTP health/metrics port
AI_RUNTIME_HARDWARE=auto                  # Hardware mode: auto, cpu, gpu, jetson
AI_RUNTIME_MAX_FPS=100                    # Maximum processing FPS
AI_RUNTIME_MAX_CONCURRENT_STREAMS=10      # Max camera streams
AI_RUNTIME_INFERENCE_TIMEOUT_MS=100       # Single inference timeout
AI_RUNTIME_BATCH_SIZE=4                   # Batch inference size

# Model Configuration
MODEL_WEIGHTS_PATH=/app/weights           # Model weights directory
MODEL_ID=fall_detection                   # Model identifier
MODEL_VERSION=1.0.0                       # Model version
CONFIDENCE_THRESHOLD=0.7                  # Detection threshold

# GPU Configuration (when AI_RUNTIME_HARDWARE=gpu)
NVIDIA_VISIBLE_DEVICES=all                # GPU visibility
CUDA_VISIBLE_DEVICES=0                    # Specific GPU index

# === Ruth AI Portal ===
RUTH_AI_API_URL=http://ruth-ai-backend:8080  # Backend API
VAS_WEBRTC_URL=ws://10.30.250.245:3002       # VAS WebRTC endpoint
NEXT_PUBLIC_ENV=production                    # Next.js environment

# === Database (PostgreSQL) ===
POSTGRES_USER=ruth                        # Database user
POSTGRES_PASSWORD=<secret>                # Database password
POSTGRES_DB=ruth_ai                       # Database name

# === Redis ===
# Redis uses default configuration, no required variables
```

---

## Appendix B: Health Check Response Schemas

### Backend Health Response

```json
{
  "status": "healthy | degraded | unhealthy",
  "service": "ruth-ai-backend",
  "version": "1.0.0",
  "timestamp": "2026-01-13T10:30:00.000Z",
  "components": {
    "database": {
      "status": "healthy | unhealthy",
      "latency_ms": 5,
      "error": null
    },
    "redis": {
      "status": "healthy | unhealthy",
      "latency_ms": 1,
      "error": null
    },
    "ai_runtime": {
      "status": "healthy | degraded | unhealthy",
      "latency_ms": 10,
      "error": null,
      "hardware_type": "gpu",
      "model_loaded": true
    },
    "vas": {
      "status": "healthy | unhealthy",
      "latency_ms": 20,
      "error": null
    }
  },
  "uptime_seconds": 86400
}
```

### Runtime Health Response

```json
{
  "status": "healthy | degraded | unhealthy",
  "service": "ruth-ai-runtime",
  "version": "1.0.0",
  "timestamp": "2026-01-13T10:30:00.000Z",
  "hardware": {
    "type": "gpu | cpu | jetson",
    "gpu_available": true,
    "gpu_name": "NVIDIA Tesla T4",
    "gpu_memory_total_mb": 16384,
    "gpu_memory_used_mb": 4096,
    "gpu_utilization_percent": 45,
    "cuda_version": "12.1"
  },
  "model": {
    "model_id": "fall_detection",
    "version": "1.0.0",
    "loaded": true,
    "inference_ready": true
  },
  "metrics": {
    "uptime_seconds": 86400,
    "frames_processed_total": 8640000,
    "errors_total": 12,
    "avg_inference_time_ms": 85,
    "current_queue_depth": 3,
    "throughput_fps": 95
  }
}
```

---

## Appendix C: Glossary

| Term | Definition |
|------|------------|
| **Profile** | A named deployment configuration (dev, test, prod-cpu, prod-gpu, edge-jetson) |
| **Capability Declaration** | AI Runtime self-reporting its hardware and performance characteristics to Backend |
| **Multi-arch Manifest** | Docker manifest listing images for multiple architectures under single tag |
| **L4T** | Linux for Tegra - NVIDIA's Linux distribution for Jetson devices |
| **Device Plugin** | Kubernetes component that exposes GPU resources to scheduler |
| **Backpressure** | Flow control mechanism when downstream service cannot keep up |
| **Contract Test** | Automated test validating API/service interface against specification |

---

**End of Infrastructure & Deployment Design Document**

*This specification was produced by the Platform & Infrastructure Authority Agent.*

*Document Version: 1.0*
*Last Updated: January 2026*
