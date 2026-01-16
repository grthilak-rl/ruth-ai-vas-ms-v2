# VAS-MS-V2 Integration Guide

**Version:** 2.1
**Last Updated:** January 2026
**Audience:** Ruth AI Developers, Third-Party Integrators
**OpenAPI Spec:** `/v2/openapi.json` (see [Appendix E](#appendix-e-openapi-specification))

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Authentication Model](#2-authentication-model)
3. [API Catalog](#3-api-catalog)
4. [Stream State Machine](#4-stream-state-machine)
5. [WebRTC Flow - Step by Step](#5-webrtc-flow---step-by-step)
6. [Ruth AI Integration Patterns](#6-ruth-ai-integration-patterns)
7. [Error Handling & Contracts](#7-error-handling--contracts)
8. [Async Processing (Bookmarks & Snapshots)](#8-async-processing-bookmarks--snapshots)
9. [What Ruth AI MUST NOT Do](#9-what-ruth-ai-must-not-do)
10. [Final Summary](#10-final-summary)

---

## 1. System Overview

### 1.1 What VAS-MS-V2 Is Responsible For

VAS-MS-V2 (Video Analytics Service - MediaSoup v2) is a **media gateway service** that:

- **Ingests RTSP streams** from IP cameras via FFmpeg
- **Transcodes and routes video** through MediaSoup (WebRTC SFU)
- **Exposes WebRTC endpoints** for real-time, low-latency video consumption
- **Records HLS segments** for historical playback (7-day retention by default)
- **Manages stream lifecycle** (start, stop, health monitoring)
- **Provides snapshot and bookmark APIs** for frame capture and video clip extraction
- **Handles authentication** via JWT tokens with scope-based permissions

### 1.2 What Ruth AI Is Responsible For

Ruth AI (or any third-party consumer) is responsible for:

- **Discovering devices** via the Device API
- **Requesting stream start/stop** via Device API (V1) or Stream API (V2)
- **Consuming WebRTC streams** using the mediasoup-client library
- **Managing local RTCPeerConnection** and media track handling
- **Creating snapshots and bookmarks** for AI-detected events
- **Gracefully handling disconnections** and reconnecting as needed
- **Token lifecycle management** (refresh before expiry)

### 1.3 Clear Boundary: WebRTC is Transport, Not Application Logic

```
┌─────────────────────────────────────────────────────────────────────┐
│                         VAS-MS-V2 DOMAIN                            │
├─────────────────────────────────────────────────────────────────────┤
│  RTSP Camera → FFmpeg → RTP → MediaSoup → WebRTC Transport          │
│                                                                     │
│  Responsibilities:                                                  │
│  - RTSP connection management                                       │
│  - Video transcoding (H.264)                                        │
│  - RTP packet routing                                               │
│  - WebRTC signaling (offer/answer, ICE, DTLS)                       │
│  - HLS recording                                                    │
│  - Stream state management                                          │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ WebRTC Media Stream
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        RUTH AI DOMAIN                               │
├─────────────────────────────────────────────────────────────────────┤
│  WebRTC Consumer → Video Decode → AI Pipeline → Actions             │
│                                                                     │
│  Responsibilities:                                                  │
│  - mediasoup-client Device management                               │
│  - RTCPeerConnection lifecycle                                      │
│  - Media track consumption                                          │
│  - Frame extraction for AI processing                               │
│  - Event detection and bookmark creation                            │
│  - UI rendering (if applicable)                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Key Principle:** VAS-MS-V2 delivers raw video frames over WebRTC. It has no knowledge of what Ruth AI does with those frames (object detection, anomaly detection, etc.). The boundary is the WebRTC media track.

---

## 2. Authentication Model

### 2.1 Authentication Mechanism

VAS-MS-V2 uses **JWT (JSON Web Token)** authentication with:

- **Access Tokens:** Short-lived (1 hour), used for API requests
- **Refresh Tokens:** Long-lived (7 days), used to obtain new access tokens
- **Scope-based Permissions:** Fine-grained access control per endpoint

### 2.2 Token Lifecycle

```
┌──────────────────────────────────────────────────────────────────┐
│                     TOKEN LIFECYCLE                               │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Client Registration (One-time, by Admin)                     │
│     POST /v2/auth/clients                                        │
│     └── Returns: client_id + client_secret (SAVE THIS!)          │
│                                                                  │
│  2. Token Generation                                             │
│     POST /v2/auth/token                                          │
│     └── Returns: access_token (1hr) + refresh_token (7d)         │
│                                                                  │
│  3. API Requests                                                 │
│     Authorization: Bearer <access_token>                         │
│                                                                  │
│  4. Token Refresh (before expiry)                                │
│     POST /v2/auth/token/refresh                                  │
│     └── Returns: new access_token                                │
│                                                                  │
│  5. Token Rotation (on refresh token expiry)                     │
│     Repeat step 2 with client credentials                        │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 2.3 Required Headers

| Header | Value | Required For |
|--------|-------|--------------|
| `Authorization` | `Bearer <access_token>` | All V2 API endpoints |
| `Content-Type` | `application/json` | POST/PUT requests |

### 2.4 Available Scopes

| Scope | Description |
|-------|-------------|
| `streams:read` | List and view stream information |
| `streams:write` | Create, update, delete streams |
| `streams:consume` | Attach WebRTC consumers to streams |
| `snapshots:read` | View and download snapshots |
| `snapshots:write` | Create and delete snapshots |
| `bookmarks:read` | View and download bookmarks |
| `bookmarks:write` | Create, update, delete bookmarks |

### 2.5 Protected vs Public Endpoints

| Endpoint Category | Authentication Required |
|-------------------|------------------------|
| V2 API (`/v2/*`) | **Yes** - JWT Bearer token |
| V1 Device API (`/api/v1/devices/*`) | No (legacy compatibility) |
| Health endpoints (`/v2/health/*`) | No |
| WebSocket signaling | Via query param or header |

### 2.6 Token Lifecycle Assumptions for Consumers

1. **Store tokens securely** - Never expose client_secret in frontend code
2. **Refresh proactively** - Refresh access token when ~80% of TTL has elapsed
3. **Handle 401 gracefully** - Retry with refreshed token, then re-authenticate
4. **Single active session** - One refresh token per client at a time

---

## 3. API Catalog

### 3.1 Authentication APIs

#### POST /v2/auth/clients
**Create a new API client (Admin only)**

```http
POST /v2/auth/clients
Content-Type: application/json

{
  "client_id": "ruth-ai-production",
  "scopes": ["streams:read", "streams:consume", "bookmarks:write", "snapshots:write"]
}
```

**Response (201 Created):**
```json
{
  "client_id": "ruth-ai-production",
  "client_secret": "abc123xyz...",
  "scopes": ["streams:read", "streams:consume", "bookmarks:write", "snapshots:write"],
  "created_at": "2026-01-12T10:00:00Z"
}
```

> **WARNING:** `client_secret` is only returned once. Store it securely.

---

#### POST /v2/auth/token
**Generate access and refresh tokens**

```http
POST /v2/auth/token
Content-Type: application/json

{
  "client_id": "ruth-ai-production",
  "client_secret": "abc123xyz..."
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "def456uvw...",
  "scopes": ["streams:read", "streams:consume", "bookmarks:write", "snapshots:write"]
}
```

**Error Response (401 Unauthorized):**
```json
{
  "error": "invalid_credentials",
  "error_description": "Invalid client credentials",
  "status_code": 401
}
```

---

#### POST /v2/auth/token/refresh
**Refresh an access token using a refresh token**

Use this endpoint to obtain a new access token before the current one expires. Best practice is to refresh when ~80% of the access token TTL has elapsed (e.g., at ~48 minutes for a 1-hour token).

```http
POST /v2/auth/token/refresh
Content-Type: application/json

{
  "refresh_token": "def456uvw..."
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scopes": ["streams:read", "streams:consume", "bookmarks:write", "snapshots:write"]
}
```

> **Note:** The refresh token itself is not rotated on refresh. It remains valid until its 7-day expiry.

**Error Response (401 Unauthorized - Expired/Invalid Refresh Token):**
```json
{
  "error": "invalid_refresh_token",
  "error_description": "Refresh token is expired or invalid",
  "status_code": 401
}
```

**When to Re-authenticate:**
- If refresh token is expired (after 7 days)
- If refresh token is revoked
- If client credentials have changed

In these cases, call `POST /v2/auth/token` with `client_id` and `client_secret` to obtain new tokens.

---

#### POST /v2/auth/token/revoke
**Revoke a refresh token (logout)**

```http
POST /v2/auth/token/revoke
Content-Type: application/json

{
  "refresh_token": "def456uvw..."
}
```

**Response (200 OK):**
```json
{
  "status": "revoked",
  "message": "Token successfully revoked"
}
```

---

### 3.2 Device APIs (V1 - Legacy)

> **SECURITY NOTICE:** V1 Device APIs currently use API Key authentication (`X-API-Key` header) for backwards compatibility. These endpoints are scheduled for deprecation. New integrations should use V2 APIs with JWT authentication where possible.
>
> **Migration Path:**
> - Use `POST /api/v1/devices/{id}/start-stream` to start streams (returns `v2_stream_id`)
> - Use V2 Stream APIs (`/v2/streams/*`) for all subsequent operations
> - V2 Device management APIs are planned for a future release

#### GET /api/v1/devices
**List all devices**

```http
GET /api/v1/devices?skip=0&limit=100
```

**Response (200 OK):**
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Front Door Camera",
    "description": "Main entrance camera",
    "rtsp_url": "rtsp://192.168.1.100:554/stream1",
    "is_active": false,
    "location": "Building A - Entrance",
    "created_at": "2026-01-10T08:00:00Z",
    "updated_at": null
  }
]
```

---

#### GET /api/v1/devices/{device_id}
**Get device details**

```http
GET /api/v1/devices/550e8400-e29b-41d4-a716-446655440000
```

**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Front Door Camera",
  "description": "Main entrance camera",
  "rtsp_url": "rtsp://192.168.1.100:554/stream1",
  "is_active": true,
  "location": "Building A - Entrance",
  "created_at": "2026-01-10T08:00:00Z",
  "updated_at": "2026-01-12T09:00:00Z"
}
```

---

#### POST /api/v1/devices
**Create a new device**

```http
POST /api/v1/devices
Content-Type: application/json

{
  "name": "Parking Lot Camera",
  "description": "Covers parking area B",
  "rtsp_url": "rtsp://192.168.1.101:554/stream1",
  "location": "Parking Lot B"
}
```

**Response (201 Created):**
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "name": "Parking Lot Camera",
  "description": "Covers parking area B",
  "rtsp_url": "rtsp://192.168.1.101:554/stream1",
  "is_active": false,
  "location": "Parking Lot B",
  "created_at": "2026-01-12T10:30:00Z",
  "updated_at": null
}
```

---

#### POST /api/v1/devices/{device_id}/start-stream
**Start streaming from a device**

This is the primary endpoint to initiate RTSP→WebRTC streaming.

```http
POST /api/v1/devices/550e8400-e29b-41d4-a716-446655440000/start-stream
```

**Response (200 OK):**
```json
{
  "status": "success",
  "device_id": "550e8400-e29b-41d4-a716-446655440000",
  "room_id": "550e8400-e29b-41d4-a716-446655440000",
  "transport_id": "transport-abc123",
  "producers": {
    "video": "producer-xyz789"
  },
  "stream": {
    "status": "started",
    "started_at": "2026-01-12T10:35:00Z"
  },
  "v2_stream_id": "770e8400-e29b-41d4-a716-446655440002"
}
```

**If stream already active (reconnect scenario):**
```json
{
  "status": "success",
  "device_id": "550e8400-e29b-41d4-a716-446655440000",
  "room_id": "550e8400-e29b-41d4-a716-446655440000",
  "transport_id": "transport-abc123",
  "producers": {
    "video": "producer-xyz789"
  },
  "stream": {
    "status": "active",
    "message": "Stream already running",
    "started_at": "2026-01-12T10:35:00Z"
  },
  "reconnect": true
}
```

---

#### POST /api/v1/devices/{device_id}/stop-stream
**Stop streaming from a device**

```http
POST /api/v1/devices/550e8400-e29b-41d4-a716-446655440000/stop-stream
```

**Response (200 OK):**
```json
{
  "status": "success",
  "device_id": "550e8400-e29b-41d4-a716-446655440000",
  "stopped": true
}
```

---

#### GET /api/v1/devices/{device_id}/status
**Get device status including streaming state**

```http
GET /api/v1/devices/550e8400-e29b-41d4-a716-446655440000/status
```

**Response (200 OK):**
```json
{
  "device_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Front Door Camera",
  "description": "Main entrance camera",
  "location": "Building A - Entrance",
  "rtsp_url": "rtsp://192.168.1.100:554/stream1",
  "is_active": true,
  "created_at": "2026-01-10T08:00:00Z",
  "updated_at": "2026-01-12T09:00:00Z",
  "streaming": {
    "active": true,
    "room_id": "550e8400-e29b-41d4-a716-446655440000",
    "started_at": "2026-01-12T10:35:00Z"
  }
}
```

---

#### POST /api/v1/devices/validate
**Validate RTSP URL without saving device**

```http
POST /api/v1/devices/validate
Content-Type: application/json

{
  "name": "Test Camera",
  "rtsp_url": "rtsp://192.168.1.102:554/stream1"
}
```

**Response (200 OK - Valid):**
```json
{
  "valid": true,
  "rtsp_url": "rtsp://192.168.1.102:554/stream1",
  "ssrc": 1234567890,
  "message": "Device validated successfully"
}
```

**Response (200 OK - Invalid):**
```json
{
  "valid": false,
  "error": "Failed to connect to RTSP stream or stream has no video",
  "rtsp_url": "rtsp://192.168.1.102:554/stream1"
}
```

---

### 3.3 Stream APIs (V2)

#### GET /v2/streams
**List all streams with optional filtering**

```http
GET /v2/streams?state=LIVE&limit=50&offset=0
Authorization: Bearer <access_token>
```

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `state` | string | Filter by state: LIVE, READY, ERROR, STOPPED, INITIALIZING, CLOSED |
| `camera_id` | UUID | Filter by camera/device ID |
| `limit` | int | Max results (1-100, default 50) |
| `offset` | int | Pagination offset |

**Response (200 OK):**
```json
{
  "streams": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440002",
      "name": "Front Door Camera",
      "camera_id": "550e8400-e29b-41d4-a716-446655440000",
      "state": "LIVE",
      "endpoints": {
        "webrtc": "/v2/streams/770e8400.../consume",
        "hls": "/v2/streams/770e8400.../hls",
        "health": "/v2/streams/770e8400.../health"
      },
      "created_at": "2026-01-12T10:35:00Z"
    }
  ],
  "pagination": {
    "total": 1,
    "limit": 50,
    "offset": 0
  }
}
```

---

#### GET /v2/streams/{stream_id}
**Get detailed stream information**

```http
GET /v2/streams/770e8400-e29b-41d4-a716-446655440002
Authorization: Bearer <access_token>
```

**Response (200 OK):**
```json
{
  "id": "770e8400-e29b-41d4-a716-446655440002",
  "name": "Front Door Camera",
  "camera_id": "550e8400-e29b-41d4-a716-446655440000",
  "state": "LIVE",
  "codec_config": {
    "video": {
      "codec": "H264",
      "profile": "42e01f",
      "payloadType": 96
    }
  },
  "producer": {
    "id": "880e8400-e29b-41d4-a716-446655440003",
    "mediasoup_id": "producer-xyz789",
    "state": "ACTIVE",
    "ssrc": 1234567890
  },
  "consumers": {
    "count": 2,
    "active": 2
  },
  "endpoints": {
    "webrtc": "/v2/streams/770e8400.../consume",
    "hls": "/v2/streams/770e8400.../hls",
    "health": "/v2/streams/770e8400.../health"
  },
  "created_at": "2026-01-12T10:35:00Z",
  "uptime_seconds": 1800
}
```

---

#### GET /v2/streams/{stream_id}/health
**Get stream health metrics**

```http
GET /v2/streams/770e8400-e29b-41d4-a716-446655440002/health
Authorization: Bearer <access_token>
```

**Response (200 OK):**
```json
{
  "stream_id": "770e8400-e29b-41d4-a716-446655440002",
  "state": "LIVE",
  "is_healthy": true,
  "uptime_seconds": 1800,
  "metrics": {
    "bitrate_kbps": 2500,
    "fps": 30,
    "packet_loss": 0.0,
    "jitter_ms": 2.5
  },
  "last_error": null,
  "checked_at": "2026-01-12T11:05:00Z"
}
```

---

#### GET /v2/streams/{stream_id}/router-capabilities
**Get MediaSoup router RTP capabilities**

Required before attaching a consumer. The client needs these capabilities to initialize the mediasoup-client Device.

```http
GET /v2/streams/770e8400-e29b-41d4-a716-446655440002/router-capabilities
Authorization: Bearer <access_token>
```

**Response (200 OK):**
```json
{
  "rtp_capabilities": {
    "codecs": [
      {
        "mimeType": "video/H264",
        "kind": "video",
        "clockRate": 90000,
        "parameters": {
          "packetization-mode": 1,
          "profile-level-id": "42e01f"
        },
        "rtcpFeedback": [
          { "type": "nack" },
          { "type": "nack", "parameter": "pli" },
          { "type": "goog-remb" }
        ]
      }
    ],
    "headerExtensions": [...]
  }
}
```

---

#### DELETE /v2/streams/{stream_id}
**Stop and delete a stream**

```http
DELETE /v2/streams/770e8400-e29b-41d4-a716-446655440002
Authorization: Bearer <access_token>
```

**Response (204 No Content)**

---

### 3.4 WebRTC Consumer APIs

#### POST /v2/streams/{stream_id}/consume
**Attach a WebRTC consumer to a live stream**

This is the primary endpoint for Ruth AI to start receiving WebRTC video.

```http
POST /v2/streams/770e8400-e29b-41d4-a716-446655440002/consume
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "client_id": "ruth-ai-instance-1",
  "rtp_capabilities": {
    "codecs": [
      {
        "mimeType": "video/H264",
        "kind": "video",
        "clockRate": 90000,
        "parameters": {
          "packetization-mode": 1,
          "profile-level-id": "42e01f"
        }
      }
    ],
    "headerExtensions": [...]
  }
}
```

**Response (201 Created):**
```json
{
  "consumer_id": "990e8400-e29b-41d4-a716-446655440004",
  "transport": {
    "id": "transport-consumer-abc123",
    "ice_parameters": {
      "usernameFragment": "abc123",
      "password": "xyz789..."
    },
    "ice_candidates": [
      {
        "foundation": "udpcandidate",
        "priority": 1076302079,
        "ip": "192.168.1.50",
        "port": 40000,
        "type": "host",
        "protocol": "udp"
      }
    ],
    "dtls_parameters": {
      "role": "auto",
      "fingerprints": [
        {
          "algorithm": "sha-256",
          "value": "AB:CD:EF:..."
        }
      ]
    }
  },
  "rtp_parameters": {
    "codecs": [...],
    "encodings": [
      {
        "ssrc": 987654321
      }
    ]
  }
}
```

---

#### POST /v2/streams/{stream_id}/consumers/{consumer_id}/connect
**Complete DTLS handshake**

After creating the local transport, send DTLS parameters to complete the connection.

```http
POST /v2/streams/770e8400.../consumers/990e8400.../connect
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "dtls_parameters": {
    "role": "client",
    "fingerprints": [
      {
        "algorithm": "sha-256",
        "value": "12:34:56:..."
      }
    ]
  }
}
```

**Response (200 OK):**
```json
{
  "status": "connected",
  "consumer_id": "990e8400-e29b-41d4-a716-446655440004",
  "transport_id": "transport-consumer-abc123"
}
```

---

#### POST /v2/streams/{stream_id}/consumers/{consumer_id}/ice-candidate
**Add ICE candidate (optional)**

```http
POST /v2/streams/770e8400.../consumers/990e8400.../ice-candidate
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "candidate": {
    "candidate": "candidate:...",
    "sdpMLineIndex": 0,
    "sdpMid": "0"
  }
}
```

**Response (200 OK):**
```json
{
  "status": "acknowledged",
  "consumer_id": "990e8400-e29b-41d4-a716-446655440004"
}
```

---

#### GET /v2/streams/{stream_id}/consumers
**List all consumers for a stream**

```http
GET /v2/streams/770e8400-e29b-41d4-a716-446655440002/consumers
Authorization: Bearer <access_token>
```

**Response (200 OK):**
```json
{
  "stream_id": "770e8400-e29b-41d4-a716-446655440002",
  "total_consumers": 2,
  "active_consumers": 2,
  "consumers": [
    {
      "id": "990e8400-e29b-41d4-a716-446655440004",
      "client_id": "ruth-ai-instance-1",
      "state": "CONNECTED",
      "created_at": "2026-01-12T10:40:00Z",
      "last_seen_at": "2026-01-12T11:10:00Z",
      "closed_at": null
    }
  ]
}
```

---

#### DELETE /v2/streams/{stream_id}/consumers/{consumer_id}
**Detach and close a consumer**

```http
DELETE /v2/streams/770e8400.../consumers/990e8400...
Authorization: Bearer <access_token>
```

**Response (204 No Content)**

---

### 3.5 HLS Playback APIs

#### GET /v2/streams/{stream_id}/hls/playlist.m3u8
**Get HLS playlist for stream**

```http
GET /v2/streams/770e8400.../hls/playlist.m3u8
Authorization: Bearer <access_token>
```

**Response (200 OK):**
```
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:6.000000,
stream0.ts
#EXTINF:6.000000,
stream1.ts
...
```

---

#### GET /v2/streams/{stream_id}/hls/{segment_name}
**Get HLS segment**

```http
GET /v2/streams/770e8400.../hls/stream0.ts
Authorization: Bearer <access_token>
```

**Response (200 OK):** Binary video segment (video/mp2t)

---

### 3.6 Snapshot APIs

#### POST /v2/streams/{stream_id}/snapshots
**Create a snapshot**

```http
POST /v2/streams/770e8400.../snapshots
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "source": "live",
  "created_by": "ruth-ai",
  "metadata": {
    "detection_type": "person",
    "confidence": 0.95
  }
}
```

For historical snapshots:
```json
{
  "source": "historical",
  "timestamp": "2026-01-12T10:45:00Z",
  "created_by": "ruth-ai"
}
```

**Response (201 Created):**
```json
{
  "id": "aa0e8400-e29b-41d4-a716-446655440005",
  "stream_id": "770e8400-e29b-41d4-a716-446655440002",
  "timestamp": "2026-01-12T11:00:00Z",
  "source": "live",
  "created_by": "ruth-ai",
  "format": "jpg",
  "file_size": null,
  "width": null,
  "height": null,
  "image_url": "/v2/snapshots/aa0e8400.../image",
  "metadata": {
    "detection_type": "person",
    "confidence": 0.95
  },
  "created_at": "2026-01-12T11:00:00Z"
}
```

---

#### GET /v2/snapshots
**List all snapshots with filtering**

```http
GET /v2/snapshots?stream_id=770e8400...&created_by=ruth-ai&limit=50
Authorization: Bearer <access_token>
```

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `stream_id` | UUID | Filter by stream |
| `created_by` | string | Filter by creator |
| `source` | string | Filter by source (live/historical) |
| `after` | datetime | Snapshots after this time |
| `before` | datetime | Snapshots before this time |
| `limit` | int | Max results (1-100) |
| `offset` | int | Pagination offset |

---

#### GET /v2/snapshots/{snapshot_id}
**Get snapshot details**

```http
GET /v2/snapshots/aa0e8400-e29b-41d4-a716-446655440005
Authorization: Bearer <access_token>
```

---

#### GET /v2/snapshots/{snapshot_id}/image
**Download snapshot image**

```http
GET /v2/snapshots/aa0e8400.../image
Authorization: Bearer <access_token>
```

**Response (200 OK):** Binary image (image/jpeg)

---

#### DELETE /v2/snapshots/{snapshot_id}
**Delete a snapshot**

```http
DELETE /v2/snapshots/aa0e8400-e29b-41d4-a716-446655440005
Authorization: Bearer <access_token>
```

**Response (204 No Content)**

---

### 3.7 Bookmark APIs

#### POST /v2/streams/{stream_id}/bookmarks
**Create a bookmark (video clip)**

```http
POST /v2/streams/770e8400.../bookmarks
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "source": "live",
  "label": "Person detected at entrance",
  "event_type": "person_detected",
  "confidence": 0.92,
  "before_seconds": 5,
  "after_seconds": 10,
  "tags": ["security", "entrance"],
  "created_by": "ruth-ai",
  "metadata": {
    "bounding_box": {"x": 100, "y": 150, "w": 200, "h": 400}
  }
}
```

For historical bookmarks:
```json
{
  "source": "historical",
  "center_timestamp": "2026-01-12T10:30:00Z",
  "before_seconds": 10,
  "after_seconds": 10,
  "label": "Reviewed incident",
  "event_type": "anomaly"
}
```

**Response (201 Created):**
```json
{
  "id": "bb0e8400-e29b-41d4-a716-446655440006",
  "stream_id": "770e8400-e29b-41d4-a716-446655440002",
  "center_timestamp": "2026-01-12T11:15:00Z",
  "start_time": "2026-01-12T11:14:55Z",
  "end_time": "2026-01-12T11:15:10Z",
  "duration_seconds": 15.0,
  "source": "live",
  "label": "Person detected at entrance",
  "created_by": "ruth-ai",
  "event_type": "person_detected",
  "confidence": 0.92,
  "tags": ["security", "entrance"],
  "video_url": null,
  "thumbnail_url": null,
  "status": "processing",
  "metadata": {...},
  "created_at": "2026-01-12T11:15:00Z"
}
```

---

#### GET /v2/bookmarks
**List all bookmarks with filtering**

```http
GET /v2/bookmarks?event_type=person_detected&created_by=ruth-ai&limit=50
Authorization: Bearer <access_token>
```

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `stream_id` | UUID | Filter by stream |
| `event_type` | string | Filter by event type |
| `created_by` | string | Filter by creator |
| `source` | string | Filter by source (live/historical) |
| `start_after` | datetime | Bookmarks starting after this time |
| `start_before` | datetime | Bookmarks starting before this time |
| `limit` | int | Max results (1-100) |
| `offset` | int | Pagination offset |

---

#### GET /v2/bookmarks/{bookmark_id}
**Get bookmark details**

---

#### GET /v2/bookmarks/{bookmark_id}/video
**Download bookmark video clip**

```http
GET /v2/bookmarks/bb0e8400.../video
Authorization: Bearer <access_token>
```

**Response (200 OK):** Binary video (video/mp4)

---

#### GET /v2/bookmarks/{bookmark_id}/thumbnail
**Get bookmark thumbnail**

```http
GET /v2/bookmarks/bb0e8400.../thumbnail
Authorization: Bearer <access_token>
```

**Response (200 OK):** Binary image (image/jpeg)

---

#### PUT /v2/bookmarks/{bookmark_id}
**Update bookmark metadata**

```http
PUT /v2/bookmarks/bb0e8400...
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "label": "Updated: Confirmed delivery person",
  "event_type": "delivery",
  "tags": ["delivery", "verified"]
}
```

---

#### DELETE /v2/bookmarks/{bookmark_id}
**Delete a bookmark**

```http
DELETE /v2/bookmarks/bb0e8400-e29b-41d4-a716-446655440006
Authorization: Bearer <access_token>
```

**Response (204 No Content)**

---

## 4. Stream State Machine

### 4.1 Stream States

VAS-MS-V2 manages stream lifecycle through a finite state machine. Understanding these states is critical for proper integration.

| State | Description | Can Attach Consumer? | Terminal? |
|-------|-------------|---------------------|-----------|
| `INITIALIZING` | Stream record created, setup in progress | No | No |
| `READY` | SSRC captured, producer created, waiting for media | No | No |
| `LIVE` | FFmpeg running, media actively flowing | **Yes** | No |
| `ERROR` | Failure occurred (recoverable) | No | No |
| `STOPPED` | Manually stopped by user/API | No | No |
| `CLOSED` | Cleanup complete, resources released | No | **Yes** |

### 4.2 State Transition Diagram

```
                              ┌─────────────────────────────────────────┐
                              │           STREAM STATE MACHINE          │
                              └─────────────────────────────────────────┘

    ┌──────────────┐     SSRC captured      ┌──────────────┐     FFmpeg started     ┌──────────────┐
    │              │ ───────────────────────>│              │ ───────────────────────>│              │
    │ INITIALIZING │                         │    READY     │                         │     LIVE     │
    │              │<───────────────────────│              │<───────────────────────│              │
    └──────────────┘     retry on failure    └──────────────┘     reconnect          └──────────────┘
           │                                        │                                       │
           │                                        │                                       │
           │ setup failed                           │ producer failed                       │ stop requested
           │                                        │                                       │
           ▼                                        ▼                                       ▼
    ┌──────────────┐                         ┌──────────────┐                        ┌──────────────┐
    │              │                         │              │                        │              │
    │    ERROR     │◄────────────────────────│    ERROR     │◄───────────────────────│   STOPPED    │
    │              │                         │              │                        │              │
    └──────────────┘                         └──────────────┘                        └──────────────┘
           │                                        │                                       │
           │ restart                                │ restart                               │ cleanup
           │ attempted                              │ attempted                             │ complete
           ▼                                        ▼                                       ▼
    ┌──────────────┐                         ┌──────────────┐                        ┌──────────────┐
    │              │                         │              │                        │              │
    │ INITIALIZING │                         │ INITIALIZING │                        │    CLOSED    │
    │              │                         │              │                        │  (terminal)  │
    └──────────────┘                         └──────────────┘                        └──────────────┘
```

### 4.3 Valid State Transitions

| From State | To State | Trigger | Notes |
|------------|----------|---------|-------|
| `INITIALIZING` | `READY` | SSRC captured successfully | Producer created in MediaSoup |
| `INITIALIZING` | `ERROR` | SSRC capture failed | RTSP connection issue or no video |
| `READY` | `LIVE` | FFmpeg started, media flowing | Consumers can now attach |
| `READY` | `ERROR` | FFmpeg failed to start | Check RTSP URL and camera status |
| `LIVE` | `STOPPED` | `stop-stream` API called | Graceful shutdown |
| `LIVE` | `ERROR` | FFmpeg crashed or RTSP disconnected | Automatic recovery attempted |
| `ERROR` | `INITIALIZING` | Automatic retry or manual restart | Up to 3 automatic retries |
| `ERROR` | `CLOSED` | Max retries exceeded or manual close | Terminal state |
| `STOPPED` | `INITIALIZING` | `start-stream` API called | Restart stream |
| `STOPPED` | `CLOSED` | Cleanup timeout (5 min) or explicit close | Terminal state |
| `*` | `CLOSED` | Stream deleted via API | Resources released |

### 4.4 State-Based API Behavior

| API Endpoint | INITIALIZING | READY | LIVE | ERROR | STOPPED | CLOSED |
|--------------|--------------|-------|------|-------|---------|--------|
| `GET /v2/streams/{id}` | ✓ | ✓ | ✓ | ✓ | ✓ | 404 |
| `POST /v2/streams/{id}/consume` | 409 | 409 | ✓ | 409 | 409 | 404 |
| `GET /v2/streams/{id}/health` | ✓ | ✓ | ✓ | ✓ | ✓ | 404 |
| `DELETE /v2/streams/{id}` | ✓ | ✓ | ✓ | ✓ | ✓ | 404 |
| `POST /devices/{id}/stop-stream` | ✓ | ✓ | ✓ | ✓ | 200 (no-op) | 404 |

### 4.5 Handling State in Client Code

```javascript
async function ensureStreamReady(streamId) {
  const maxWait = 30000; // 30 seconds
  const pollInterval = 1000; // 1 second
  const startTime = Date.now();

  while (Date.now() - startTime < maxWait) {
    const response = await fetch(`/v2/streams/${streamId}`, {
      headers: { 'Authorization': `Bearer ${accessToken}` }
    });

    if (!response.ok) {
      throw new Error(`Stream not found: ${response.status}`);
    }

    const stream = await response.json();

    switch (stream.state) {
      case 'LIVE':
        return stream; // Ready to consume

      case 'INITIALIZING':
      case 'READY':
        await sleep(pollInterval); // Wait and retry
        break;

      case 'ERROR':
        throw new Error(`Stream error: ${stream.last_error}`);

      case 'STOPPED':
        throw new Error('Stream is stopped');

      case 'CLOSED':
        throw new Error('Stream is closed');

      default:
        throw new Error(`Unknown state: ${stream.state}`);
    }
  }

  throw new Error('Timeout waiting for stream to become LIVE');
}
```

---

## 5. WebRTC Flow - Step by Step

### 5.1 Complete Connection Sequence

```
┌─────────────┐          ┌─────────────┐          ┌─────────────┐
│   Ruth AI   │          │  VAS-MS-V2  │          │  MediaSoup  │
│   Client    │          │   Backend   │          │    Server   │
└──────┬──────┘          └──────┬──────┘          └──────┬──────┘
       │                        │                        │
       │ 1. GET /devices        │                        │
       │───────────────────────>│                        │
       │        Device List     │                        │
       │<───────────────────────│                        │
       │                        │                        │
       │ 2. POST /devices/{id}/ │                        │
       │    start-stream        │                        │
       │───────────────────────>│                        │
       │                        │ Create Router          │
       │                        │───────────────────────>│
       │                        │ Create RTP Transport   │
       │                        │───────────────────────>│
       │                        │ [Capture SSRC]         │
       │                        │ Create Producer        │
       │                        │───────────────────────>│
       │                        │ [Start FFmpeg]         │
       │      Stream Info       │                        │
       │<───────────────────────│                        │
       │                        │                        │
       │ 3. GET /streams/{id}/  │                        │
       │    router-capabilities │                        │
       │───────────────────────>│                        │
       │                        │ getRouterRtpCapabilities
       │                        │───────────────────────>│
       │   RTP Capabilities     │                        │
       │<───────────────────────│                        │
       │                        │                        │
       │ [Load Device with      │                        │
       │  routerRtpCapabilities]│                        │
       │                        │                        │
       │ 4. POST /streams/{id}/ │                        │
       │    consume             │                        │
       │───────────────────────>│                        │
       │                        │ Create WebRTC Transport│
       │                        │───────────────────────>│
       │                        │ Create Consumer        │
       │                        │───────────────────────>│
       │  Transport Info +      │                        │
       │  RTP Parameters        │                        │
       │<───────────────────────│                        │
       │                        │                        │
       │ [Create RecvTransport  │                        │
       │  with server params]   │                        │
       │                        │                        │
       │ 5. POST /consumers/    │                        │
       │    {id}/connect        │                        │
       │   (DTLS parameters)    │                        │
       │───────────────────────>│                        │
       │                        │ connectWebRtcTransport │
       │                        │───────────────────────>│
       │     Connected          │                        │
       │<───────────────────────│                        │
       │                        │                        │
       │ [transport.consume()]  │                        │
       │                        │                        │
       │ 6. Media Track         │                        │
       │<═══════════════════════╪════════════════════════│
       │    (WebRTC RTP)        │                        │
       │                        │                        │
       │ [Attach to video       │                        │
       │  element / AI pipeline]│                        │
       │                        │                        │
```

### 5.2 Step-by-Step Instructions

#### Step 1: Discover Device

```javascript
// Fetch available devices
const response = await fetch('/api/v1/devices');
const devices = await response.json();

// Select device to stream
const device = devices.find(d => d.name === 'Front Door Camera');
```

#### Step 2: Start Stream

```javascript
// Start the stream (creates producer)
const startResponse = await fetch(
  `/api/v1/devices/${device.id}/start-stream`,
  { method: 'POST' }
);
const streamInfo = await startResponse.json();

// Check if already running (reconnect)
if (streamInfo.reconnect) {
  console.log('Reconnecting to existing stream');
}

const streamId = streamInfo.v2_stream_id;
```

#### Step 3: Get Router Capabilities

```javascript
// Get router RTP capabilities
const capResponse = await fetch(
  `/v2/streams/${streamId}/router-capabilities`,
  {
    headers: { 'Authorization': `Bearer ${accessToken}` }
  }
);
const { rtp_capabilities } = await capResponse.json();

// Initialize mediasoup Device
import { Device } from 'mediasoup-client';

const msDevice = new Device();
await msDevice.load({ routerRtpCapabilities: rtp_capabilities });
```

#### Step 4: Attach Consumer

```javascript
// Request consumer attachment
const consumeResponse = await fetch(
  `/v2/streams/${streamId}/consume`,
  {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${accessToken}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      client_id: 'ruth-ai-instance-1',
      rtp_capabilities: msDevice.rtpCapabilities
    })
  }
);
const consumerData = await consumeResponse.json();
```

#### Step 5: Create Transport and Connect

```javascript
// Create receive transport
const transport = msDevice.createRecvTransport({
  id: consumerData.transport.id,
  iceParameters: consumerData.transport.ice_parameters,
  iceCandidates: consumerData.transport.ice_candidates,
  dtlsParameters: consumerData.transport.dtls_parameters
});

// Handle connect event (DTLS handshake)
transport.on('connect', async ({ dtlsParameters }, callback, errback) => {
  try {
    await fetch(
      `/v2/streams/${streamId}/consumers/${consumerData.consumer_id}/connect`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ dtls_parameters: dtlsParameters })
      }
    );
    callback();
  } catch (error) {
    errback(error);
  }
});
```

#### Step 6: Consume Media

```javascript
// Create consumer
const consumer = await transport.consume({
  id: consumerData.consumer_id,
  producerId: streamInfo.producers.video,
  kind: 'video',
  rtpParameters: consumerData.rtp_parameters
});

// Resume consumer
await consumer.resume();

// Attach to video element
const videoElement = document.getElementById('video');
const mediaStream = new MediaStream([consumer.track]);
videoElement.srcObject = mediaStream;
await videoElement.play();
```

#### Step 7: Monitor Stream Health (Optional)

```javascript
// Periodic health check
setInterval(async () => {
  const healthResponse = await fetch(
    `/v2/streams/${streamId}/health`,
    { headers: { 'Authorization': `Bearer ${accessToken}` }}
  );
  const health = await healthResponse.json();

  if (!health.is_healthy) {
    console.warn('Stream unhealthy:', health.last_error);
    // Consider reconnecting
  }
}, 30000); // Every 30 seconds
```

#### Step 8: Graceful Disconnect

```javascript
// When done, detach consumer
await fetch(
  `/v2/streams/${streamId}/consumers/${consumerData.consumer_id}`,
  {
    method: 'DELETE',
    headers: { 'Authorization': `Bearer ${accessToken}` }
  }
);

// Close local resources
consumer.close();
transport.close();
```

### 5.3 Signaling Direction Summary

| Direction | Data | Endpoint |
|-----------|------|----------|
| Client → Server | Start stream request | `POST /devices/{id}/start-stream` |
| Server → Client | Stream info + producer ID | Response |
| Client → Server | Request router capabilities | `GET /streams/{id}/router-capabilities` |
| Server → Client | RTP capabilities | Response |
| Client → Server | Consumer attach + RTP caps | `POST /streams/{id}/consume` |
| Server → Client | Transport info + RTP params | Response |
| Client → Server | DTLS parameters | `POST /consumers/{id}/connect` |
| Server → Client | Connection confirmed | Response |
| Server → Client | **Media stream** | WebRTC (direct) |

### 5.4 State Ownership

| State | Owner | Persistence |
|-------|-------|-------------|
| Stream state (LIVE, STOPPED, etc.) | VAS-MS-V2 | Database |
| Producer | VAS-MS-V2 | Database + MediaSoup |
| Consumer | VAS-MS-V2 | Database + MediaSoup |
| RTCPeerConnection | Ruth AI | Memory (client-side) |
| MediaStream / Tracks | Ruth AI | Memory (client-side) |
| mediasoup Device | Ruth AI | Memory (client-side) |

### 5.5 Retry and Timeout Expectations

| Operation | Timeout | Retry Strategy |
|-----------|---------|----------------|
| Start stream | 30s | Retry 2x with 5s delay |
| SSRC capture | 15s | Part of start-stream |
| Consumer attach | 10s | Retry 3x with 2s delay |
| DTLS connect | 10s | Retry 2x with 2s delay |
| Health check | 5s | Skip on timeout, try next interval |
| Stream recovery | - | Re-attach consumer, don't restart stream |

---

## 6. Ruth AI Integration Patterns

### 6.1 One Stream Per Device vs Shared Streams

**VAS-MS-V2 uses a shared stream model:**

```
┌──────────────────────────────────────────────────────────────────┐
│                     SHARED STREAM PATTERN                         │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Device ──> 1 Producer ──> N Consumers                           │
│                                                                  │
│  - One FFmpeg process per device                                 │
│  - One MediaSoup producer per stream                             │
│  - Multiple consumers can attach to same producer                │
│  - Starting an already-running stream returns existing info      │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Best Practice:**
1. Check stream status before starting
2. If stream is already LIVE, attach consumer directly
3. Don't call start-stream if status shows active

```javascript
// Check status first
const statusResponse = await fetch(`/api/v1/devices/${deviceId}/status`);
const status = await statusResponse.json();

if (status.streaming.active) {
  // Stream already running - just attach consumer
  console.log('Stream already active, attaching...');
} else {
  // Start the stream
  await fetch(`/api/v1/devices/${deviceId}/start-stream`, { method: 'POST' });
}
```

### 6.2 Avoiding Duplicate Stream Starts

**VAS-MS-V2 handles this automatically:**
- If stream is already active, `start-stream` returns existing stream info
- Response includes `reconnect: true` flag

**However, Ruth AI should:**
1. Track which streams are currently connected
2. Use local state to avoid redundant API calls
3. Handle `reconnect: true` response gracefully

```javascript
class StreamManager {
  constructor() {
    this.activeStreams = new Map();
  }

  async ensureStreamStarted(deviceId) {
    if (this.activeStreams.has(deviceId)) {
      return this.activeStreams.get(deviceId);
    }

    const response = await fetch(`/api/v1/devices/${deviceId}/start-stream`, {
      method: 'POST'
    });
    const streamInfo = await response.json();

    this.activeStreams.set(deviceId, streamInfo);
    return streamInfo;
  }

  markStopped(deviceId) {
    this.activeStreams.delete(deviceId);
  }
}
```

### 6.3 Handling Multiple Viewers

**Scenario:** Multiple Ruth AI instances or UI panels viewing the same stream.

**Pattern:**
- Each viewer creates their own consumer
- All consumers share the same producer
- Server tracks consumer count per stream

```javascript
// Each viewer instance
const consumeResponse = await fetch(`/v2/streams/${streamId}/consume`, {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${accessToken}` },
  body: JSON.stringify({
    client_id: `ruth-ai-viewer-${viewerId}`,  // Unique per viewer
    rtp_capabilities: device.rtpCapabilities
  })
});
```

### 6.4 AI Pipeline Consumption

**For AI processing, Ruth AI can:**

1. **Browser-based (Canvas extraction):**
```javascript
const canvas = document.createElement('canvas');
const ctx = canvas.getContext('2d');

function captureFrame() {
  ctx.drawImage(videoElement, 0, 0);
  return canvas.toDataURL('image/jpeg');
}

// Process frames
setInterval(() => {
  const frameData = captureFrame();
  sendToAIPipeline(frameData);
}, 100); // 10 FPS to AI
```

2. **Server-side (Direct media processing):**
```javascript
// Use mediasoup in Node.js
const { createWorker } = require('mediasoup');

// Get raw RTP packets via DirectTransport
// Decode H.264 frames with FFmpeg bindings
```

3. **Use HLS for batch processing:**
```javascript
// For historical analysis, use HLS segments
const playlist = await fetch(`/v2/streams/${streamId}/hls/playlist.m3u8`);
// Download and process .ts segments
```

### 6.5 Failure Handling

#### RTSP Camera Offline

```javascript
// Monitor stream health
const health = await fetchHealth(streamId);

if (!health.is_healthy && health.last_error?.includes('RTSP')) {
  // Camera is offline
  // 1. Notify user/system
  // 2. Queue for retry
  // 3. Don't repeatedly call start-stream

  scheduleRetry(deviceId, 60000); // Retry in 1 minute
}
```

#### Stream Crash Recovery

```javascript
// If consumer disconnects unexpectedly
transport.on('connectionstatechange', (state) => {
  if (state === 'disconnected' || state === 'failed') {
    // Don't restart stream, just re-attach consumer
    reconnectConsumer(streamId);
  }
});

async function reconnectConsumer(streamId) {
  // Check if stream is still LIVE
  const stream = await fetchStream(streamId);

  if (stream.state === 'LIVE') {
    // Re-attach consumer
    await attachConsumer(streamId);
  } else {
    // Stream died - need to restart
    await startStream(deviceId);
  }
}
```

#### WebRTC Connection Failure

```javascript
async function handleConnectionFailure(error) {
  if (error.message.includes('ICE')) {
    // Network issue - retry with backoff
    await retryWithBackoff(() => attachConsumer(streamId), 3, 2000);
  } else if (error.message.includes('DTLS')) {
    // Handshake failure - may need to restart
    await detachConsumer(consumerId);
    await attachConsumer(streamId);
  }
}
```

---

## 7. Error Handling & Contracts

### 7.1 HTTP Status Code Semantics

| Code | Meaning | Ruth AI Action |
|------|---------|----------------|
| `200 OK` | Success | Process response |
| `201 Created` | Resource created | Process response, track new ID |
| `204 No Content` | Deleted/Updated | Update local state |
| `400 Bad Request` | Invalid input | Fix request, show user error |
| `401 Unauthorized` | Token invalid/expired | Refresh token, retry |
| `403 Forbidden` | Insufficient scope | Show permission error, don't retry |
| `404 Not Found` | Resource doesn't exist | Update UI, don't retry |
| `409 Conflict` | State conflict | Check current state, adjust |
| `500 Internal Server Error` | Server bug | Retry 1-2x, then show error |
| `502 Bad Gateway` | RTSP/external failure | Retry with backoff |
| `503 Service Unavailable` | MediaSoup down | Retry later |
| `504 Gateway Timeout` | RTSP timeout | Check camera, retry later |

### 7.2 Standardized Error Response Format

All VAS-MS-V2 API endpoints return errors in a consistent format to enable programmatic error handling.

#### Standard Error Schema

```json
{
  "error": "ERROR_CODE",
  "error_description": "Human-readable error message",
  "status_code": 400,
  "details": {
    "field": "Additional context (optional)"
  },
  "request_id": "req_abc123xyz",
  "timestamp": "2026-01-12T11:00:00Z"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `error` | string | Yes | Machine-readable error code (SCREAMING_SNAKE_CASE) |
| `error_description` | string | Yes | Human-readable message for display |
| `status_code` | integer | Yes | HTTP status code (matches response status) |
| `details` | object | No | Additional context (field errors, constraints, etc.) |
| `request_id` | string | No | Unique request ID for debugging/support |
| `timestamp` | string | No | ISO 8601 timestamp of error occurrence |

#### Validation Error (400 Bad Request)

```json
{
  "error": "VALIDATION_ERROR",
  "error_description": "Request validation failed",
  "status_code": 400,
  "details": {
    "rtsp_url": "Invalid RTSP URL format",
    "name": "Field is required"
  },
  "request_id": "req_abc123xyz"
}
```

#### Authentication Error (401 Unauthorized)

```json
{
  "error": "INVALID_TOKEN",
  "error_description": "Access token is expired or invalid",
  "status_code": 401,
  "request_id": "req_abc123xyz"
}
```

#### Stream Operation Error (502 Bad Gateway)

```json
{
  "error": "SSRC_CAPTURE_FAILED",
  "error_description": "Failed to capture SSRC from RTSP source",
  "status_code": 502,
  "details": {
    "rtsp_url": "rtsp://192.168.1.100:554/stream1",
    "timeout_seconds": 15,
    "reason": "Connection refused"
  },
  "request_id": "req_abc123xyz"
}
```

#### Conflict Error (409 Conflict)

```json
{
  "error": "STREAM_NOT_LIVE",
  "error_description": "Cannot attach consumer: stream is not in LIVE state",
  "status_code": 409,
  "details": {
    "stream_id": "770e8400-e29b-41d4-a716-446655440002",
    "current_state": "INITIALIZING",
    "required_state": "LIVE"
  },
  "request_id": "req_abc123xyz"
}
```

#### Parsing Errors Programmatically

```javascript
async function handleApiError(response) {
  const error = await response.json();

  switch (error.error) {
    case 'INVALID_TOKEN':
    case 'TOKEN_EXPIRED':
      await refreshToken();
      return { retry: true };

    case 'STREAM_NOT_LIVE':
      // Wait for stream to be ready
      await waitForStreamLive(error.details.stream_id);
      return { retry: true };

    case 'SSRC_CAPTURE_FAILED':
    case 'RTSP_CONNECTION_FAILED':
      // Camera issue - notify user
      showError(`Camera unavailable: ${error.error_description}`);
      return { retry: false, userAction: true };

    case 'VALIDATION_ERROR':
      // Show field-specific errors
      showValidationErrors(error.details);
      return { retry: false };

    default:
      console.error(`Unhandled error: ${error.error}`, error);
      return { retry: false };
  }
}
```

### 7.3 Error Codes Reference

| Error Code | HTTP Status | Meaning |
|------------|-------------|---------|
| `MEDIASOUP_UNAVAILABLE` | 503 | MediaSoup server not running |
| `RTSP_TIMEOUT` | 504 | Camera not responding |
| `SSRC_CAPTURE_FAILED` | 502 | Camera stream has no video |
| `RTSP_CONNECTION_FAILED` | 502 | Invalid RTSP URL or network issue |
| `MEDIASOUP_ERROR` | 503 | MediaSoup internal error |
| `FFMPEG_ERROR` | 500 | Transcoding failure |
| `STREAM_START_FAILED` | 500 | Generic stream start failure |
| `STREAM_STOP_FAILED` | 500 | Generic stream stop failure |

### 7.4 Retry Decision Matrix

| Error Type | Retry? | Max Retries | Backoff |
|------------|--------|-------------|---------|
| 401 Unauthorized | Yes (with refresh) | 1 | None |
| 403 Forbidden | No | - | - |
| 404 Not Found | No | - | - |
| 500 Server Error | Yes | 2 | 2s, 5s |
| 502 Bad Gateway | Yes | 3 | 5s, 10s, 30s |
| 503 Unavailable | Yes | 3 | 10s, 30s, 60s |
| 504 Timeout | Yes | 2 | 30s, 60s |
| Network Error | Yes | 3 | 2s, 5s, 10s |
| WebRTC ICE Failure | Yes | 2 | 2s |
| WebRTC DTLS Failure | Yes | 1 | 2s |

### 7.5 Which Errors Require User Action

| Error | Required Action |
|-------|-----------------|
| 403 Forbidden | Contact admin for permissions |
| 404 Device Not Found | Re-check device configuration |
| RTSP_CONNECTION_FAILED | Verify camera IP/port/credentials |
| SSRC_CAPTURE_FAILED | Check if camera is producing video |
| Repeated 502/503 | Check infrastructure status |

### 7.6 Fatal Errors (Don't Retry)

- `403 Forbidden` - Missing permissions
- `404 Not Found` - Resource deleted
- Invalid client credentials (after refresh attempt)
- Schema validation errors (400)

---

## 8. Async Processing (Bookmarks & Snapshots)

### 8.1 Understanding Async Resource Creation

When you create a **bookmark** or **snapshot**, the API returns immediately with a resource record, but the actual media file (video clip or image) is processed **asynchronously** in the background. This design allows:

- Fast API response times (< 500ms)
- Multiple concurrent capture requests
- Graceful handling of processing backlogs

### 8.2 Processing States

| Status | Description | Media Available? |
|--------|-------------|------------------|
| `processing` | Resource created, media being generated | No |
| `ready` | Processing complete, media available | **Yes** |
| `failed` | Processing failed (see `error` field) | No |

### 8.3 Async Flow Diagram

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    ASYNC BOOKMARK/SNAPSHOT CREATION                         │
└────────────────────────────────────────────────────────────────────────────┘

   Client                              VAS-MS-V2                    FFmpeg
     │                                    │                            │
     │ POST /streams/{id}/bookmarks       │                            │
     │ ─────────────────────────────────> │                            │
     │                                    │ Create DB record           │
     │                                    │ (status=processing)        │
     │                                    │                            │
     │ 201 Created                        │                            │
     │ { status: "processing" }           │                            │
     │ <───────────────────────────────── │                            │
     │                                    │                            │
     │                                    │ Queue extraction job       │
     │                                    │ ─────────────────────────> │
     │                                    │                            │
     │                                    │      [Extract video clip]  │
     │                                    │                            │
     │                                    │ Job complete               │
     │                                    │ <───────────────────────── │
     │                                    │                            │
     │                                    │ Update DB record           │
     │                                    │ (status=ready, video_url)  │
     │                                    │                            │
     │ GET /bookmarks/{id}                │                            │
     │ ─────────────────────────────────> │                            │
     │                                    │                            │
     │ 200 OK                             │                            │
     │ { status: "ready", video_url: ... }│                            │
     │ <───────────────────────────────── │                            │
     │                                    │                            │
     │ GET /bookmarks/{id}/video          │                            │
     │ ─────────────────────────────────> │                            │
     │                                    │                            │
     │ 200 OK (video/mp4)                 │                            │
     │ <───────────────────────────────── │                            │
     │                                    │                            │
```

### 8.4 Expected Processing Times

| Resource Type | Source | Typical Processing Time |
|---------------|--------|------------------------|
| Snapshot (live) | Live stream | 1-3 seconds |
| Snapshot (historical) | HLS recording | 2-5 seconds |
| Bookmark (live, 15s) | Live stream | 5-15 seconds |
| Bookmark (historical, 15s) | HLS recording | 3-10 seconds |
| Bookmark (historical, 60s) | HLS recording | 15-30 seconds |

### 8.5 Polling for Completion

**Recommended Approach: Poll with Exponential Backoff**

```javascript
async function waitForBookmarkReady(bookmarkId, maxWaitMs = 60000) {
  const startTime = Date.now();
  let pollInterval = 1000; // Start at 1 second
  const maxInterval = 5000; // Max 5 seconds between polls

  while (Date.now() - startTime < maxWaitMs) {
    const response = await fetch(`/v2/bookmarks/${bookmarkId}`, {
      headers: { 'Authorization': `Bearer ${accessToken}` }
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch bookmark: ${response.status}`);
    }

    const bookmark = await response.json();

    switch (bookmark.status) {
      case 'ready':
        return bookmark; // Success!

      case 'failed':
        throw new Error(`Bookmark processing failed: ${bookmark.error}`);

      case 'processing':
        // Wait and poll again
        await sleep(pollInterval);
        pollInterval = Math.min(pollInterval * 1.5, maxInterval);
        break;

      default:
        throw new Error(`Unknown status: ${bookmark.status}`);
    }
  }

  throw new Error('Timeout waiting for bookmark to be ready');
}
```

### 8.6 Handling Processing Failures

When processing fails, the resource will have:
- `status: "failed"`
- `error`: Error description

**Common Failure Reasons:**

| Error | Cause | Action |
|-------|-------|--------|
| `NO_RECORDING_DATA` | Historical data not available for requested time | Check retention period (7 days) |
| `EXTRACTION_TIMEOUT` | FFmpeg took too long | Retry or reduce duration |
| `DISK_FULL` | Storage exhausted | Contact admin |
| `STREAM_NOT_FOUND` | Stream was deleted during processing | Re-check stream exists |

```javascript
async function createBookmarkWithRetry(streamId, params, maxRetries = 2) {
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const bookmark = await createBookmark(streamId, params);

    try {
      return await waitForBookmarkReady(bookmark.id);
    } catch (error) {
      if (error.message.includes('EXTRACTION_TIMEOUT') && attempt < maxRetries) {
        console.log(`Retry ${attempt + 1}/${maxRetries}...`);
        continue;
      }
      throw error;
    }
  }
}
```

### 8.7 Best Practices

1. **Don't block on creation** - Return bookmark ID to user immediately, poll in background
2. **Show progress indicator** - Display "Processing..." while status is `processing`
3. **Handle failures gracefully** - Show error message, offer retry option
4. **Set reasonable timeouts** - 60s for short clips, 120s for longer bookmarks
5. **Batch create, then poll** - Create multiple bookmarks, then poll for all

```javascript
// Create multiple bookmarks in parallel
const bookmarkPromises = events.map(event =>
  createBookmark(streamId, {
    source: 'live',
    label: event.label,
    center_timestamp: event.timestamp
  })
);

const bookmarks = await Promise.all(bookmarkPromises);

// Poll for all to complete
const readyBookmarks = await Promise.all(
  bookmarks.map(b => waitForBookmarkReady(b.id))
);
```

### 8.8 Snapshot-Specific Notes

Snapshots follow the same async pattern but are typically faster:

```javascript
// Create snapshot
const snapshot = await fetch(`/v2/streams/${streamId}/snapshots`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${accessToken}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    source: 'live',
    metadata: { detection_type: 'person', confidence: 0.95 }
  })
}).then(r => r.json());

// For live snapshots, image is usually ready within 2 seconds
await sleep(2000);

// Check if ready
const ready = await fetch(`/v2/snapshots/${snapshot.id}`, {
  headers: { 'Authorization': `Bearer ${accessToken}` }
}).then(r => r.json());

if (ready.status === 'ready') {
  // Download image
  const imageUrl = await getSnapshotImageUrl(snapshot.id);
  displayImage(imageUrl);
}
```

---

## 9. What Ruth AI MUST NOT Do

### 9.1 Anti-Patterns to Avoid

#### DO NOT: Bypass VAS APIs

```javascript
// BAD: Direct RTSP connection
const rtspStream = ffmpeg('rtsp://camera-ip/stream');

// BAD: Direct MediaSoup connection
const socket = new WebSocket('ws://mediasoup:3001');

// GOOD: Use VAS-MS-V2 APIs
const stream = await fetch('/api/v1/devices/{id}/start-stream', { method: 'POST' });
```

#### DO NOT: Re-implement RTSP Handling

VAS-MS-V2 handles:
- RTSP connection management
- SSRC capture
- FFmpeg process lifecycle
- RTP packet routing

Ruth AI should **never**:
- Parse RTSP URLs for direct connection
- Manage FFmpeg processes
- Handle RTP packets directly

#### DO NOT: Hold WebRTC State Incorrectly

```javascript
// BAD: Storing transport across sessions
localStorage.setItem('transport', JSON.stringify(transportInfo));

// BAD: Reusing stale consumer IDs
const oldConsumerId = localStorage.getItem('consumerId');
await fetch(`/consumers/${oldConsumerId}/connect`); // WILL FAIL

// GOOD: Fresh consumer on each session
const consumeResponse = await fetch('/streams/{id}/consume', { method: 'POST' });
```

#### DO NOT: Assume Streams Are Always On

```javascript
// BAD: Skip status check
await attachConsumer(streamId);

// GOOD: Check state first
const stream = await fetch(`/v2/streams/${streamId}`);
if (stream.state !== 'LIVE') {
  await startStream(deviceId);
}
await attachConsumer(streamId);
```

#### DO NOT: Hardcode Internal VAS Behavior

```javascript
// BAD: Hardcoded ports
const mediasoupPort = 40000;

// BAD: Assumed recording paths
const hlsPath = `/recordings/hot/${deviceId}/stream.m3u8`;

// BAD: Hardcoded timeouts
const ssrcTimeout = 15000;

// GOOD: Use API responses
const { endpoints } = await fetch(`/v2/streams/${streamId}`);
const playlist = await fetch(endpoints.hls);
```

#### DO NOT: Ignore Consumer Lifecycle

```javascript
// BAD: Abandon consumers without cleanup
function switchCamera(newDeviceId) {
  // Old consumer left dangling!
  startNewStream(newDeviceId);
}

// GOOD: Clean up before switching
async function switchCamera(newDeviceId) {
  // Detach old consumer
  await fetch(`/streams/${oldStreamId}/consumers/${consumerId}`, {
    method: 'DELETE'
  });
  consumer.close();
  transport.close();

  // Start new stream
  await startNewStream(newDeviceId);
}
```

#### DO NOT: Flood Start/Stop Requests

```javascript
// BAD: No debouncing
button.onclick = () => fetch('/devices/{id}/start-stream', { method: 'POST' });

// GOOD: Debounce and track state
let isStarting = false;
button.onclick = async () => {
  if (isStarting) return;
  isStarting = true;
  try {
    await fetch('/devices/{id}/start-stream', { method: 'POST' });
  } finally {
    isStarting = false;
  }
};
```

#### DO NOT: Store Tokens Insecurely

```javascript
// BAD: Token in localStorage (XSS vulnerable)
localStorage.setItem('token', accessToken);

// BAD: Token in URL
fetch(`/v2/streams?token=${accessToken}`);

// GOOD: HTTP-only cookies or secure memory
// Token in Authorization header only
```

### 9.2 Summary of Anti-Patterns

| Anti-Pattern | Why It's Bad | Correct Approach |
|--------------|--------------|------------------|
| Direct RTSP connection | Duplicates VAS functionality, no WebRTC | Use VAS APIs |
| Direct MediaSoup connection | Bypasses auth and state management | Use VAS consumer APIs |
| Storing WebRTC state | State becomes stale, causes failures | Fresh state each session |
| Assuming stream is on | Causes consumer attach failures | Check state first |
| Hardcoded paths/ports | Breaks on config changes | Use API responses |
| Abandoned consumers | Resource leak, inaccurate metrics | Always cleanup |
| Request flooding | Overloads server, causes conflicts | Debounce and track |
| Insecure token storage | Security vulnerability | Use secure storage |

---

## 10. Final Summary

### 10.1 How to Integrate VAS-MS-V2 in 10 Steps

1. **Register client** - Get `client_id` and `client_secret` from admin
2. **Obtain tokens** - POST to `/v2/auth/token` with credentials
3. **Discover devices** - GET `/api/v1/devices` to list cameras
4. **Start stream** - POST `/api/v1/devices/{id}/start-stream`
5. **Get capabilities** - GET `/v2/streams/{id}/router-capabilities`
6. **Load Device** - `device.load({ routerRtpCapabilities })`
7. **Attach consumer** - POST `/v2/streams/{id}/consume` with RTP caps
8. **Connect transport** - POST `/consumers/{id}/connect` with DTLS params
9. **Consume media** - `transport.consume()` and attach to video/AI pipeline
10. **Cleanup** - DELETE consumer when done

### 10.2 Developer Checklist

#### Setup
- [ ] Registered API client with appropriate scopes
- [ ] Stored `client_secret` securely (not in code)
- [ ] Implemented token refresh logic
- [ ] Added `Authorization: Bearer` header to all V2 requests

#### Streaming
- [ ] Check device/stream status before starting
- [ ] Handle `reconnect: true` response
- [ ] Get router capabilities before attaching consumer
- [ ] Initialize mediasoup Device properly
- [ ] Handle `transport.on('connect')` event
- [ ] Resume consumer after creation

#### Error Handling
- [ ] Handle 401 with token refresh
- [ ] Implement retry logic with backoff
- [ ] Log errors with context (stream ID, device ID)
- [ ] Show user-friendly messages for user-actionable errors

#### Lifecycle
- [ ] Track active consumers locally
- [ ] Detach consumers before switching streams
- [ ] Close transport and consumer on disconnect
- [ ] Handle page/app unload gracefully

#### Monitoring
- [ ] Poll `/v2/streams/{id}/health` periodically
- [ ] Handle unhealthy stream states
- [ ] Implement reconnection logic

#### Security
- [ ] Never expose `client_secret` in frontend
- [ ] Use HTTPS in production
- [ ] Validate SSL certificates
- [ ] Don't store tokens in localStorage

### 10.3 Quick Reference Card

```
┌─────────────────────────────────────────────────────────────────┐
│                    VAS-MS-V2 QUICK REFERENCE                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  AUTH                                                           │
│  └─ POST /v2/auth/token → Get access_token                      │
│                                                                 │
│  DEVICES                                                        │
│  ├─ GET  /api/v1/devices → List cameras                         │
│  ├─ POST /api/v1/devices/{id}/start-stream → Start              │
│  └─ POST /api/v1/devices/{id}/stop-stream → Stop                │
│                                                                 │
│  STREAMS                                                        │
│  ├─ GET  /v2/streams → List streams                             │
│  ├─ GET  /v2/streams/{id} → Stream details                      │
│  ├─ GET  /v2/streams/{id}/health → Health check                 │
│  └─ GET  /v2/streams/{id}/router-capabilities → RTP caps        │
│                                                                 │
│  WEBRTC                                                         │
│  ├─ POST /v2/streams/{id}/consume → Attach consumer             │
│  ├─ POST /consumers/{id}/connect → DTLS handshake               │
│  └─ DEL  /consumers/{id} → Detach                               │
│                                                                 │
│  SNAPSHOTS                                                      │
│  ├─ POST /v2/streams/{id}/snapshots → Capture frame             │
│  ├─ GET  /v2/snapshots/{id}/image → Download image              │
│  └─ GET  /v2/snapshots → List with filters                      │
│                                                                 │
│  BOOKMARKS                                                      │
│  ├─ POST /v2/streams/{id}/bookmarks → Create clip               │
│  ├─ GET  /v2/bookmarks/{id}/video → Download video              │
│  └─ GET  /v2/bookmarks → List with filters                      │
│                                                                 │
│  HLS (Fallback)                                                 │
│  └─ GET  /v2/streams/{id}/hls/playlist.m3u8 → HLS playlist      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Appendix A: Stream States

| State | Description | Can Attach Consumer? |
|-------|-------------|---------------------|
| `INITIALIZING` | Stream record created | No |
| `READY` | SSRC captured, producer created | No |
| `LIVE` | FFmpeg running, media flowing | **Yes** |
| `ERROR` | Failure occurred (can recover) | No |
| `STOPPED` | Manually stopped | No |
| `CLOSED` | Cleanup complete (terminal) | No |

---

## Appendix B: Recording Retention

- **Default retention:** 7 days
- **Format:** HLS (.m3u8 + .ts segments)
- **Segment duration:** 6 seconds
- **Path:** `/recordings/hot/{stream_id}/`
- **Cleanup:** Automatic hourly job

---

## Appendix C: Supported Codecs

| Type | Codec | Parameters |
|------|-------|------------|
| Video | H.264 | Baseline profile (42e01f), 30 FPS, 2 Mbps |

---

## Appendix D: Environment Variables (Reference)

| Variable | Default | Description |
|----------|---------|-------------|
| `MEDIASOUP_URL` | `ws://localhost:3001` | MediaSoup server URL |
| `MEDIASOUP_HOST` | `127.0.0.1` | MediaSoup RTP host |
| `JWT_SECRET_KEY` | (required) | JWT signing key |

---

## Appendix E: OpenAPI Specification

VAS-MS-V2 provides an OpenAPI 3.0 specification for automated tooling and contract testing.

### Accessing the Specification

| Format | Endpoint | Description |
|--------|----------|-------------|
| JSON | `GET /v2/openapi.json` | OpenAPI 3.0 spec in JSON format |
| YAML | `GET /v2/openapi.yaml` | OpenAPI 3.0 spec in YAML format |
| Swagger UI | `GET /v2/docs` | Interactive API documentation |
| ReDoc | `GET /v2/redoc` | Alternative documentation UI |

### Using for Code Generation

```bash
# Generate TypeScript client
npx openapi-typescript-codegen \
  --input http://vas-ms-v2:8085/v2/openapi.json \
  --output ./src/api-client \
  --client axios

# Generate Python client
openapi-generator generate \
  -i http://vas-ms-v2:8085/v2/openapi.json \
  -g python \
  -o ./api-client

# Validate requests/responses against spec
npx @apidevtools/swagger-cli validate openapi.json
```

### Contract Testing

```javascript
// Using Prism for mock server
npx @stoplight/prism-cli mock openapi.json

// Using schemathesis for fuzz testing
schemathesis run http://vas-ms-v2:8085/v2/openapi.json
```

### Key Schema Definitions

The OpenAPI spec includes complete schemas for:

- `Stream` - Stream resource with state, endpoints, producer info
- `Consumer` - WebRTC consumer with transport parameters
- `Bookmark` - Video clip with async processing status
- `Snapshot` - Image capture with async processing status
- `Error` - Standardized error response format
- `TokenResponse` - Authentication token response

### Version Compatibility

| API Version | OpenAPI Spec Version | Compatibility |
|-------------|---------------------|---------------|
| V2 (current) | 3.0.3 | Full support |
| V1 (legacy) | Not available | Use this guide |

---

## Appendix F: Complete Error Code Reference

| Error Code | HTTP Status | Category | Description | Retry? |
|------------|-------------|----------|-------------|--------|
| `VALIDATION_ERROR` | 400 | Request | Request validation failed | No |
| `INVALID_TOKEN` | 401 | Auth | Access token invalid | Yes (refresh) |
| `TOKEN_EXPIRED` | 401 | Auth | Access token expired | Yes (refresh) |
| `INVALID_REFRESH_TOKEN` | 401 | Auth | Refresh token invalid/expired | No (re-auth) |
| `INVALID_CREDENTIALS` | 401 | Auth | Client credentials invalid | No |
| `INSUFFICIENT_SCOPE` | 403 | Auth | Missing required scope | No |
| `RESOURCE_NOT_FOUND` | 404 | Resource | Stream/bookmark/snapshot not found | No |
| `STREAM_NOT_LIVE` | 409 | State | Cannot consume non-live stream | Yes (wait) |
| `CONSUMER_ALREADY_EXISTS` | 409 | State | Consumer already attached | No |
| `MEDIASOUP_UNAVAILABLE` | 503 | Infrastructure | MediaSoup server down | Yes (backoff) |
| `RTSP_TIMEOUT` | 504 | Camera | Camera not responding | Yes (backoff) |
| `SSRC_CAPTURE_FAILED` | 502 | Camera | No video from camera | Yes (backoff) |
| `RTSP_CONNECTION_FAILED` | 502 | Camera | Cannot connect to RTSP | No (check URL) |
| `FFMPEG_ERROR` | 500 | Processing | Transcoding failure | Yes (1x) |
| `EXTRACTION_TIMEOUT` | 500 | Processing | Bookmark/snapshot timeout | Yes (1x) |
| `NO_RECORDING_DATA` | 404 | Storage | Historical data not available | No |
| `DISK_FULL` | 503 | Storage | Storage exhausted | No (admin) |

---

*Document maintained by VAS-MS-V2 Team. For questions or updates, contact the platform team.*
