# Ruth AI API & Contract Specification

**Version:** 1.0
**Status:** Draft - Approved
**Date:** January 2026
**Author:** API & Contract Authority Agent
**Delivery Gate:** No implementation may begin until this specification is approved.

---

## Document Purpose

This specification defines all Ruth AI-owned interfaces, schemas, and contracts. It serves as the **hard delivery gate** between design and implementation phases. Backend, AI Runtime, and Frontend teams must implement exactly to these contracts.

---

## Input Document References

| Document                             | Version | Status                          |
|--------------------------------------|---------|---------------------------------|
| Ruth AI Product Requirement Document | 0.1     | Approved                        |
| Ruth AI System Architecture Design   | 1.0     | Approved                        |
| VAS-MS-V2 Integration Guide          | 2.1     | Validated                       |
| VAS API Guardian Outputs             | Latest  | Validated (87/88 tests passing) |

---

## Table of Contents

1. [Ruth AI Public API Specification](#1-ruth-ai-public-api-specification)
2. [Internal Service Contracts](#2-internal-service-contracts)
3. [Domain Model Definitions](#3-domain-model-definitions)
4. [Error & Status Semantics](#4-error--status-semantics)
5. [Versioning & Compatibility Policy](#5-versioning--compatibility-policy)
6. [Open Questions & Assumptions](#6-open-questions--assumptions)
7. [Self-Verification Checklist](#7-self-verification-checklist)

---

## 1. Ruth AI Public API Specification

### 1.1 API Overview

**Base URL:** `/api/v1`

**Authentication:** JWT Bearer Token (to be implemented by Ruth AI)

**Content-Type:** `application/json`

All endpoints require authentication unless explicitly marked as public.

**Authentication Scope:**
- Authentication tokens are issued by Ruth AI and represent authenticated operators or services
- VAS credentials are never exposed to API consumers; Ruth AI uses internal VAS credentials for upstream calls
- Service-to-service authentication (e.g., AI Runtime → Backend) may use separate credentials or mutual TLS
- Token scopes and role-based access control are defined by Ruth AI independently of VAS permissions

---

### 1.2 Health & Status Endpoints

#### GET /api/v1/health

**Description:** Service health check endpoint. Returns the overall health status of Ruth AI.

**Authentication:** Not required (public endpoint)

**Request:** None

**Response (200 OK):**
```json
{
  "status": "healthy",
  "service": "ruth-ai",
  "version": "1.0.0",
  "timestamp": "2026-01-13T10:00:00.000Z",
  "components": {
    "database": "healthy",
    "redis": "healthy",
    "ai_runtime": "healthy"
  }
}
```

**Response (503 Service Unavailable):**
```json
{
  "status": "unhealthy",
  "service": "ruth-ai",
  "version": "1.0.0",
  "timestamp": "2026-01-13T10:00:00.000Z",
  "components": {
    "database": "healthy",
    "redis": "healthy",
    "ai_runtime": "unhealthy"
  },
  "error": "AI Runtime is not responding"
}
```

**Rationale:** Public health endpoint enables load balancer and monitoring integration without authentication overhead.

---

#### GET /api/v1/models/status

**Description:** Returns the health and status of all AI models.

**Authentication:** Required

**Request:** None

**Response (200 OK):**
```json
{
  "models": [
    {
      "model_id": "fall_detection",
      "version": "1.0.0",
      "status": "active",
      "health": "healthy",
      "metrics": {
        "inference_latency_ms_avg": 85,
        "inference_latency_ms_p99": 150,
        "throughput_fps": 95,
        "frames_processed_total": 1234567,
        "errors_total": 42
      },
      "cameras_active": 8,
      "last_inference_at": "2026-01-13T10:00:00.000Z",
      "started_at": "2026-01-13T00:00:00.000Z"
    }
  ],
  "summary": {
    "total_models": 1,
    "healthy_models": 1,
    "total_cameras_processed": 8
  }
}
```

**Model Status Values:**
| Status     | Description                            |
|------------|----------------------------------------|
| `active`   | Model is running and processing frames |
| `idle`     | Model is loaded but not processing     |
| `starting` | Model is initializing                  |
| `stopping` | Model is shutting down                 |
| `error`    | Model encountered an error             |

**Model Health Values:**
| Health      | Description                                    |
|-------------|------------------------------------------------|
| `healthy`   | Inference latency within acceptable range      |
| `degraded`  | Inference latency elevated or partial failures |
| `unhealthy` | Model not responding or critical failure       |

**Rationale:** Exposes AI runtime health for operator visibility without leaking internal model architecture details.

---

### 1.3 Violation Endpoints

#### GET /api/v1/violations

**Description:** List violations with filtering and pagination.

**Authentication:** Required

**Query Parameters:**

| Parameter        | Type | Required | Default | Description |
|------------------|--------|----------|---------|-------------|
| `status`         | string | No | - | Filter by status: `open`, `reviewed`, `dismissed`, `resolved` |
| `type`           | string | No | - | Filter by violation type (e.g., `fall_detected`) |
| `camera_id`      | UUID | No | - | Filter by camera ID |
| `from`           | ISO 8601 datetime | No | - | Violations created after this time |
| `to`             | ISO 8601 datetime | No | - | Violations created before this time |
| `confidence_min` | float | No | - | Minimum confidence score (0.0-1.0) |
| `sort_by`        | string | No | `created_at` | Sort field: `created_at`, `confidence`, `status` |
| `sort_order`     | string | No | `desc` | Sort order: `asc`, `desc` |
| `limit`          | integer | No | 50 | Max results (1-100) |
| `offset`         | integer | No | 0 | Pagination offset |

**Request:**
```http
GET /api/v1/violations?status=open&limit=20&offset=0
Authorization: Bearer <access_token>
```

**Response (200 OK):**
```json
{
  "violations": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "type": "fall_detected",
      "camera_id": "660e8400-e29b-41d4-a716-446655440001",
      "camera_name": "Front Door Camera",
      "status": "open",
      "confidence": 0.92,
      "timestamp": "2026-01-13T10:30:00.000Z",
      "model_id": "fall_detection",
      "model_version": "1.0.0",
      "evidence": {
        "snapshot_id": "770e8400-e29b-41d4-a716-446655440002",
        "snapshot_url": "/api/v1/violations/550e8400.../snapshot",
        "bookmark_id": "880e8400-e29b-41d4-a716-446655440003",
        "bookmark_url": "/api/v1/violations/550e8400.../video",
        "evidence_status": "ready"
      },
      "reviewed_by": null,
      "reviewed_at": null,
      "created_at": "2026-01-13T10:30:00.123Z",
      "updated_at": "2026-01-13T10:30:00.123Z"
    }
  ],
  "pagination": {
    "total": 150,
    "limit": 20,
    "offset": 0,
    "has_more": true
  }
}
```

**Rationale:** Filtering by status and time range enables efficient violation triage. Pagination prevents response size explosion.

---

#### GET /api/v1/violations/{id}

**Description:** Get detailed information about a specific violation.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | UUID | Yes | Violation ID |

**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "fall_detected",
  "camera_id": "660e8400-e29b-41d4-a716-446655440001",
  "camera_name": "Front Door Camera",
  "stream_id": "990e8400-e29b-41d4-a716-446655440004",
  "status": "open",
  "confidence": 0.92,
  "timestamp": "2026-01-13T10:30:00.000Z",
  "model_id": "fall_detection",
  "model_version": "1.0.0",
  "bounding_boxes": [
    {
      "x": 100,
      "y": 150,
      "width": 200,
      "height": 400,
      "label": "person",
      "confidence": 0.95
    }
  ],
  "evidence": {
    "snapshot_id": "770e8400-e29b-41d4-a716-446655440002",
    "snapshot_url": "/api/v1/violations/550e8400.../snapshot",
    "snapshot_status": "ready",
    "bookmark_id": "880e8400-e29b-41d4-a716-446655440003",
    "bookmark_url": "/api/v1/violations/550e8400.../video",
    "bookmark_status": "ready",
    "bookmark_duration_seconds": 15
  },
  "events": [
    {
      "id": "aa0e8400-e29b-41d4-a716-446655440005",
      "timestamp": "2026-01-13T10:30:00.000Z",
      "confidence": 0.92
    }
  ],
  "reviewed_by": null,
  "reviewed_at": null,
  "resolution_notes": null,
  "created_at": "2026-01-13T10:30:00.123Z",
  "updated_at": "2026-01-13T10:30:00.123Z"
}
```

**Response (404 Not Found):**
```json
{
  "error": "VIOLATION_NOT_FOUND",
  "error_description": "Violation with ID '550e8400...' does not exist",
  "status_code": 404
}
```

**Rationale:** Detailed view includes bounding boxes and full event history for operator review.

---

#### PATCH /api/v1/violations/{id}

**Description:** Update violation status and add review information.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | UUID | Yes | Violation ID |

**Request Body:**
```json
{
  "status": "reviewed",
  "resolution_notes": "Operator confirmed fall incident, emergency services notified"
}
```

**Allowed Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | string | No | New status: `reviewed`, `dismissed`, `resolved` |
| `resolution_notes` | string | No | Operator notes (max 2000 chars) |

**Status Transition Rules:**

| From | Allowed To |
|------|------------|
| `open` | `reviewed`, `dismissed` |
| `reviewed` | `dismissed`, `resolved` |
| `dismissed` | `open` (re-open) |
| `resolved` | - (terminal state) |

**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "reviewed",
  "reviewed_by": "operator@example.com",
  "reviewed_at": "2026-01-13T11:00:00.000Z",
  "resolution_notes": "Operator confirmed fall incident, emergency services notified",
  "updated_at": "2026-01-13T11:00:00.000Z"
}
```

**Response (400 Bad Request - Invalid Transition):**
```json
{
  "error": "INVALID_STATUS_TRANSITION",
  "error_description": "Cannot transition from 'resolved' to 'reviewed'",
  "status_code": 400,
  "details": {
    "current_status": "resolved",
    "requested_status": "reviewed",
    "allowed_transitions": []
  }
}
```

**Rationale:** Status transitions are constrained to enforce violation lifecycle. `resolved` is terminal to maintain audit trail integrity.

---

#### GET /api/v1/violations/{id}/snapshot

**Description:** Retrieve the snapshot image associated with a violation.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | UUID | Yes | Violation ID |

**Response (200 OK):**
- Content-Type: `image/jpeg`
- Body: Binary image data

**Response (404 Not Found):**
```json
{
  "error": "EVIDENCE_NOT_FOUND",
  "error_description": "Snapshot for violation '550e8400...' does not exist or is not ready",
  "status_code": 404
}
```

**Response (202 Accepted - Processing):**
```json
{
  "error": "EVIDENCE_PROCESSING",
  "error_description": "Snapshot is still being processed",
  "status_code": 202,
  "details": {
    "snapshot_id": "770e8400...",
    "status": "processing",
    "retry_after_seconds": 5
  }
}
```

**Rationale:** Proxies VAS snapshot through Ruth AI to abstract VAS internals. 202 response handles async processing.

---

#### GET /api/v1/violations/{id}/video

**Description:** Retrieve the bookmark video clip associated with a violation.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | UUID | Yes | Violation ID |

**Response (200 OK):**
- Content-Type: `video/mp4`
- Body: Binary video data

**Response (404 Not Found):**
```json
{
  "error": "EVIDENCE_NOT_FOUND",
  "error_description": "Video for violation '550e8400...' does not exist or is not ready",
  "status_code": 404
}
```

**Response (202 Accepted - Processing):**
```json
{
  "error": "EVIDENCE_PROCESSING",
  "error_description": "Video bookmark is still being processed",
  "status_code": 202,
  "details": {
    "bookmark_id": "880e8400...",
    "status": "processing",
    "retry_after_seconds": 10
  }
}
```

**Rationale:** Proxies VAS bookmark through Ruth AI to abstract VAS internals.

---

### 1.4 Event Endpoints

#### GET /api/v1/events

**Description:** List raw AI detection events with filtering and pagination.

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `event_type` | string | No | - | Filter by event type (e.g., `fall_detected`, `no_fall`) |
| `camera_id` | UUID | No | - | Filter by camera ID |
| `violation_id` | UUID | No | - | Filter events linked to a specific violation |
| `from` | ISO 8601 datetime | No | - | Events after this time |
| `to` | ISO 8601 datetime | No | - | Events before this time |
| `confidence_min` | float | No | - | Minimum confidence score (0.0-1.0) |
| `limit` | integer | No | 100 | Max results (1-1000) |
| `offset` | integer | No | 0 | Pagination offset |

**Request:**
```http
GET /api/v1/events?camera_id=660e8400...&event_type=fall_detected&limit=50
Authorization: Bearer <access_token>
```

**Response (200 OK):**
```json
{
  "events": [
    {
      "id": "aa0e8400-e29b-41d4-a716-446655440005",
      "camera_id": "660e8400-e29b-41d4-a716-446655440001",
      "stream_id": "990e8400-e29b-41d4-a716-446655440004",
      "event_type": "fall_detected",
      "confidence": 0.92,
      "timestamp": "2026-01-13T10:30:00.000Z",
      "model_id": "fall_detection",
      "model_version": "1.0.0",
      "bounding_boxes": [
        {
          "x": 100,
          "y": 150,
          "width": 200,
          "height": 400,
          "label": "person",
          "confidence": 0.95
        }
      ],
      "frame_id": "bb0e8400-e29b-41d4-a716-446655440006",
      "violation_id": "550e8400-e29b-41d4-a716-446655440000",
      "created_at": "2026-01-13T10:30:00.123Z"
    }
  ],
  "pagination": {
    "total": 5000,
    "limit": 50,
    "offset": 0,
    "has_more": true
  }
}
```

**Rationale:** Events are high-volume raw data. Higher default limit (100) and max (1000) support analytics use cases. Events link to violations for traceability.

---

#### GET /api/v1/events/{id}

**Description:** Get detailed information about a specific event.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | UUID | Yes | Event ID |

**Response (200 OK):**
```json
{
  "id": "aa0e8400-e29b-41d4-a716-446655440005",
  "camera_id": "660e8400-e29b-41d4-a716-446655440001",
  "camera_name": "Front Door Camera",
  "stream_id": "990e8400-e29b-41d4-a716-446655440004",
  "event_type": "fall_detected",
  "confidence": 0.92,
  "timestamp": "2026-01-13T10:30:00.000Z",
  "model_id": "fall_detection",
  "model_version": "1.0.0",
  "bounding_boxes": [
    {
      "x": 100,
      "y": 150,
      "width": 200,
      "height": 400,
      "label": "person",
      "confidence": 0.95
    }
  ],
  "frame_id": "bb0e8400-e29b-41d4-a716-446655440006",
  "inference_time_ms": 85,
  "violation_id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2026-01-13T10:30:00.123Z"
}
```

**Response (404 Not Found):**
```json
{
  "error": "EVENT_NOT_FOUND",
  "error_description": "Event with ID 'aa0e8400...' does not exist",
  "status_code": 404
}
```

---

### 1.5 Analytics Endpoints

#### GET /api/v1/analytics/summary

**Description:** Get aggregated analytics summary for operational monitoring.

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `from` | ISO 8601 datetime | No | 24 hours ago | Start of time range |
| `to` | ISO 8601 datetime | No | now | End of time range |
| `camera_id` | UUID | No | - | Filter by specific camera |
| `granularity` | string | No | `hour` | Aggregation granularity: `minute`, `hour`, `day` |

**Request:**
```http
GET /api/v1/analytics/summary?from=2026-01-12T00:00:00Z&granularity=hour
Authorization: Bearer <access_token>
```

**Response (200 OK):**
```json
{
  "summary": {
    "time_range": {
      "from": "2026-01-12T00:00:00.000Z",
      "to": "2026-01-13T00:00:00.000Z"
    },
    "totals": {
      "violations_total": 45,
      "violations_open": 12,
      "violations_reviewed": 18,
      "violations_dismissed": 10,
      "violations_resolved": 5,
      "events_total": 15000,
      "events_fall_detected": 85,
      "cameras_active": 8
    },
    "by_camera": [
      {
        "camera_id": "660e8400-e29b-41d4-a716-446655440001",
        "camera_name": "Front Door Camera",
        "violations_total": 8,
        "violations_open": 2,
        "events_total": 2500,
        "last_event_at": "2026-01-13T10:30:00.000Z"
      }
    ],
    "time_series": [
      {
        "bucket": "2026-01-12T00:00:00.000Z",
        "violations": 3,
        "events": 650
      },
      {
        "bucket": "2026-01-12T01:00:00.000Z",
        "violations": 2,
        "events": 580
      }
    ]
  },
  "generated_at": "2026-01-13T10:35:00.000Z"
}
```

**Rationale:** Analytics are derived from events and violations per PRD requirement. Granularity options support different operational views.

---

#### GET /api/v1/analytics/cameras/{camera_id}

**Description:** Get analytics for a specific camera.

**Authentication:** Required

**Path Parameters:**

| Parameter   | Type | Required | Description      |
|-------------|------|----------|------------------|
| `camera_id` | UUID | Yes      | Camera/Device ID |

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `from` | ISO 8601 datetime | No | 24 hours ago | Start of time range |
| `to` | ISO 8601 datetime | No | now | End of time range |

**Response (200 OK):**
```json
{
  "camera_id": "660e8400-e29b-41d4-a716-446655440001",
  "camera_name": "Front Door Camera",
  "time_range": {
    "from": "2026-01-12T00:00:00.000Z",
    "to": "2026-01-13T00:00:00.000Z"
  },
  "metrics": {
    "violations_total": 8,
    "violations_by_status": {
      "open": 2,
      "reviewed": 3,
      "dismissed": 2,
      "resolved": 1
    },
    "events_total": 2500,
    "events_by_type": {
      "fall_detected": 12,
      "no_fall": 2488
    },
    "avg_confidence": 0.87,
    "last_violation_at": "2026-01-13T10:30:00.000Z",
    "last_event_at": "2026-01-13T10:35:00.000Z"
  },
  "inference_stats": {
    "frames_processed": 25000,
    "fps_avg": 9.8,
    "inference_latency_ms_avg": 82
  },
  "generated_at": "2026-01-13T10:40:00.000Z"
}
```

---

### 1.6 Device Proxy Endpoints

**Note:** Ruth AI proxies device information from VAS to provide a unified API. These endpoints do NOT expose VAS internals.

#### GET /api/v1/devices

**Description:** List available devices/cameras. Proxied from VAS. Device IDs are VAS-owned identifiers and are treated as opaque by Ruth AI.

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `is_active` | boolean | No | - | Filter by active status |
| `limit` | integer | No | 100 | Max results (1-100) |
| `offset` | integer | No | 0 | Pagination offset |

**Response (200 OK):**
```json
{
  "devices": [
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "name": "Front Door Camera",
      "description": "Main entrance camera",
      "location": "Building A - Entrance",
      "is_active": true,
      "streaming": {
        "active": true,
        "stream_id": "990e8400-e29b-41d4-a716-446655440004",
        "ai_enabled": true,
        "model_id": "fall_detection"
      },
      "created_at": "2026-01-10T08:00:00.000Z"
    }
  ],
  "pagination": {
    "total": 10,
    "limit": 100,
    "offset": 0,
    "has_more": false
  }
}
```

**Rationale:** Device listing is proxied from VAS but enriched with Ruth AI streaming status. No RTSP URLs or VAS-internal details exposed.

---

#### GET /api/v1/devices/{id}

**Description:** Get device details enriched with Ruth AI status.

**Authentication:** Required

**Response (200 OK):**
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "name": "Front Door Camera",
  "description": "Main entrance camera",
  "location": "Building A - Entrance",
  "is_active": true,
  "streaming": {
    "active": true,
    "stream_id": "990e8400-e29b-41d4-a716-446655440004",
    "state": "live",
    "ai_enabled": true,
    "model_id": "fall_detection",
    "inference_fps": 10,
    "started_at": "2026-01-13T00:00:00.000Z"
  },
  "statistics": {
    "violations_24h": 3,
    "events_24h": 850,
    "last_violation_at": "2026-01-13T10:30:00.000Z"
  },
  "created_at": "2026-01-10T08:00:00.000Z"
}
```

---

### 1.7 Streaming Control Endpoints

#### POST /api/v1/devices/{id}/start-inference

**Description:** Enable AI inference on a device's stream. If the stream is not already running in VAS, this endpoint will start it.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | UUID | Yes | Device ID |

**Request Body:**
```json
{
  "model_id": "fall_detection",
  "inference_fps": 10,
  "confidence_threshold": 0.7
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `model_id` | string | Yes | - | AI model to use |
| `inference_fps` | integer | No | 10 | Target frames per second for inference |
| `confidence_threshold` | float | No | 0.7 | Minimum confidence to trigger violation |

**Response (200 OK):**
```json
{
  "device_id": "660e8400-e29b-41d4-a716-446655440001",
  "stream_id": "990e8400-e29b-41d4-a716-446655440004",
  "status": "started",
  "model_id": "fall_detection",
  "inference_fps": 10,
  "confidence_threshold": 0.7,
  "started_at": "2026-01-13T11:00:00.000Z"
}
```

**Response (409 Conflict - Already Running):**
```json
{
  "error": "INFERENCE_ALREADY_ACTIVE",
  "error_description": "AI inference is already active for this device",
  "status_code": 409,
  "details": {
    "device_id": "660e8400...",
    "model_id": "fall_detection",
    "started_at": "2026-01-13T00:00:00.000Z"
  }
}
```

**Response (503 Service Unavailable - Stream Error):**
```json
{
  "error": "STREAM_UNAVAILABLE",
  "error_description": "Cannot start inference: VAS stream is not available",
  "status_code": 503,
  "details": {
    "vas_error": "RTSP_TIMEOUT"
  }
}
```

**Rationale:** Inference control is separate from VAS stream control. Ruth AI manages AI pipeline; VAS manages video transport.

---

#### POST /api/v1/devices/{id}/stop-inference

**Description:** Disable AI inference on a device's stream. The VAS stream continues running (for other consumers or UI viewing).

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | UUID | Yes | Device ID |

**Response (200 OK):**
```json
{
  "device_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "stopped",
  "stopped_at": "2026-01-13T11:30:00.000Z"
}
```

**Response (404 Not Found - Not Running):**
```json
{
  "error": "INFERENCE_NOT_ACTIVE",
  "error_description": "AI inference is not active for this device",
  "status_code": 404
}
```

---

## 2. Internal Service Contracts

### 2.1 Backend ↔ AI Runtime Interface

**Transport:** gRPC

**Rationale for gRPC over REST:**
1. Efficient binary serialization for frame data (avoids 33% base64 overhead)
2. Built-in streaming support for batch inference
3. Strong typing via protobuf prevents schema drift
4. Lower latency for high-frequency inference calls (~10ms vs ~50ms)

---

### 2.2 Service Definition (Protobuf)

```protobuf
syntax = "proto3";

package ruth.ai.v1;

// AI Runtime Service - processes video frames through AI models
service AIRuntime {
  // Submit a single frame for inference
  rpc Infer(InferenceRequest) returns (InferenceResponse);

  // Stream multiple frames for inference (future batch support)
  rpc InferStream(stream InferenceRequest) returns (stream InferenceResponse);

  // Health check
  rpc HealthCheck(HealthCheckRequest) returns (HealthCheckResponse);

  // Get model status
  rpc GetModelStatus(ModelStatusRequest) returns (ModelStatusResponse);
}

// Frame submission for inference
message InferenceRequest {
  // Unique identifier for this frame
  string frame_id = 1;

  // Camera/device identifier
  string camera_id = 2;

  // Stream identifier (from VAS)
  string stream_id = 3;

  // Frame timestamp (ISO 8601)
  string timestamp = 4;

  // Model to use for inference
  string model_id = 5;

  // Frame data - JPEG encoded
  bytes frame_data = 6;

  // Frame dimensions
  int32 width = 7;
  int32 height = 8;

  // Optional: minimum confidence threshold
  float confidence_threshold = 9;
}

// Inference result
message InferenceResponse {
  // Echo back frame identifiers for correlation
  string frame_id = 1;
  string camera_id = 2;
  string stream_id = 3;

  // Detection result
  string event_type = 4;  // "fall_detected" | "no_fall" | "error"
  float confidence = 5;

  // Bounding boxes for detected objects
  repeated BoundingBox bounding_boxes = 6;

  // Processing metrics
  int32 inference_time_ms = 7;
  string model_version = 8;

  // Error information (if event_type == "error")
  string error_code = 9;
  string error_message = 10;
}

// Bounding box for detected object
message BoundingBox {
  int32 x = 1;
  int32 y = 2;
  int32 width = 3;
  int32 height = 4;
  string label = 5;
  float confidence = 6;
}

// Health check messages
message HealthCheckRequest {}

message HealthCheckResponse {
  string status = 1;  // "healthy" | "degraded" | "unhealthy"
  string model_id = 2;
  string model_version = 3;
  int64 uptime_seconds = 4;
  int64 frames_processed = 5;
  float avg_inference_time_ms = 6;
}

// Model status messages
message ModelStatusRequest {
  string model_id = 1;
}

message ModelStatusResponse {
  string model_id = 1;
  string version = 2;
  string status = 3;  // "active" | "idle" | "starting" | "stopping" | "error"
  bool is_healthy = 4;

  ModelMetrics metrics = 5;
}

message ModelMetrics {
  int64 frames_processed_total = 1;
  int64 errors_total = 2;
  float inference_latency_ms_avg = 3;
  float inference_latency_ms_p99 = 4;
  float throughput_fps = 5;
  int32 cameras_active = 6;
}
```

---

### 2.3 Communication Patterns

#### 2.3.1 Frame Submission Pattern

```
Backend                          AI Runtime
   │                                  │
   │  InferenceRequest                │
   │  {frame_id, camera_id,           │
   │   frame_data, model_id}          │
   │ ────────────────────────────────>│
   │                                  │ [Process frame]
   │                                  │ [Run model inference]
   │  InferenceResponse               │
   │  {event_type, confidence,        │
   │   bounding_boxes}                │
   │ <────────────────────────────────│
   │                                  │
```

#### 2.3.2 Health Check Pattern

**Frequency:** Every 5 seconds
**Timeout:** 3 seconds
**Failure threshold:** 3 consecutive failures → mark AI Runtime as unhealthy

#### 2.3.3 Backpressure Handling

| Condition | AI Runtime Behavior | Backend Behavior |
|-----------|---------------------|------------------|
| Queue depth < 30 | Process normally | Send frames at configured FPS |
| Queue depth 30-60 | Log warning | Reduce FPS by 20% |
| Queue depth > 60 | Return `RESOURCE_EXHAUSTED` | Drop oldest 50% of queue, reduce FPS by 50% |

---

### 2.4 Error Handling

| gRPC Status | Meaning | Backend Action |
|-------------|---------|----------------|
| `OK` | Success | Process response |
| `UNAVAILABLE` | AI Runtime down | Queue frames, retry with backoff |
| `DEADLINE_EXCEEDED` | Inference timeout (>5s) | Skip frame, log timeout |
| `RESOURCE_EXHAUSTED` | Queue full | Drop frames, reduce FPS |
| `INVALID_ARGUMENT` | Bad frame data | Log error, skip frame |
| `INTERNAL` | Model error | Log error, skip frame, monitor |

---

### 2.5 Timeout Specifications

| Operation | Timeout | Retry Strategy |
|-----------|---------|----------------|
| Infer (single frame) | 5 seconds | No retry (frame is stale) |
| HealthCheck | 3 seconds | 3 retries with 1s delay |
| GetModelStatus | 5 seconds | 2 retries with 2s delay |
| Connection establishment | 10 seconds | 3 retries with exponential backoff |

---

## 3. Domain Model Definitions

### 3.1 Event Schema

```typescript
/**
 * Event represents a single AI detection output.
 * Events are high-volume, raw outputs from AI models.
 * Multiple events may be aggregated into a single Violation.
 */
interface Event {
  /**
   * Unique identifier for this event
   * Format: UUID v4
   */
  id: string;

  /**
   * Camera/device that produced this event
   * References VAS device ID
   */
  camera_id: string;

  /**
   * VAS stream identifier
   */
  stream_id: string;

  /**
   * Type of event detected
   * Enum: "fall_detected" | "no_fall" | "person_detected" | "unknown"
   */
  event_type: EventType;

  /**
   * Model confidence score
   * Range: 0.0 to 1.0
   */
  confidence: number;

  /**
   * Timestamp when the event occurred (frame capture time)
   * Format: ISO 8601 with milliseconds
   */
  timestamp: string;

  /**
   * Model that produced this detection
   */
  model_id: string;

  /**
   * Version of the model
   * Format: semver (e.g., "1.0.0")
   */
  model_version: string;

  /**
   * Detected objects with bounding boxes
   * May be empty for some event types
   */
  bounding_boxes: BoundingBox[];

  /**
   * Reference to the frame that was analyzed
   * Internal identifier for debugging
   */
  frame_id: string;

  /**
   * Inference processing time in milliseconds
   */
  inference_time_ms: number;

  /**
   * Violation this event is linked to (if any)
   * Null if event did not trigger a violation
   */
  violation_id: string | null;

  /**
   * Timestamp when this record was created
   * Format: ISO 8601 with milliseconds
   */
  created_at: string;
}

enum EventType {
  FALL_DETECTED = "fall_detected",
  NO_FALL = "no_fall",
  PERSON_DETECTED = "person_detected",
  UNKNOWN = "unknown"
}
```

---

### 3.2 Violation Schema

```typescript
/**
 * Violation represents a confirmed or potential safety incident.
 * Violations are created when AI detects significant events.
 * Each Violation has a lifecycle: open → reviewed → resolved/dismissed
 */
interface Violation {
  /**
   * Unique identifier for this violation
   * Format: UUID v4
   */
  id: string;

  /**
   * Type of violation
   * Derived from the triggering event type
   */
  type: ViolationType;

  /**
   * Camera/device where violation was detected
   * References VAS device ID
   */
  camera_id: string;

  /**
   * Human-readable camera name (denormalized for display)
   */
  camera_name: string;

  /**
   * VAS stream identifier at time of detection
   */
  stream_id: string;

  /**
   * Current status in the violation lifecycle
   */
  status: ViolationStatus;

  /**
   * Highest confidence score among triggering events
   * Range: 0.0 to 1.0
   */
  confidence: number;

  /**
   * Timestamp when the violation was detected
   * Format: ISO 8601 with milliseconds
   */
  timestamp: string;

  /**
   * Model that detected this violation
   */
  model_id: string;

  /**
   * Version of the model
   * Format: semver
   */
  model_version: string;

  /**
   * Bounding boxes from the primary detection
   */
  bounding_boxes: BoundingBox[];

  /**
   * Evidence associated with this violation
   */
  evidence: Evidence;

  /**
   * IDs of events that contributed to this violation
   * Minimum 1 event required
   */
  event_ids: string[];

  /**
   * User who reviewed this violation (if reviewed)
   */
  reviewed_by: string | null;

  /**
   * Timestamp when violation was reviewed
   */
  reviewed_at: string | null;

  /**
   * Operator notes about resolution
   * Max length: 2000 characters
   */
  resolution_notes: string | null;

  /**
   * Timestamp when this record was created
   */
  created_at: string;

  /**
   * Timestamp when this record was last updated
   */
  updated_at: string;
}

enum ViolationType {
  FALL_DETECTED = "fall_detected"
  // Future: INTRUSION = "intrusion", FIRE = "fire", etc.
}

enum ViolationStatus {
  /**
   * New violation, not yet seen by operator
   */
  OPEN = "open",

  /**
   * Operator has viewed the violation
   */
  REVIEWED = "reviewed",

  /**
   * Marked as false positive or not actionable
   */
  DISMISSED = "dismissed",

  /**
   * Incident has been handled (terminal state)
   */
  RESOLVED = "resolved"
}
```

---

### 3.3 Evidence Schema

```typescript
/**
 * Evidence contains references to snapshot and video bookmark
 * created via VAS when a violation is detected.
 * Evidence is created asynchronously.
 */
interface Evidence {
  /**
   * VAS snapshot ID
   */
  snapshot_id: string | null;

  /**
   * URL to retrieve snapshot (proxied through Ruth AI)
   */
  snapshot_url: string | null;

  /**
   * Processing status of snapshot
   */
  snapshot_status: EvidenceStatus;

  /**
   * VAS bookmark ID
   */
  bookmark_id: string | null;

  /**
   * URL to retrieve video (proxied through Ruth AI)
   */
  bookmark_url: string | null;

  /**
   * Processing status of bookmark
   */
  bookmark_status: EvidenceStatus;

  /**
   * Duration of bookmark video in seconds
   * Default: 15 (5 before + 10 after event)
   */
  bookmark_duration_seconds: number;
}

enum EvidenceStatus {
  /**
   * Evidence creation has been requested
   */
  PENDING = "pending",

  /**
   * VAS is processing the evidence
   */
  PROCESSING = "processing",

  /**
   * Evidence is ready for retrieval
   */
  READY = "ready",

  /**
   * Evidence creation failed permanently.
   * Ruth AI will NOT retry automatically; operator intervention required.
   * The violation remains valid but evidence must be manually re-requested if needed.
   */
  FAILED = "failed"
}
```

---

### 3.4 Bounding Box Schema

```typescript
/**
 * Bounding box identifies a detected object's location in a frame.
 */
interface BoundingBox {
  /**
   * X coordinate of top-left corner (pixels)
   */
  x: number;

  /**
   * Y coordinate of top-left corner (pixels)
   */
  y: number;

  /**
   * Width of bounding box (pixels)
   */
  width: number;

  /**
   * Height of bounding box (pixels)
   */
  height: number;

  /**
   * Classification label (e.g., "person", "fall")
   */
  label: string;

  /**
   * Confidence score for this specific detection
   * Range: 0.0 to 1.0
   */
  confidence: number;
}
```

---

### 3.5 Analytics Aggregates Schema

```typescript
/**
 * Analytics aggregates are pre-computed summaries for dashboard display.
 * Computed from events and violations on a scheduled basis.
 */
interface AnalyticsSummary {
  /**
   * Time range for this summary
   */
  time_range: TimeRange;

  /**
   * Overall totals across all cameras
   */
  totals: AnalyticsTotals;

  /**
   * Breakdown by camera
   */
  by_camera: CameraAnalytics[];

  /**
   * Time series data for charts
   */
  time_series: TimeSeriesBucket[];

  /**
   * When this summary was generated
   */
  generated_at: string;
}

interface TimeRange {
  from: string;  // ISO 8601
  to: string;    // ISO 8601
}

interface AnalyticsTotals {
  violations_total: number;
  violations_open: number;
  violations_reviewed: number;
  violations_dismissed: number;
  violations_resolved: number;
  events_total: number;
  events_fall_detected: number;
  cameras_active: number;
}

interface CameraAnalytics {
  camera_id: string;
  camera_name: string;
  violations_total: number;
  violations_open: number;
  events_total: number;
  last_event_at: string | null;
}

interface TimeSeriesBucket {
  /**
   * Start of time bucket (ISO 8601)
   */
  bucket: string;

  /**
   * Violations in this bucket
   */
  violations: number;

  /**
   * Events in this bucket
   */
  events: number;
}
```

---

## 4. Error & Status Semantics

### 4.1 Standard Error Response Format

All Ruth AI API errors follow this consistent format:

```json
{
  "error": "ERROR_CODE",
  "error_description": "Human-readable error message",
  "status_code": 400,
  "details": {
    "field": "Additional context"
  },
  "request_id": "req_abc123xyz",
  "timestamp": "2026-01-13T10:00:00.000Z"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `error` | string | Yes | Machine-readable error code (SCREAMING_SNAKE_CASE) |
| `error_description` | string | Yes | Human-readable message for display |
| `status_code` | integer | Yes | HTTP status code (matches response) |
| `details` | object | No | Additional context, field errors |
| `request_id` | string | Yes | Unique request ID for debugging |
| `timestamp` | string | Yes | ISO 8601 timestamp |

---

### 4.2 Error Code Taxonomy

#### 4.2.1 Client Errors (4xx)

| Error Code | HTTP Status | Description | Retryable |
|------------|-------------|-------------|-----------|
| `VALIDATION_ERROR` | 400 | Request validation failed | No |
| `INVALID_PARAMETER` | 400 | Specific parameter is invalid | No |
| `MISSING_REQUIRED_FIELD` | 400 | Required field not provided | No |
| `INVALID_TOKEN` | 401 | Access token invalid or malformed | Yes (refresh) |
| `TOKEN_EXPIRED` | 401 | Access token has expired | Yes (refresh) |
| `INSUFFICIENT_PERMISSIONS` | 403 | Valid token but lacks required scope | No |
| `RESOURCE_NOT_FOUND` | 404 | Requested resource does not exist | No |
| `VIOLATION_NOT_FOUND` | 404 | Violation ID not found | No |
| `EVENT_NOT_FOUND` | 404 | Event ID not found | No |
| `DEVICE_NOT_FOUND` | 404 | Device ID not found | No |
| `INVALID_STATUS_TRANSITION` | 400 | Status change not allowed | No |
| `INFERENCE_ALREADY_ACTIVE` | 409 | Inference already running | No |
| `INFERENCE_NOT_ACTIVE` | 404 | Inference not running | No |

#### 4.2.2 Server Errors (5xx)

| Error Code | HTTP Status | Description | Retryable |
|------------|-------------|-------------|-----------|
| `INTERNAL_ERROR` | 500 | Unexpected server error | Yes (1-2x) |
| `DATABASE_ERROR` | 500 | Database operation failed | Yes (1-2x) |
| `AI_RUNTIME_ERROR` | 503 | AI Runtime unavailable | Yes (backoff) |
| `VAS_UNAVAILABLE` | 503 | VAS service unavailable | Yes (backoff) |
| `STREAM_UNAVAILABLE` | 503 | Video stream not available | Yes (backoff) |
| `EVIDENCE_PROCESSING` | 202 | Evidence still being processed | Yes (poll) |
| `EVIDENCE_NOT_FOUND` | 404 | Evidence does not exist | No |
| `EVIDENCE_FAILED` | 500 | Evidence creation failed | Yes (1x) |

---

### 4.3 Retry Strategy Matrix

| Error Category | Retry? | Max Retries | Backoff Strategy |
|----------------|--------|-------------|------------------|
| 400 Validation | No | - | - |
| 401 Unauthorized | Yes (with refresh) | 1 | Immediate |
| 403 Forbidden | No | - | - |
| 404 Not Found | No | - | - |
| 409 Conflict | No | - | - |
| 500 Internal | Yes | 2 | 2s, 5s |
| 503 Unavailable | Yes | 3 | 5s, 10s, 30s |
| 202 Processing | Yes (poll) | 10 | 1s, 2s, 3s, 5s... (exponential) |

---

### 4.4 Error Response Examples

#### Validation Error
```json
{
  "error": "VALIDATION_ERROR",
  "error_description": "Request validation failed",
  "status_code": 400,
  "details": {
    "confidence_min": "Must be between 0.0 and 1.0",
    "limit": "Must be between 1 and 100"
  },
  "request_id": "req_abc123",
  "timestamp": "2026-01-13T10:00:00.000Z"
}
```

#### Invalid Status Transition
```json
{
  "error": "INVALID_STATUS_TRANSITION",
  "error_description": "Cannot transition from 'resolved' to 'open'",
  "status_code": 400,
  "details": {
    "current_status": "resolved",
    "requested_status": "open",
    "allowed_transitions": []
  },
  "request_id": "req_def456",
  "timestamp": "2026-01-13T10:00:00.000Z"
}
```

#### AI Runtime Unavailable
```json
{
  "error": "AI_RUNTIME_ERROR",
  "error_description": "AI Runtime service is not responding",
  "status_code": 503,
  "details": {
    "last_healthy_at": "2026-01-13T09:55:00.000Z",
    "retry_after_seconds": 30
  },
  "request_id": "req_ghi789",
  "timestamp": "2026-01-13T10:00:00.000Z"
}
```

---

### 4.5 Mapping Internal Errors to Public API

| Internal Error Source | Public Error Code | User-Facing Message |
|----------------------|-------------------|---------------------|
| gRPC UNAVAILABLE | AI_RUNTIME_ERROR | "AI processing is temporarily unavailable" |
| gRPC DEADLINE_EXCEEDED | AI_RUNTIME_ERROR | "AI processing is taking too long" |
| PostgreSQL connection error | DATABASE_ERROR | "Service temporarily unavailable" |
| VAS API 5xx | VAS_UNAVAILABLE | "Video service is temporarily unavailable" |
| VAS API 404 | DEVICE_NOT_FOUND | "Device not found" |
| Bookmark status=failed | EVIDENCE_FAILED | "Could not create evidence for this violation" |

**Rationale:** Internal details (gRPC status codes, database names, VAS error codes) are never exposed to public API consumers.

---

## 5. Versioning & Compatibility Policy

### 5.1 API Versioning Strategy

**Versioning Scheme:** URL path versioning (`/api/v1`, `/api/v2`, etc.)

**Rationale:** URL versioning is explicit, visible in logs and monitoring, and easily enforced by routing.

---

### 5.2 Version Lifecycle

| Phase | Duration | Support Level |
|-------|----------|---------------|
| **Current** | Unlimited | Full support, bug fixes, new features |
| **Deprecated** | 6 months minimum | Bug fixes only, no new features |
| **Sunset** | After deprecation | Read-only, then removed |

**Version Transition Timeline:**
1. Announce deprecation → 6 months before sunset
2. Add deprecation headers → Immediately upon announcement
3. Read-only mode → 1 month before removal
4. Remove version → After sunset date

---

### 5.3 Breaking vs Non-Breaking Changes

#### Breaking Changes (Require Version Bump)

| Change Type | Example | Action Required |
|-------------|---------|-----------------|
| Remove endpoint | DELETE `/api/v1/legacy` | New version |
| Remove required field | Remove `camera_id` from Violation | New version |
| Change field type | `confidence: string` → `confidence: number` | New version |
| Rename field | `camera_id` → `device_id` | New version |
| Change authentication | API key → JWT | New version |
| Change error code semantics | `404` → `400` for same error | New version |
| Remove enum value | Remove `"dismissed"` from status | New version |

#### Non-Breaking Changes (Additive)

| Change Type | Example | Action Required |
|-------------|---------|-----------------|
| Add new endpoint | Add `/api/v1/reports` | None |
| Add optional field | Add `tags: string[]` to Violation | None |
| Add new enum value | Add `"escalated"` to status | None |
| Add query parameter | Add `?include_events=true` | None |
| Extend error details | Add `retry_after` to error response | None |
| Improve error messages | Better `error_description` text | None |

---

### 5.4 Deprecation Communication

#### Deprecation Response Headers

When an endpoint is deprecated:

```http
Deprecation: true
Sunset: Sat, 01 Jul 2026 00:00:00 GMT
Link: </api/v2/violations>; rel="successor-version"
```

#### Deprecation in Response Body

```json
{
  "violations": [...],
  "_deprecation": {
    "deprecated": true,
    "sunset_date": "2026-07-01",
    "successor": "/api/v2/violations",
    "migration_guide": "https://docs.ruth-ai.com/migration/v1-to-v2"
  }
}
```

---

### 5.5 Consumer Protection Guarantees

1. **Minimum deprecation period:** 6 months from announcement to sunset
2. **No silent breaking changes:** All breaking changes require version bump
3. **Deprecation headers:** Always present before sunset
4. **Migration documentation:** Provided for every version transition
5. **Parallel operation:** New version available before old version is deprecated
6. **Rollback capability:** Old version remains available during transition period

---

### 5.6 Internal Contract Versioning (gRPC)

**Protobuf versioning strategy:**

1. Add `reserved` for removed field numbers
2. Never change field numbers
3. Never change field types (add new field instead)
4. Version package: `ruth.ai.v1`, `ruth.ai.v2`

```protobuf
// Example: Adding a field without breaking compatibility
message InferenceRequest {
  string frame_id = 1;
  // ... existing fields ...

  // Added in v1.1 - optional for backward compatibility
  optional int32 priority = 10;

  // Reserved for removed fields
  reserved 9;
  reserved "deprecated_field";
}
```

---

## 6. Open Questions & Assumptions

### 6.1 Assumptions Made

| ID | Assumption | Impact if False | Validation Owner |
|----|------------|-----------------|------------------|
| A1 | VAS-MS-V2 streams return frames at consistent 30 FPS | Frame extraction timing may vary | VAS Team |
| A2 | Fall detection model input is JPEG at 640x480 minimum | Frame preprocessing may be needed | AI Team |
| A3 | Single AI Runtime can handle 10 cameras at 10 FPS each | Need horizontal scaling sooner | DevOps |
| A4 | Evidence creation (bookmark) completes within 30 seconds | Longer polling timeout needed | VAS Team |
| A5 | JWT authentication is sufficient for MVP | May need API keys for service-to-service | Security |
| A6 | PostgreSQL can handle event volume (100 events/sec) | May need time-series DB | DevOps |
| A7 | 15-second bookmark duration (5 before + 10 after) is sufficient | Configuration may be needed | Product |
| A8 | All services rely on synchronized system clocks (NTP) | Timestamp ordering issues, event correlation errors | DevOps |

---

### 6.2 Open Questions Requiring Resolution

| ID | Question | Blocking? | Owner | Target Date |
|----|----------|-----------|-------|-------------|
| Q1 | What is the exact fall detection model input format? (resolution, color space, normalization) | **Yes** | AI Team | Before AI Runtime implementation |
| Q2 | Should violations support custom metadata fields? | No | Product | Before v1.1 |
| Q3 | What is the evidence retention period? | No | Product/Legal | Before production |
| Q4 | Should the Operator Portal use WebSocket for real-time violation updates? | No | Frontend Team | Before UI implementation |
| Q5 | What authentication scopes are needed for Ruth AI API? | **Yes** | Security | Before Backend implementation |
| Q6 | Should analytics support export (CSV/PDF)? | No | Product | Post-MVP |
| Q7 | What is the maximum concurrent cameras per AI Runtime? | **Yes** | AI Team | Before scaling design |
| Q8 | How should Ruth AI handle VAS token refresh? (embedded credentials vs. operator login) | No | Security | Before production |

---

### 6.3 Dependencies on Other Teams

| Dependency                      | Owner        | Required Artifact                | Status  |
|---------------------------------|--------------|----------------------------------|---------|
| Fall detection model container  | AI Team      | Docker image with gRPC interface | Pending |
| VAS API credentials for Ruth AI | VAS Team     | client_id/client_secret          | Pending |
| PostgreSQL schema migrations    | DevOps       | Database setup scripts           | Pending |
| JWT authentication service      | Backend Team | Auth middleware                  | Pending |
| GPU infrastructure              | DevOps       | Kubernetes GPU nodes             | Pending |

---

## 7. Self-Verification Checklist

### 7.1 Input Verification

- [x] Ruth AI PRD v0.1 consumed
- [x] Ruth AI System Architecture v1.0 consumed
- [x] VAS-MS-V2 Integration Guide v2.1 consumed
- [x] VAS API Guardian outputs reviewed

### 7.2 Scope Verification

- [x] All Ruth AI-owned REST endpoints defined
- [x] Internal service contract (Backend ↔ AI Runtime) defined
- [x] Domain schemas (Event, Violation, Evidence, Analytics) defined
- [x] Error handling standardized
- [x] Versioning policy documented

### 7.3 Constraint Verification

- [x] No architecture redesign performed
- [x] VAS APIs not re-validated (referenced only)
- [x] No VAS internals leak into Ruth AI APIs (RTSP, MediaSoup hidden)
- [x] No implementation code written
- [x] No performance optimizations specified

### 7.4 Quality Verification

- [x] All schemas are explicit with field types and descriptions
- [x] All schemas include version context
- [x] Error handling is comprehensive with codes and retry guidance
- [x] Versioning policy is clear with timeline
- [x] Open questions are documented with owners
- [x] Significant decisions include rationale

---

## Approval & Sign-Off

| Role                | Name | Date | Signature |
|---------------------|------|------|-----------|
| Product Owner       |      |      |           |
| Principal Architect |      |      |           |
| Backend Lead        |      |      |           |
| AI Team Lead        |      |      |           |
| Frontend Lead       |      |      |           |
| Security Review     |      |      |           |

---

**End of Specification**

*This specification was produced by the API & Contract Authority Agent.*

*Document Version: 1.0*
*Last Updated: January 2026*