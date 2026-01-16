# Ruth AI – System Architecture Design

**Version:** 1.0
**Architect:** Principal Software Architect Agent
**Date:** January 2026

---

## Executive Summary

Ruth AI is an AI-powered video intelligence platform that consumes live video streams from VAS-MS-V2 and applies computer vision models (initially fall detection) to detect safety incidents in real-time. The architecture is designed around three core principles:

1. **VAS as the single video gateway** – Ruth AI never touches RTSP, MediaSoup, or raw video transport directly. All video access flows through documented VAS APIs.

2. **Shared AI runtime model** – A single AI model container processes frames from multiple camera streams through a scheduling layer, avoiding the need to instantiate one model per camera.

3. **Clear domain boundaries** – Frontend, Backend, and AI Runtime are distinct services with explicit contracts, enabling independent development and deployment.

The v1 architecture prioritizes simplicity and operability while establishing extension points for future capabilities (multi-model orchestration, alerting systems, advanced analytics).

---

## System Context

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL SYSTEMS                                   │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────┐         ┌──────────────────────────────────────────────────┐   │
│  │  IP Cameras │──RTSP──>│                 VAS-MS-V2                        │   │
│  │  (External) │         │  ┌──────────┐  ┌──────────┐  ┌──────────┐        │   │
│  └─────────────┘         │  │  FFmpeg  │  │ MediaSoup│  │ Backend  │        │   │
│                          │  │  (RTSP)  │──│  (SFU)   │──│  (API)   │        │   │
│                          │  └──────────┘  └──────────┘  └──────────┘        │   │
│                          │        │                          │              │   │
│                          │        │    WebRTC                │ REST API     │   │
│                          │        ▼                          ▼              │   │
│                          └──────────────────────────────────────────────────┘   │
│                                        │                     │                  │
│                                        │                     │                  │
└────────────────────────────────────────│─────────────────────│──────────────────┘
                                         │                     │
                    ┌────────────────────┼─────────────────────┼────────────────────┐
                    │                    │    RUTH AI DOMAIN   │                    │
                    │                    ▼                     ▼                    │
                    │  ┌─────────────────────────────────────────────────────────┐  │
                    │  │                  RUTH AI BACKEND                        │  │
                    │  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │  │
                    │  │  │   Stream    │  │   Event     │  │  Evidence   │      │  │
                    │  │  │  Manager    │──│   Engine    │──│   Linker    │      │  │
                    │  │  │  (WebRTC)   │  │             │  │             │      │  │
                    │  │  └──────┬──────┘  └──────┬──────┘  └─────────────┘      │  │
                    │  │         │                │                              │  │
                    │  │         │ Frames         │ Events                       │  │
                    │  │         ▼                ▼                              │  │
                    │  │  ┌──────────────────────────────────────┐               │  │
                    │  │  │         Frame Scheduler              │               │  │
                    │  │  │  (Multi-camera to single runtime)    │               │  │
                    │  │  └─────────────────┬────────────────────┘               │  │
                    │  └────────────────────│────────────────────────────────────┘  │
                    │                       │ Frames                                │
                    │                       ▼                                       │
                    │  ┌─────────────────────────────────────────────────────────┐  │
                    │  │                  AI RUNTIME                             │  │
                    │  │  ┌─────────────┐  ┌─────────────┐                       │  │
                    │  │  │  Fall       │  │  Future     │                       │  │
                    │  │  │  Detection  │  │  Models...  │                       │  │
                    │  │  │  Model      │  │             │                       │  │
                    │  │  └─────────────┘  └─────────────┘                       │  │
                    │  └─────────────────────────────────────────────────────────┘  │
                    │                                                               │
                    │  ┌─────────────────────────────────────────────────────────┐  │
                    │  │                  OPERATOR PORTAL (Frontend)             │  │
                    │  │  ┌──────────┐  ┌──────────┐  ┌──────────┐               │  │
                    │  │  │  Device  │  │  Live    │  │ Violation│               │  │
                    │  │  │  List    │  │  Video   │  │  Review  │               │  │
                    │  │  └──────────┘  └──────────┘  └──────────┘               │  │
                    │  └─────────────────────────────────────────────────────────┘  │
                    │                                                               │
                    └───────────────────────────────────────────────────────────────┘
                                                │
                                                │
                    ┌───────────────────────────┴───────────────────────────────────┐
                    │                       DATA STORES                             │
                    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
                    │  │ PostgreSQL  │  │   Redis     │  │ File Store  │            │
                    │  │ (Violations,│  │ (Sessions,  │  │ (Local      │            │
                    │  │  Events)    │  │  Streams)   │  │  Snapshots) │            │
                    │  └─────────────┘  └─────────────┘  └─────────────┘            │
                    └───────────────────────────────────────────────────────────────┘
```

**Key Boundaries:**
- **VAS-MS-V2 owns**: RTSP connections, MediaSoup, WebRTC transport, HLS recording, snapshots, bookmarks
- **Ruth AI owns**: Frame extraction, AI inference, event detection, violation management, operator UI
- **Shared contract**: VAS REST APIs and WebRTC media streams

---

## Service Architecture

### Service Inventory

| Service | Responsibility | Owner | Runtime |
|---------|----------------|-------|---------|
| **Ruth AI Backend** | Stream management, event processing, violation lifecycle, API exposure | Backend Team | Node.js / Python |
| **AI Runtime** | Model execution, frame inference, detection output | AI Team | Python (PyTorch/ONNX) |
| **Operator Portal** | Device listing, live video, violation review | Frontend Team | React/Next.js |
| **PostgreSQL** | Persistent storage for violations, events, analytics | DevOps | Container |
| **Redis** | Session state, active stream tracking, cache | DevOps | Container |

---

### Service Decomposition

#### 1. Ruth AI Backend

**Responsibility:** Orchestrate video consumption, coordinate AI inference, manage violation lifecycle, expose Ruth AI APIs.

**Inputs:**
- Device/stream information from VAS APIs
- AI detection outputs from AI Runtime
- Operator actions from Frontend

**Outputs:**
- Frame dispatch to AI Runtime
- Violation records to database
- Evidence creation requests to VAS
- API responses to Frontend

**Failure Domain:** If Backend fails:
- No new violations are created
- Existing violations remain in database
- Live video continues in VAS (not dependent on Ruth AI)
- Frontend shows stale data until recovery

**Scaling Characteristics:**
- Stateless request handling (except WebRTC consumers)
- WebRTC consumer state held in memory per instance
- Horizontal scaling: multiple instances behind load balancer
- Sticky sessions for WebRTC connections

**Internal Components:**

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          RUTH AI BACKEND                                 │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌────────────────────┐    ┌────────────────────┐    ┌────────────────┐  │
│  │   VAS Gateway      │    │  Frame Scheduler   │    │  AI Gateway    │  │
│  │                    │    │                    │    │                │  │
│  │  - Auth management │    │  - Round-robin     │    │  - gRPC/REST   │  │
│  │  - Stream tracking │───>│    dispatch        │───>│    to AI       │  │
│  │  - Consumer mgmt   │    │  - FPS throttling  │    │  - Backpressure│  │
│  │  - Health polling  │    │  - Priority queues │    │  - Timeout     │  │
│  └────────────────────┘    └────────────────────┘    └────────────────┘  │
│           │                                                    │         │
│           │                                                    │         │
│           ▼                                                    ▼         │
│  ┌────────────────────┐                          ┌────────────────────┐  │
│  │   Stream Session   │                          │   Event Engine     │  │
│  │      Manager       │                          │                    │  │
│  │                    │                          │  - Deduplication   │  │
│  │  - Device ↔ Stream │                          │  - Confidence      │  │
│  │  - Lifecycle       │                          │    thresholding    │  │
│  │  - Reconnection    │                          │  - Event creation  │  │
│  └────────────────────┘                          └─────────┬──────────┘  │
│                                                            │             │
│                                                            ▼             │
│                                                  ┌────────────────────┐  │
│                                                  │ Violation Manager  │  │
│                                                  │                    │  │
│                                                  │  - Create/update   │  │
│                                                  │  - Status workflow │  │
│                                                  │  - Evidence linking│  │
│                                                  └─────────┬──────────┘  │
│                                                            │             │
│                                                            ▼             │
│                                                  ┌────────────────────┐  │
│                                                  │  Evidence Creator  │  │
│                                                  │                    │  │
│                                                  │  - Snapshot via VAS│  │
│                                                  │  - Bookmark via VAS│  │
│                                                  │  - Async polling   │  │
│                                                  └────────────────────┘  │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                         API Layer                                  │  │
│  │  /api/violations  /api/events  /api/analytics  /api/models/status  │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

#### 2. AI Runtime

**Responsibility:** Execute AI models on video frames, return detection results.

**Inputs:**
- Normalized video frames (JPEG/raw pixels) from Backend
- Model configuration (confidence threshold, target FPS)

**Outputs:**
- Detection results (event type, confidence, bounding boxes)
- Model health/metrics

**Failure Domain:** If AI Runtime fails:
- No new detections occur
- Backend continues to receive frames (queued or dropped based on backpressure)
- Existing violations/events remain intact
- Video streaming to UI continues unaffected

**Scaling Characteristics:**
- GPU-bound workload
- One runtime instance can handle multiple streams (shared model)
- Vertical scaling: more powerful GPU
- Horizontal scaling: multiple runtime instances, partitioned by camera assignment

---

#### 3. Operator Portal (Frontend)

**Responsibility:** Provide operator interface for monitoring and review.

**Inputs:**
- Device list from VAS (proxied through Ruth AI Backend)
- Live video from VAS (direct WebRTC connection)
- Violations/events from Ruth AI Backend

**Outputs:**
- Operator actions (review, dismiss, resolve violations)
- Stream start/stop requests

**Failure Domain:** If Frontend fails:
- Backend and AI continue operating
- Violations still created
- No operator visibility until recovery

**Scaling Characteristics:**
- Static assets served from CDN
- Stateless
- Horizontal scaling: multiple instances

---

## AI Execution Architecture

### Multi-Camera Shared Runtime Model

The PRD explicitly requires that **one AI model container subscribes to multiple camera streams**. This is the core architectural challenge.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      AI RUNTIME EXECUTION MODEL                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  BACKEND (Frame Producer)                    AI RUNTIME (Consumer)              │
│  ─────────────────────────                   ──────────────────────             │
│                                                                                 │
│  ┌──────────┐                                                                   │
│  │ Camera 1 │──┐                                                                │
│  │ Stream   │  │                                                                │
│  └──────────┘  │                                                                │
│                │     ┌─────────────────┐      ┌─────────────────────┐           │
│  ┌──────────┐  │     │                 │      │                     │           │
│  │ Camera 2 │──┼────>│ Frame Scheduler │─────>│   Model Executor    │           │
│  │ Stream   │  │     │                 │      │                     │           │
│  └──────────┘  │     │  - Queue per    │      │  - Single model     │           │
│                │     │    camera       │      │    instance         │           │
│  ┌──────────┐  │     │  - Round-robin  │      │  - Batch inference  │           │
│  │ Camera 3 │──┘     │    or priority  │      │    (optional)       │           │
│  │ Stream   │        │  - FPS control  │      │  - Fall detection   │           │
│  └──────────┘        │  - Backpressure │      │                     │           │
│                      └─────────────────┘      └──────────┬──────────┘           │
│                                                          │                      │
│                                                          ▼                      │
│                                               ┌─────────────────────┐           │
│                                               │  Detection Output   │           │
│                                               │                     │           │
│                                               │  { camera_id,       │           │
│                                               │    event_type,      │           │
│                                               │    confidence,      │           │
│                                               │    bbox,            │           │
│                                               │    timestamp }      │           │
│                                               └─────────────────────┘           │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Frame Scheduling Strategy

**Chosen Approach: Round-Robin with Priority Override**

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    FRAME SCHEDULING ALGORITHM                            │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. Each camera has a dedicated frame queue                              │
│  2. Scheduler pulls frames in round-robin order                          │
│  3. FPS limiting: drop frames if queue exceeds target FPS                │
│  4. Priority cameras get 2x pull rate                                    │
│                                                                          │
│  Example (3 cameras, 10 FPS target per camera):                          │
│                                                                          │
│  Time │ Frame Source │ Action                                            │
│  ─────┼──────────────┼───────────────────────────────────────            │
│  T1   │ Camera 1     │ Pull frame, send to model                         │
│  T2   │ Camera 2     │ Pull frame, send to model                         │
│  T3   │ Camera 3     │ Pull frame, send to model                         │
│  T4   │ Camera 1     │ Pull frame, send to model                         │
│  ...  │ ...          │ Round-robin continues                             │
│                                                                          │
│  Backpressure: If model cannot keep up (inference time > frame interval):│
│  - Drop oldest frames from queue                                         │
│  - Log backpressure event                                                │
│  - Reduce FPS temporarily (adaptive throttling)                          │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

**Alternatives Considered:**

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| Round-robin | Simple, fair distribution | No priority handling | **Selected** (with priority extension) |
| Oldest-first | Process stale frames first | Can starve high-priority cameras | Rejected |
| Per-camera threads | Parallel processing | Complex synchronization, GPU contention | Rejected for v1 |

### Backpressure Handling

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    BACKPRESSURE STRATEGY                                 │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Queue Depth Thresholds:                                                 │
│  ─────────────────────                                                   │
│  - NORMAL: < 30 frames (3 seconds at 10 FPS)                             │
│  - WARNING: 30-60 frames → log warning, no action                        │
│  - CRITICAL: > 60 frames → drop oldest 50%, alert                        │
│                                                                          │
│  Adaptive Throttling:                                                    │
│  ───────────────────                                                     │
│  - If WARNING for > 10 seconds: reduce target FPS by 20%                 │
│  - If CRITICAL: reduce target FPS by 50%                                 │
│  - When queue drains to NORMAL: restore original FPS                     │
│                                                                          │
│  Metrics Exposed:                                                        │
│  ───────────────                                                         │
│  - ruth_ai_frame_queue_depth{camera_id}                                  │
│  - ruth_ai_frames_dropped_total{camera_id}                               │
│  - ruth_ai_inference_latency_ms                                          │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Model Isolation and Failure Recovery

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    MODEL FAILURE HANDLING                                │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Failure Modes:                                                          │
│  ─────────────                                                           │
│  1. Model inference timeout (> 5 seconds)                                │
│     → Skip frame, log timeout, continue                                  │
│                                                                          │
│  2. Model crash (OOM, segfault)                                          │
│     → Restart model process                                              │
│     → Queue frames during restart (max 60 frames)                        │
│     → Drop frames if queue full                                          │
│                                                                          │
│  3. Model returns invalid output                                         │
│     → Log error, skip frame, continue                                    │
│                                                                          │
│  Recovery Strategy:                                                      │
│  ─────────────────                                                       │
│  - Health check endpoint: GET /health (every 5 seconds)                  │
│  - Max restart attempts: 3 within 5 minutes                              │
│  - After 3 failures: alert, stop processing, wait for manual intervention│
│                                                                          │
│  Isolation Guarantee:                                                    │
│  ───────────────────                                                     │
│  - Model runs in separate process/container                              │
│  - Backend ↔ AI Runtime communication via gRPC/REST                      │
│  - Model crash does NOT crash Backend                                    │
│  - Video streaming to UI is NOT affected by model failure                │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### AI Runtime Capability Declaration

**Principle:** The AI Runtime must declare its execution capabilities at startup. The Backend treats the AI Runtime as a black box and adapts scheduling behavior based on reported capabilities.

**Required Capability Declaration:**

```json
{
  "runtime_id": "ai-runtime-001",
  "supports_gpu": true,
  "hardware_type": "gpu",
  "supported_models": ["fall_detection_v1", "fall_detection_v2"],
  "max_fps": 100,
  "max_concurrent_streams": 10,
  "inference_batch_size": 4,
  "memory_available_mb": 8192,
  "version": "1.0.0"
}
```

**Capability Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `runtime_id` | string | Unique identifier for this runtime instance |
| `supports_gpu` | boolean | Whether GPU acceleration is available |
| `hardware_type` | enum | `cpu` \| `gpu` \| `jetson` \| `tpu` |
| `supported_models` | string[] | List of model IDs this runtime can execute |
| `max_fps` | integer | Maximum frames per second this runtime can process |
| `max_concurrent_streams` | integer | Maximum camera streams this runtime can handle |
| `inference_batch_size` | integer | Optimal batch size for inference (1 = no batching) |
| `memory_available_mb` | integer | Available memory for model execution |
| `version` | string | Runtime software version |

**Backend Adaptation Rules:**

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    CAPABILITY-BASED SCHEDULING                           │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  On Runtime Registration:                                                │
│  ────────────────────────                                                │
│  1. Runtime calls POST /api/internal/register with capabilities          │
│  2. Backend stores capabilities in Redis                                 │
│  3. Frame Scheduler adjusts based on hardware_type:                      │
│                                                                          │
│     hardware_type │ max_fps adjustment │ batch_size │ timeout            │
│     ──────────────┼────────────────────┼────────────┼─────────           │
│     gpu           │ Use declared       │ 4-8        │ 100ms              │
│     cpu           │ Cap at 30 FPS      │ 1          │ 500ms              │
│     jetson        │ Cap at 50 FPS      │ 2          │ 200ms              │
│                                                                          │
│  On Capability Change:                                                   │
│  ─────────────────────                                                   │
│  - Runtime can re-register with updated capabilities                     │
│  - Backend gracefully adjusts without dropping frames                    │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

**Why This Matters:**

| Deployment Scenario | Hardware Type | Behavior |
|---------------------|---------------|----------|
| Local development | `cpu` | Lower FPS, longer timeouts, no batching |
| Production server | `gpu` | Full FPS, short timeouts, batch inference |
| Edge deployment | `jetson` | Moderate FPS, optimized for power efficiency |
| Kubernetes cluster | Any | Works identically regardless of orchestrator |
| Docker Compose | Any | Works identically regardless of orchestrator |

This single capability declaration ensures the architecture works across all deployment environments without code changes.

---

## Data Flows

### 1. Video Flow: VAS → Ruth AI Backend

```
┌────────────┐        ┌────────────┐        ┌────────────┐        ┌────────────┐
│ VAS Device │        │    VAS     │        │  Ruth AI   │        │  mediasoup │
│    API     │        │  Backend   │        │  Backend   │        │  -client   │
└─────┬──────┘        └─────┬──────┘        └─────┬──────┘        └─────┬──────┘
      │                     │                     │                     │
      │ 1. GET /devices     │                     │                     │
      │<────────────────────│                     │                     │
      │                     │                     │                     │
      │ 2. POST /start-stream                     │                     │
      │<────────────────────│                     │                     │
      │                     │                     │                     │
      │   stream_id, room_id│                     │                     │
      │────────────────────>│                     │                     │
      │                     │                     │                     │
      │                     │ 3. GET /router-capabilities               │
      │                     │<────────────────────│                     │
      │                     │                     │                     │
      │                     │    rtp_capabilities │                     │
      │                     │────────────────────>│                     │
      │                     │                     │                     │
      │                     │                     │ 4. device.load()    │
      │                     │                     │────────────────────>│
      │                     │                     │                     │
      │                     │ 5. POST /consume    │                     │
      │                     │<────────────────────│                     │
      │                     │                     │                     │
      │                     │   transport params  │                     │
      │                     │────────────────────>│                     │
      │                     │                     │                     │
      │                     │                     │ 6. createRecvTransport
      │                     │                     │────────────────────>│
      │                     │                     │                     │
      │                     │ 7. POST /connect    │                     │
      │                     │<────────────────────│                     │
      │                     │                     │                     │
      │                     │ 8. WebRTC Media     │                     │
      │                     │═════════════════════│═════════════════════│
      │                     │                     │    media stream     │
      │                     │                     │<════════════════════│
      │                     │                     │                     │
```

### 2. Frame Flow: Stream → AI Model

```
┌────────────┐        ┌────────────┐        ┌────────────┐        ┌────────────┐
│  WebRTC    │        │   Frame    │        │   Frame    │        │    AI      │
│  Consumer  │        │  Extractor │        │  Scheduler │        │  Runtime   │
└─────┬──────┘        └─────┬──────┘        └─────┬──────┘        └─────┬──────┘
      │                     │                     │                     │
      │ 1. ontrack event    │                     │                     │
      │────────────────────>│                     │                     │
      │                     │                     │                     │
      │ 2. Video frame      │                     │                     │
      │═════════════════════│                     │                     │
      │  (30 FPS from VAS)  │                     │                     │
      │                     │                     │                     │
      │                     │ 3. Extract frame    │                     │
      │                     │    (every 100ms     │                     │
      │                     │     = 10 FPS)       │                     │
      │                     │────────────────────>│                     │
      │                     │                     │                     │
      │                     │                     │ 4. Queue frame      │
      │                     │                     │    by camera_id     │
      │                     │                     │                     │
      │                     │                     │ 5. Round-robin pull │
      │                     │                     │────────────────────>│
      │                     │                     │                     │
      │                     │                     │ 6. Inference        │
      │                     │                     │    (fall detection) │
      │                     │                     │                     │
      │                     │                     │<────────────────────│
      │                     │                     │   detection result  │
      │                     │                     │                     │
```

### 3. Event Flow: Detection → Violation

```
┌────────────┐        ┌────────────┐        ┌────────────┐        ┌────────────┐
│    AI      │        │   Event    │        │ Violation  │        │ PostgreSQL │
│  Runtime   │        │   Engine   │        │  Manager   │        │            │
└─────┬──────┘        └─────┬──────┘        └─────┬──────┘        └─────┬──────┘
      │                     │                     │                     │
      │ 1. Detection        │                     │                     │
      │    { event_type:    │                     │                     │
      │      "fall_detected"│                     │                     │
      │      confidence: 0.92 }                   │                     │
      │────────────────────>│                     │                     │
      │                     │                     │                     │
      │                     │ 2. Dedupe check     │                     │
      │                     │    (same camera,    │                     │
      │                     │     last 5 sec?)    │                     │
      │                     │                     │                     │
      │                     │ 3. Threshold check  │                     │
      │                     │    (confidence >    │                     │
      │                     │     0.7?)           │                     │
      │                     │                     │                     │
      │                     │ 4. Create Event     │                     │
      │                     │────────────────────>│                     │
      │                     │                     │                     │
      │                     │                     │ 5. Create Violation │
      │                     │                     │    { type: "fall",  │
      │                     │                     │      status: "open",│
      │                     │                     │      camera_id,     │
      │                     │                     │      confidence }   │
      │                     │                     │────────────────────>│
      │                     │                     │                     │
      │                     │                     │   violation_id      │
      │                     │                     │<────────────────────│
      │                     │                     │                     │
```

### 4. Evidence Flow: Snapshot/Bookmark via VAS

```
┌────────────┐        ┌────────────┐        ┌────────────┐        ┌────────────┐
│ Violation  │        │  Evidence  │        │    VAS     │        │ PostgreSQL │
│  Manager   │        │  Creator   │        │  Backend   │        │            │
└─────┬──────┘        └─────┬──────┘        └─────┬──────┘        └─────┬──────┘
      │                     │                     │                     │
      │ 1. Violation created│                     │                     │
      │    (fall_detected)  │                     │                     │
      │────────────────────>│                     │                     │
      │                     │                     │                     │
      │                     │ 2. POST /snapshots  │                     │
      │                     │────────────────────>│                     │
      │                     │                     │                     │
      │                     │   snapshot_id       │                     │
      │                     │<────────────────────│                     │
      │                     │                     │                     │
      │                     │ 3. POST /bookmarks  │                     │
      │                     │    (before: 5s,     │                     │
      │                     │     after: 10s)     │                     │
      │                     │────────────────────>│                     │
      │                     │                     │                     │
      │                     │   bookmark_id       │                     │
      │                     │<────────────────────│                     │
      │                     │                     │                     │
      │                     │ 4. Poll for ready   │                     │
      │                     │    status           │                     │
      │                     │<───────────────────>│                     │
      │                     │                     │                     │
      │                     │ 5. Link evidence    │                     │
      │                     │    to violation     │                     │
      │                     │──────────────────────────────────────────>│
      │                     │                     │                     │
```

---

## API & Contract Boundaries

### Ruth AI Public API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/violations` | GET | List violations with filtering |
| `/api/v1/violations/{id}` | GET | Get violation details |
| `/api/v1/violations/{id}` | PATCH | Update violation status |
| `/api/v1/events` | GET | List events with filtering |
| `/api/v1/events/{id}` | GET | Get event details |
| `/api/v1/analytics/summary` | GET | Get analytics summary |
| `/api/v1/models/status` | GET | Get AI model health |
| `/api/v1/health` | GET | Service health check |

### Internal Service Contracts

**Backend → AI Runtime (gRPC/REST)**

```protobuf
// Frame submission
message InferenceRequest {
  string camera_id = 1;
  string frame_id = 2;
  bytes frame_data = 3;       // JPEG or raw pixels
  string timestamp = 4;
  string model_id = 5;        // "fall_detection"
}

message InferenceResponse {
  string frame_id = 1;
  string camera_id = 2;
  string event_type = 3;      // "fall_detected" | "no_fall"
  float confidence = 4;
  repeated BoundingBox boxes = 5;
  int32 inference_time_ms = 6;
}

message BoundingBox {
  int32 x = 1;
  int32 y = 2;
  int32 width = 3;
  int32 height = 4;
  string label = 5;
}
```

### Event Schema

```json
{
  "event": {
    "id": "uuid",
    "camera_id": "uuid",
    "stream_id": "uuid",
    "event_type": "fall_detected",
    "confidence": 0.92,
    "timestamp": "2026-01-13T10:30:00Z",
    "model_id": "fall_detection_v1",
    "model_version": "1.0.0",
    "bounding_boxes": [
      { "x": 100, "y": 150, "width": 200, "height": 400, "label": "person" }
    ],
    "frame_id": "uuid",
    "created_at": "2026-01-13T10:30:00.123Z"
  }
}
```

### Violation Schema

```json
{
  "violation": {
    "id": "uuid",
    "type": "fall_detected",
    "camera_id": "uuid",
    "camera_name": "Front Door Camera",
    "status": "open",
    "confidence": 0.92,
    "timestamp": "2026-01-13T10:30:00Z",
    "model_id": "fall_detection_v1",
    "model_version": "1.0.0",
    "evidence": {
      "snapshot_id": "uuid",
      "snapshot_url": "/api/v1/violations/{id}/snapshot",
      "bookmark_id": "uuid",
      "bookmark_url": "/api/v1/violations/{id}/video"
    },
    "events": ["event_id_1", "event_id_2"],
    "reviewed_by": null,
    "reviewed_at": null,
    "created_at": "2026-01-13T10:30:00.123Z",
    "updated_at": "2026-01-13T10:30:00.123Z"
  }
}
```

**Violation Status Values:**
- `open` - New violation, not yet reviewed
- `reviewed` - Operator has seen the violation
- `dismissed` - False positive or not actionable
- `resolved` - Incident handled

### Data Model Ownership

| Entity | Owner Service | Storage |
|--------|---------------|---------|
| Device | VAS | VAS Database |
| Stream | VAS | VAS Database |
| Consumer | VAS | VAS Database |
| Snapshot | VAS | VAS Database + File Storage |
| Bookmark | VAS | VAS Database + File Storage |
| Event | Ruth AI Backend | Ruth AI PostgreSQL |
| Violation | Ruth AI Backend | Ruth AI PostgreSQL |
| Analytics Aggregates | Ruth AI Backend | Ruth AI PostgreSQL |

---

## Deployment Topology

### Container Layout

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              RUTH AI DEPLOYMENT                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                          Docker Compose / K8s                           │    │
│  ├─────────────────────────────────────────────────────────────────────────┤    │
│  │                                                                         │    │
│  │  ┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐  │    │
│  │  │  ruth-ai-backend  │   │   ruth-ai-runtime │   │  ruth-ai-portal   │  │    │
│  │  │                   │   │                   │   │                   │  │    │
│  │  │  Port: 8080       │   │  Port: 50051      │   │  Port: 3000       │  │    │
│  │  │  Replicas: 2      │   │  Replicas: 1      │   │  Replicas: 2      │  │    │
│  │  │  Memory: 2GB      │   │  Memory: 4GB      │   │  Memory: 512MB    │  │    │
│  │  │  CPU: 2           │   │  GPU: 1           │   │  CPU: 1           │  │    │
│  │  └───────────────────┘   └───────────────────┘   └───────────────────┘  │    │
│  │           │                       │                       │             │    │
│  │           │                       │                       │             │    │
│  │           ▼                       │                       │             │    │
│  │  ┌───────────────────┐            │                       │             │    │
│  │  │    PostgreSQL     │<───────────┘                       │             │    │
│  │  │    Port: 5432     │                                    │             │    │
│  │  │    Replicas: 1    │                                    │             │    │
│  │  └───────────────────┘                                    │             │    │
│  │           │                                               │             │    │
│  │           │                                               │             │    │
│  │  ┌───────────────────┐                                    │             │    │
│  │  │       Redis       │<───────────────────────────────────┘             │    │
│  │  │    Port: 6379     │                                                  │    │
│  │  │    Replicas: 1    │                                                  │    │
│  │  └───────────────────┘                                                  │    │
│  │                                                                         │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                 │
│  External Connections:                                                          │
│  ─────────────────────                                                          │
│  ruth-ai-backend ──────> VAS Backend (http://10.30.250.245:8085)                │
│  ruth-ai-portal ────────> VAS Backend (direct for video)                        │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Service Communication Matrix

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| Portal | Backend | REST/HTTP | API calls |
| Portal | VAS | WebRTC | Live video |
| Backend | VAS | REST/HTTP | Stream management, evidence |
| Backend | AI Runtime | gRPC | Frame inference |
| Backend | PostgreSQL | PostgreSQL | Data persistence |
| Backend | Redis | Redis | Session cache |

### Environment Separation

| Environment | Purpose | VAS Instance | Data |
|-------------|---------|--------------|------|
| Development | Local dev | Local/Docker | Mock data |
| Staging | Integration testing | Staging VAS | Test data |
| Production | Live operation | Production VAS | Real data |

### Observability Integration Points

| Service | Logs | Metrics | Traces |
|---------|------|---------|--------|
| Backend | stdout (JSON) | Prometheus `/metrics` | OpenTelemetry |
| AI Runtime | stdout (JSON) | Prometheus `/metrics` | OpenTelemetry |
| Portal | Browser console | - | - |

**Key Metrics to Expose:**

```
# Backend
ruth_ai_streams_active
ruth_ai_frames_processed_total
ruth_ai_violations_created_total
ruth_ai_events_created_total
ruth_ai_vas_api_latency_seconds

# AI Runtime
ruth_ai_inference_latency_seconds
ruth_ai_inference_throughput_fps
ruth_ai_frame_queue_depth
ruth_ai_frames_dropped_total
ruth_ai_model_health
```

---

## Key Decisions & Rationale

### Decision 1: Node.js for Backend (vs Python)

**Choice:** Node.js (or Python FastAPI) for Ruth AI Backend

**Rationale:**
- Excellent WebRTC client library support (mediasoup-client)
- Non-blocking I/O suits high-concurrency frame handling
- Same language as VAS for consistency
- Python is acceptable if team prefers, FastAPI provides similar async capabilities

**Trade-offs:**
- AI team may prefer Python for tighter model integration
- If chosen: Python Backend + mediasoup via aiortc

### Decision 2: gRPC for Backend ↔ AI Runtime Communication

**Choice:** gRPC (vs REST)

**Rationale:**
- Efficient binary serialization for frame data
- Built-in streaming support for future batch inference
- Strong typing via protobuf
- Lower latency than REST for high-frequency calls

**Trade-offs:**
- Adds gRPC dependency
- REST is simpler if frame rate is low enough

**Alternative considered:** REST with base64-encoded frames (rejected due to 33% overhead)

### Decision 3: Round-Robin Frame Scheduling

**Choice:** Round-robin with priority override

**Rationale:**
- Simple to implement and reason about
- Fair distribution across cameras
- Priority mechanism allows future enhancement without redesign

**Trade-offs:**
- May not be optimal if cameras have different importance
- Future: Can add weighted round-robin if needed

### Decision 4: Evidence Created via VAS (not local capture)

**Choice:** Use VAS Snapshot/Bookmark APIs for evidence

**Rationale:**
- VAS already has the video data
- Avoids duplicating storage
- Consistent with "VAS is the video gateway" principle
- Async processing aligns with VAS design

**Trade-offs:**
- Depends on VAS availability
- Slight delay in evidence availability (async processing)

### Decision 5: Single AI Runtime Instance for v1

**Choice:** One AI Runtime container handling all cameras

**Rationale:**
- Simpler deployment
- Sufficient for initial scale (10 cameras at 10 FPS each = 100 FPS total)
- GPU utilization is efficient with batching

**Trade-offs:**
- Single point of failure for AI
- Must partition cameras if scaling beyond GPU capacity

**Future:** Horizontal scaling with camera-to-runtime assignment

---

## Risks & Assumptions

### Assumptions

| ID | Assumption | Impact if False |
|----|------------|-----------------|
| A1 | VAS-MS-V2 is stable and available | Ruth AI cannot function without VAS |
| A2 | WebRTC consumer connections are reliable | Frame extraction may fail intermittently |
| A3 | Fall detection model is production-ready | Detection quality may be poor |
| A4 | 10 FPS is sufficient for fall detection | Missed detections possible |
| A5 | Single GPU can handle initial camera count | Need to scale sooner |

### Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|------------|--------|------------|
| R1 | VAS API contract changes | Medium | High | API Contract Guardian agent monitors changes |
| R2 | AI Runtime GPU memory exhaustion | Medium | High | Monitor GPU memory, implement frame dropping |
| R3 | WebRTC connection instability | Low | Medium | Implement reconnection logic |
| R4 | Frame queue backlog during inference delays | Medium | Medium | Backpressure handling, adaptive throttling |
| R5 | Evidence creation fails (VAS unavailable) | Low | Medium | Retry with backoff, queue evidence requests |

### Dependencies

| Dependency | Type | Owner | Status |
|------------|------|-------|--------|
| VAS-MS-V2 Backend API | External | VAS Team | Available |
| VAS-MS-V2 MediaSoup | External | VAS Team | Available |
| Fall Detection Model | Internal | AI Team | Assumed ready |
| PostgreSQL | Infrastructure | DevOps | Standard |
| Redis | Infrastructure | DevOps | Standard |

---

## Open Questions

| ID | Question | Blocking? | Owner |
|----|----------|-----------|-------|
| Q1 | What is the exact fall detection model interface? (input format, output schema) | Yes | AI Team |
| Q2 | GPU model/memory available in production? | Yes | DevOps |
| Q3 | VAS authentication: should Ruth AI use dedicated client credentials or share with other services? | No | VAS Team |
| Q4 | Should violation notifications be real-time (WebSocket) or polling-based? | No | Product |
| Q5 | Analytics retention period? How long to keep event/violation history? | No | Product |
| Q6 | What browsers must the Operator Portal support? | No | Frontend Team |

---

## Next-Step Handoffs

### Backend Team

1. Implement VAS Gateway component:
   - Authentication (token management, refresh)
   - Device listing proxy
   - Stream lifecycle management
   - Consumer attachment/detachment

2. Implement Frame Scheduler:
   - WebRTC consumer → frame extraction
   - Queue management per camera
   - Round-robin dispatch to AI Runtime

3. Implement Event Engine:
   - Receive detection results from AI Runtime
   - Deduplication logic
   - Confidence thresholding
   - Event persistence

4. Implement Violation Manager:
   - Violation creation from events
   - Status workflow (open → reviewed → resolved/dismissed)
   - Evidence linking

5. Implement Evidence Creator:
   - Snapshot requests to VAS
   - Bookmark requests to VAS
   - Async polling for completion
   - Link evidence to violations

6. Expose Ruth AI APIs:
   - `/api/v1/violations`
   - `/api/v1/events`
   - `/api/v1/analytics/summary`
   - `/api/v1/models/status`
   - `/api/v1/health`

### AI Team

1. Package fall detection model as container:
   - Expose gRPC endpoint for inference
   - Health check endpoint
   - Metrics endpoint

2. Define model interface:
   - Input: JPEG frame or raw pixels
   - Output: event_type, confidence, bounding_boxes

3. Implement inference server:
   - Receive frames from Backend
   - Run model inference
   - Return detection results

4. Performance testing:
   - Validate inference latency (< 100ms target)
   - Validate throughput (100+ FPS)
   - GPU memory profiling

### Frontend Team

1. Implement Device List view:
   - Fetch devices via Ruth AI Backend (proxied from VAS)
   - Display device status

2. Implement Live Video view:
   - WebRTC connection to VAS (direct)
   - Display AI detection status (overlay or panel)

3. Implement Violation Review:
   - List violations with filtering
   - View violation details
   - Play evidence video
   - Update violation status

4. Implement Analytics Dashboard (basic):
   - Violations per camera
   - Violations per time window

### DevOps Team

1. Container orchestration:
   - Docker Compose for development
   - Kubernetes manifests for staging/production

2. Database provisioning:
   - PostgreSQL with migrations
   - Redis for caching

3. Observability:
   - Prometheus scraping
   - Log aggregation
   - Grafana dashboards

4. CI/CD pipeline:
   - Build containers
   - Run tests
   - Deploy to environments

---

**End of Architecture Document**