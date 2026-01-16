# Phase 7 — I3: Frontend ↔ Backend Wiring Validation Report

**Date:** 2026-01-15
**Status:** FAIL (Contract Mismatches Detected)
**Validator:** Integration Engineer Agent

---

## Executive Summary

Task I3 validates that the frontend is properly wired to the live backend and renders real data. This validation revealed **significant contract mismatches** between the frontend data contracts (F6) and backend API implementation (Phase 4).

**Key Findings:**
1. ✅ Frontend container running and healthy
2. ✅ API proxy from frontend to backend working
3. ❌ Schema field name mismatches (`items` vs `violations`/`devices`)
4. ❌ Missing `streaming` object in device responses
5. ❌ Missing `/api/v1/models/status` endpoint
6. ❌ Mismatched analytics endpoint path

**Verdict:** Frontend cannot consume backend data in current state due to schema validation failures.

---

## Test Environment

| Component | Status | URL |
|-----------|--------|-----|
| Frontend | ✅ Healthy | http://localhost:3300 |
| Backend | ✅ Healthy | http://localhost:8090 |
| API Proxy | ✅ Working | /api/v1/* → backend:8080 |

---

## Detailed Findings

### 1. API Connectivity

**Status:** ✅ PASS

Frontend nginx successfully proxies API requests to backend:

```bash
# Via frontend proxy
curl http://localhost:3300/api/v1/health
# Returns: {"status":"healthy","service":"ruth-ai-backend",...}
```

---

### 2. Schema Mismatches

**Status:** ❌ FAIL

#### 2.1 Devices Endpoint

| Aspect | Frontend (F6 Contract) | Backend (Phase 4) | Match |
|--------|------------------------|-------------------|-------|
| List field name | `items` | `devices` | ❌ |
| Streaming object | `streaming: { active, stream_id, state, ai_enabled, model_id }` | Flat: `stream_status: { active, session_id, state, started_at, model_id }` | ❌ |
| Device.streaming.ai_enabled | Required | Not present | ❌ |
| Device.streaming.stream_id | Expected | Uses `session_id` | ❌ |

**Frontend Expects (types.ts):**
```typescript
interface DevicesListResponse {
  items: Device[];  // ← Frontend expects 'items'
  total: number;
}

interface DeviceStreaming {
  active: boolean;
  stream_id: string | null;  // ← Frontend expects 'stream_id'
  state: StreamState | null;
  ai_enabled: boolean;  // ← Frontend expects 'ai_enabled'
  model_id: string | null;
}
```

**Backend Returns:**
```json
{
  "devices": [  // ← Backend returns 'devices'
    {
      "id": "...",
      "name": "Cabin Camera",
      "is_active": true,
      "stream_status": {  // ← Backend uses 'stream_status' not 'streaming'
        "active": false,
        "session_id": null,  // ← Backend uses 'session_id' not 'stream_id'
        "state": null,
        "started_at": null,
        "model_id": null
        // Missing: ai_enabled
      }
    }
  ],
  "total": 1
}
```

#### 2.2 Violations Endpoint

| Aspect | Frontend (F6 Contract) | Backend (Phase 4) | Match |
|--------|------------------------|-------------------|-------|
| List field name | `items` | `violations` | ❌ |
| Violation.camera_id | Required | Uses `device_id` | ❌ |
| Violation.evidence | Nested object | Separate table | ⚠️ |

**Frontend Expects:**
```typescript
interface ViolationsListResponse {
  items: Violation[];  // ← Frontend expects 'items'
  total: number;
}
```

**Backend Returns:**
```json
{
  "violations": [],  // ← Backend returns 'violations'
  "total": 0
}
```

---

### 3. Missing Endpoints

**Status:** ❌ FAIL

#### 3.1 Models Status Endpoint

```bash
curl http://localhost:8090/api/v1/models/status
# Returns: {"detail":"Not Found"}
```

**Frontend requires:** `/api/v1/models/status`
**Backend provides:** Endpoint not implemented

This endpoint is needed by:
- `SystemStatusIndicator` component
- `SystemHealthView` component
- Detection status derivation

#### 3.2 Analytics Summary Endpoint

```bash
curl http://localhost:8090/api/v1/analytics/summary
# Returns: {"detail":"Not Found"}
```

**Frontend expects:** `/api/v1/analytics/summary`
**Backend provides:** `/api/v1/analytics/violations/summary` (different path, returns 501)

---

### 4. Working Endpoints

**Status:** ✅ PASS

The following endpoints work correctly:

| Endpoint | Status | Response |
|----------|--------|----------|
| `GET /api/v1/health` | ✅ 200 | Full health response with components |
| `GET /api/v1/devices` | ✅ 200 | Returns devices (schema mismatch) |
| `GET /api/v1/devices/{id}` | ✅ 200 | Returns device detail (schema mismatch) |
| `GET /api/v1/violations` | ✅ 200 | Returns violations (schema mismatch) |
| `POST /internal/sync/devices` | ✅ 200 | Device sync works |

---

### 5. Polling & Live Updates

**Status:** ⏸️ BLOCKED

Cannot validate polling because frontend validators will reject backend responses due to schema mismatches.

Expected behavior per F6:
- Violations: 10s polling interval
- Health: 30s polling interval
- Devices: 60s polling interval

---

### 6. Session/Auth Behavior

**Status:** ⏸️ NOT TESTED

Authentication is not currently enabled. When implemented:
- Session persistence
- 401 handling
- 403 handling

Should be validated.

---

## Contract Alignment Matrix

| Frontend Contract (F6) | Backend Implementation | Alignment |
|------------------------|------------------------|-----------|
| `DevicesListResponse.items` | `DeviceListResponse.devices` | ❌ Mismatch |
| `Device.streaming` | `DeviceDetailResponse.stream_status` | ❌ Mismatch |
| `Device.streaming.stream_id` | `StreamStatusResponse.session_id` | ❌ Mismatch |
| `Device.streaming.ai_enabled` | Not present | ❌ Missing |
| `ViolationsListResponse.items` | `ViolationListResponse.violations` | ❌ Mismatch |
| `Violation.camera_id` | `ViolationResponse.device_id` | ❌ Mismatch |
| `ModelsStatusResponse` | Not implemented | ❌ Missing |
| `AnalyticsSummaryResponse` | Different path, 501 | ❌ Mismatch |
| `HealthResponse` | Matches | ✅ OK |

---

## Remediation Options

### Option A: Align Backend to Frontend Contract (Recommended)

Update backend schemas to match F6 data contracts:

1. **Device schemas:**
   - Rename `devices` → `items`
   - Rename `stream_status` → `streaming`
   - Rename `session_id` → `stream_id`
   - Add `ai_enabled` field

2. **Violation schemas:**
   - Rename `violations` → `items`
   - Rename `device_id` → `camera_id`

3. **Add missing endpoints:**
   - `/api/v1/models/status`
   - `/api/v1/analytics/summary`

**Estimated effort:** Medium (schema changes + endpoint additions)

### Option B: Align Frontend to Backend Reality

Update frontend validators and types to match backend:

1. Update `DevicesListResponse.items` → `devices`
2. Update `ViolationsListResponse.items` → `violations`
3. Update all field name references

**Estimated effort:** Medium (type changes across frontend)

### Option C: Add Adapter Layer

Create API adapter functions in frontend that transform backend responses:

```typescript
function adaptDevicesResponse(backendResponse): DevicesListResponse {
  return {
    items: backendResponse.devices.map(adaptDevice),
    total: backendResponse.total
  };
}
```

**Estimated effort:** Low (adapter functions only)

---

## Files Involved in Remediation

### Backend (Option A)
- `app/schemas/device.py` - Device response schemas
- `app/schemas/violation.py` - Violation response schemas
- `app/api/v1/devices.py` - Device endpoints
- `app/api/v1/violations.py` - Violation endpoints
- New: `app/api/v1/models.py` - Models status endpoint

### Frontend (Option B/C)
- `src/state/api/types.ts` - Type definitions
- `src/state/api/validators.ts` - Response validators
- `src/state/api/devices.api.ts` - Devices API
- `src/state/api/violations.api.ts` - Violations API

---

## Conclusion

I3 validation **FAILED** due to contract mismatches between frontend and backend.

**Critical Issues:**
- ❌ Schema field name mismatches prevent data rendering
- ❌ Missing endpoints block key UI functionality
- ❌ Frontend validators will reject all backend responses

**Before production:**
1. Choose remediation option (A, B, or C)
2. Implement schema alignment
3. Add missing endpoints
4. Re-run I3 validation

---

## Next Steps

1. **Decide alignment approach** with stakeholders
2. **Implement schema fixes** (recommended: Option A)
3. **Add `/api/v1/models/status` endpoint**
4. **Add `/api/v1/analytics/summary` endpoint**
5. **Re-validate I3** after fixes
6. **Proceed to I4** (AI Runtime Integration) only after I3 passes

---

*Report generated by Integration Engineer Agent — Phase 7: Integration & Validation*
