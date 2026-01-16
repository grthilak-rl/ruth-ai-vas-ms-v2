# Ruth AI — Frontend Data Contracts (Read-Only)

| Meta             | Value                                           |
|------------------|-------------------------------------------------|
| Document ID      | RUTH-UX-F6                                      |
| Version          | 1.0                                             |
| Status           | Draft                                           |
| Owner            | Frontend UX Designer Agent                      |
| Input Documents  | F1–F5, API Contract Specification               |
| Purpose          | Defensive data contracts for frontend consumption |

---

## 1. Document Purpose

This document defines **explicit, read-only data contracts** between the Ruth AI frontend and backend. It exists to:

- Prevent frontend assumptions about data shape, presence, or reliability
- Ensure frontend functions under partial failure, delay, or inconsistency
- Eliminate inference of backend state from UI-observed behavior
- Provide engineers with unambiguous consumption rules

**This is a defensive contract, not a feature specification.**

### What This Document Does NOT Do

| Non-Goal | Explanation |
|----------|-------------|
| **Propose backend changes** | Contracts reflect current backend reality |
| **Invent new APIs** | Only documents existing endpoints |
| **Infer missing data** | Documents what is missing as missing |
| **Redesign payloads** | No schema modifications proposed |

---

## 2. Data Domain Overview

The frontend consumes data from four primary domains:

| Domain | Description | Primary Consumers (F4 Screens) |
|--------|-------------|-------------------------------|
| **Events** | Violations, alerts, evidence | Alerts List, Violation Detail, Overview |
| **Health** | System status, camera status, detection status | Overview, Camera View, Settings > System Health |
| **Capabilities** | What the system can do now | Overview, Camera View, Settings |
| **Metrics** | Counts, summaries (display-only) | Overview, Reports Dashboard |

---

## 3. Domain 1: Events

### 3.1 Violation Data Contract

**Source Endpoint:** `GET /api/v1/violations`, `GET /api/v1/violations/{id}`

**Fields Used by Frontend:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string (UUID) | Yes | Unique identifier; treat as opaque |
| `type` | enum | Yes | `fall_detected` (extensible) |
| `camera_id` | string (UUID) | Yes | Reference to device; may not exist if camera deleted |
| `camera_name` | string | Yes | Human-readable; denormalized for display |
| `status` | enum | Yes | `open`, `reviewed`, `dismissed`, `resolved` |
| `confidence` | float (0.0–1.0) | Yes | **Never display as raw number** |
| `timestamp` | string (ISO 8601) | Yes | When detection occurred |
| `evidence` | object | Yes | Contains snapshot and video availability |
| `reviewed_by` | string or null | No | Email of reviewer; null if not reviewed |
| `reviewed_at` | string (ISO 8601) or null | No | When reviewed; null if not reviewed |
| `created_at` | string (ISO 8601) | Yes | Record creation time |
| `updated_at` | string (ISO 8601) | Yes | Last modification time |

**Evidence Sub-Object:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `snapshot_id` | string or null | No | VAS snapshot reference |
| `snapshot_url` | string or null | No | Proxied URL; only valid if snapshot_status = "ready" |
| `snapshot_status` | enum | Yes | `pending`, `processing`, `ready`, `failed` |
| `bookmark_id` | string or null | No | VAS bookmark reference |
| `bookmark_url` | string or null | No | Proxied URL; only valid if bookmark_status = "ready" |
| `bookmark_status` | enum | Yes | `pending`, `processing`, `ready`, `failed` |
| `bookmark_duration_seconds` | integer | No | Duration of video clip |

### 3.2 Confidence Mapping Contract

**The frontend MUST convert numeric confidence to categorical:**

| Backend Value | Frontend Display | Visual Treatment |
|---------------|------------------|------------------|
| `>= 0.8` | "High" | Solid border, prominent color |
| `0.6 – 0.79` | "Medium" | Standard styling |
| `< 0.6` | "Low" | Muted styling, dashed border |

**Hard Rule:** The frontend MUST NOT display `0.87` or `87%`. Always use categorical labels.

### 3.3 Status Lifecycle Contract

| Status | Meaning | Frontend Behavior |
|--------|---------|-------------------|
| `open` | New, unseen | Default filter; show "New" badge |
| `reviewed` | Operator has seen | Show "Reviewed" badge |
| `dismissed` | Marked as false positive | Visible with "Dismissed" status filter |
| `resolved` | Incident handled (terminal) | Visible with "Resolved" status filter |

**Transition Awareness:** The frontend does NOT enforce transitions. It renders the status it receives.

### 3.4 Evidence Availability Contract

| Evidence Status | Frontend Behavior |
|-----------------|-------------------|
| `pending` | Show "Preparing..." placeholder |
| `processing` | Show "Preparing..." with optional progress hint |
| `ready` | Enable playback; show media |
| `failed` | Show "Unavailable" message; hide play button |

**Hard Rule:** The frontend MUST NOT attempt to fetch evidence when status is not `ready`.

---

## 4. Domain 2: Health

### 4.1 System Health Contract

**Source Endpoint:** `GET /api/v1/health`

**Fields Used by Frontend:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `status` | enum | Yes | `healthy`, `unhealthy` |
| `service` | string | Yes | Service name (display for Admin only) |
| `version` | string | Yes | Service version (display for Admin only) |
| `timestamp` | string (ISO 8601) | Yes | When health was checked |
| `components` | object | Yes | Per-component health status |
| `error` | string or null | No | Error message if unhealthy |

**Components Object:**

| Field | Type | Notes |
|-------|------|-------|
| `database` | enum | `healthy`, `unhealthy` |
| `redis` | enum | `healthy`, `unhealthy` |
| `ai_runtime` | enum | `healthy`, `unhealthy` |

### 4.2 Global Status Mapping Contract

**The frontend derives global status from `/api/v1/health`:**

| Backend State | Frontend Display | Visual Indicator |
|---------------|------------------|------------------|
| `status = "healthy"` | "All Systems OK" | Green dot (●) |
| `status = "unhealthy"` AND any component unhealthy | "Degraded" | Yellow dot (◐) |
| API call fails | "Offline" | Red dot (○) |

**Hard Rule:** The frontend MUST NOT infer health from the absence of violations or any other indirect signal.

### 4.3 Model Status Contract

**Source Endpoint:** `GET /api/v1/models/status`

**Fields Used by Frontend:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `model_id` | string | Yes | Machine identifier (e.g., `fall_detection`) |
| `version` | string | Yes | Semver; display for Admin only |
| `status` | enum | Yes | `active`, `idle`, `starting`, `stopping`, `error` |
| `health` | enum | Yes | `healthy`, `degraded`, `unhealthy` |
| `cameras_active` | integer | Yes | Count of cameras using this model |
| `last_inference_at` | string (ISO 8601) or null | No | May be null if never run |
| `started_at` | string (ISO 8601) or null | No | May be null if not started |

**Status to Frontend Display Mapping:**

| Backend Status | Backend Health | Operator Sees | Admin Sees |
|----------------|----------------|---------------|------------|
| `active` | `healthy` | "Detection Active" | "Active / Healthy" |
| `active` | `degraded` | "Detection Degraded" | "Active / Degraded" |
| `active` | `unhealthy` | "Detection Paused" | "Active / Unhealthy" |
| `idle` | any | "Detection Paused" | "Idle" |
| `starting` | any | "Detection Starting..." | "Starting" |
| `stopping` | any | "Detection Stopping..." | "Stopping" |
| `error` | any | "Detection Paused" | "Error" |

**Hard Rule:** Operators MUST NOT see `model_id` as "fall_detection". Display as "Detection" or "AI Detection".

### 4.4 Camera/Device Health Contract

**Source Endpoint:** `GET /api/v1/devices`, `GET /api/v1/devices/{id}`

**Fields Used by Frontend:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string (UUID) | Yes | VAS device ID; treat as opaque |
| `name` | string | Yes | Human-readable camera name |
| `is_active` | boolean | Yes | Whether camera is registered as active |
| `streaming` | object | Yes | Streaming and inference status |

**Streaming Sub-Object:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `active` | boolean | Yes | Whether stream is running |
| `stream_id` | string or null | No | VAS stream ID; null if not streaming |
| `state` | enum or null | No | `live`, `stopped`, etc. |
| `ai_enabled` | boolean | Yes | Whether AI inference is enabled |
| `model_id` | string or null | No | Which model is processing |

**Camera Status Derivation:**

| `is_active` | `streaming.active` | Frontend Display |
|-------------|-------------------|------------------|
| `true` | `true` | "● Live" |
| `true` | `false` | "○ Offline" |
| `false` | any | "○ Disabled" |

**Detection Status Derivation:**

| `streaming.ai_enabled` | Model Health | Frontend Display |
|------------------------|--------------|------------------|
| `true` | healthy | "Detection Active" |
| `true` | degraded/unhealthy | "Detection Paused" |
| `false` | any | "Detection Disabled" |

---

## 5. Domain 3: Capabilities

### 5.1 System Capabilities Contract

The frontend determines what the system can currently do from health and model status endpoints.

**Capability Derivation Rules:**

| Capability | Derived From | When Available |
|------------|--------------|----------------|
| View live video | Device `streaming.active = true` | Camera is streaming |
| View violations | Health status != "offline" | Backend is reachable |
| Take action on violations | Health status != "offline" | Backend is reachable |
| View detection overlays | Model `status = "active"` | Model is running |
| Create new evidence | VAS component healthy | VAS is reachable |

**Hard Rule:** The frontend MUST NOT cache capability state. Always derive from latest API response.

### 5.2 Feature Availability Contract

| Feature | Always Available | Depends On |
|---------|------------------|------------|
| View Alerts List | Backend reachable | Health API |
| View Violation Detail | Backend reachable | Health API |
| Acknowledge/Dismiss | Backend reachable | Health API |
| View Camera List | Backend reachable | Health API |
| View Live Video | VAS streaming | Streaming state |
| View Detection Status | AI Runtime reachable | Model status |
| View System Health (Admin) | Backend reachable | Health API |

---

## 6. Domain 4: Metrics (Display-Only)

### 6.1 Analytics Summary Contract

**Source Endpoint:** `GET /api/v1/analytics/summary`

**Fields Used by Frontend:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `totals.violations_total` | integer | Yes | Total violations in time range |
| `totals.violations_open` | integer | Yes | Currently open violations |
| `totals.violations_reviewed` | integer | Yes | Reviewed but not resolved |
| `totals.violations_dismissed` | integer | Yes | Dismissed as false positive |
| `totals.violations_resolved` | integer | Yes | Resolved incidents |
| `totals.cameras_active` | integer | Yes | Cameras currently active |
| `generated_at` | string (ISO 8601) | Yes | When summary was computed |

### 6.2 Count Display Contract

**Frontend MUST display counts as:**

| Metric | Display Format | Example |
|--------|----------------|---------|
| Open violations | Integer, no formatting | "12" |
| Cameras active | "X / Y" format | "8 / 10" |
| Models active | "X / Y" format | "2 / 3" |
| Total violations (today) | Integer | "47" |

**Hard Rule:** The frontend MUST NOT perform arithmetic on counts from different API calls.

### 6.3 Staleness Contract

| `generated_at` Age | Frontend Behavior |
|--------------------|-------------------|
| < 60 seconds | Display normally |
| 60–300 seconds | Display with "Last updated: X ago" |
| > 300 seconds | Display with "Data may be outdated" warning |

---

## 7. Frontend Non-Assumptions (Critical)

This section defines what the frontend **MUST NEVER assume**.

### 7.1 Ordering Assumptions

| Assumption | Status | Explanation |
|------------|--------|-------------|
| Violations are returned in timestamp order | **FORBIDDEN** | Backend may return any order; use `sort_by` parameter |
| New violations appear at list top | **FORBIDDEN** | Must re-sort after each fetch |
| IDs are sequential or time-based | **FORBIDDEN** | IDs are opaque UUIDs |
| Pagination offset remains stable | **FORBIDDEN** | New items may shift offsets |

### 7.2 Completeness Assumptions

| Assumption | Status | Explanation |
|------------|--------|-------------|
| All violations have evidence | **FORBIDDEN** | Evidence may be `pending`, `failed`, or `null` |
| All cameras have violations | **FORBIDDEN** | Cameras may have zero violations |
| All fields are present | **FORBIDDEN** | Optional fields may be `null` or absent |
| Pagination `total` is exact | **FORBIDDEN** | Total may change during pagination |

### 7.3 Freshness Assumptions

| Assumption | Status | Explanation |
|------------|--------|-------------|
| Data is current | **FORBIDDEN** | Always check `updated_at` or `generated_at` |
| Health status is real-time | **FORBIDDEN** | Polling interval creates lag |
| Violation counts match list length | **FORBIDDEN** | Pagination and filtering may differ |
| Evidence `ready` means immediately available | **FORBIDDEN** | VAS may return 404 briefly after status change |

### 7.4 Correlation Assumptions

| Assumption | Status | Explanation |
|------------|--------|-------------|
| `camera_id` on violation exists as a device | **FORBIDDEN** | Camera may have been deleted |
| High confidence means detection is correct | **FORBIDDEN** | Confidence is model output, not truth |
| Zero violations means system is working | **FORBIDDEN** | Could mean model is paused |
| `reviewed_by` matches current user | **FORBIDDEN** | Another user may have reviewed |

### 7.5 Stability Assumptions

| Assumption | Status | Explanation |
|------------|--------|-------------|
| IDs never change | **ALLOWED** | UUIDs are immutable |
| Status only transitions forward | **FORBIDDEN** | `dismissed` can transition to `open` |
| Evidence status only transitions to `ready` | **FORBIDDEN** | Can transition to `failed` |
| Model version is stable | **FORBIDDEN** | Hot-reload or rollback may change version |

---

## 8. Frontend Non-Inference Rules (Critical)

This section defines what the frontend **MUST NEVER infer**.

### 8.1 Health Inference Rules

| Inference | Status | Correct Approach |
|-----------|--------|------------------|
| Infer system health from API latency | **FORBIDDEN** | Use explicit `/health` endpoint |
| Infer model health from detection frequency | **FORBIDDEN** | Use explicit `/models/status` endpoint |
| Infer camera online from recent violations | **FORBIDDEN** | Use device `streaming.active` field |
| Infer backend outage from 500 errors | **FORBIDDEN** | Show "error" state; let user retry |

### 8.2 Correctness Inference Rules

| Inference | Status | Correct Approach |
|-----------|--------|------------------|
| Infer detection correctness from confidence | **FORBIDDEN** | Display confidence category; let operator decide |
| Infer false positive from low confidence | **FORBIDDEN** | Display "Low Confidence" badge; let operator decide |
| Infer incident severity from violation count | **FORBIDDEN** | Each violation is independent |
| Infer model quality from dismissal rate | **FORBIDDEN** | Outside frontend scope |

### 8.3 Availability Inference Rules

| Inference | Status | Correct Approach |
|-----------|--------|------------------|
| Infer evidence availability from violation age | **FORBIDDEN** | Use explicit `evidence.snapshot_status` |
| Infer video existence from snapshot existence | **FORBIDDEN** | Check `evidence.bookmark_status` separately |
| Infer feature availability from UI visibility | **FORBIDDEN** | Check capability from API response |
| Infer camera capabilities from model status | **FORBIDDEN** | Camera and model are independent |

### 8.4 State Inference Rules

| Inference | Status | Correct Approach |
|-----------|--------|------------------|
| Infer global status from individual camera status | **FORBIDDEN** | Use `/health` endpoint |
| Infer model status from individual camera detection | **FORBIDDEN** | Use `/models/status` endpoint |
| Infer user permissions from UI presence | **FORBIDDEN** | Handle 403 errors gracefully |
| Infer action success from UI state change | **FORBIDDEN** | Wait for API confirmation |

---

## 9. Missing/Null Data Handling

### 9.1 Null Field Handling

| Field | When Null | Frontend Behavior |
|-------|-----------|-------------------|
| `camera_name` | Never (required) | N/A |
| `reviewed_by` | Not yet reviewed | Show "Not reviewed" |
| `reviewed_at` | Not yet reviewed | Omit from display |
| `evidence.snapshot_url` | No snapshot | Show placeholder |
| `evidence.bookmark_url` | No video | Show "Video unavailable" |
| `last_inference_at` | Model never ran | Show "No data" |

### 9.2 Empty Collection Handling

| Collection | When Empty | Frontend Behavior |
|------------|-----------|-------------------|
| Violations list | No violations | Show "No violations" empty state |
| Camera list | No cameras | Show "No cameras configured" |
| Events in violation | Never (at least one) | N/A |
| Bounding boxes | No detection boxes | Omit overlay |

### 9.3 API Failure Handling

| Failure Type | Frontend Behavior | User Message |
|--------------|-------------------|--------------|
| Network timeout | Show error state with retry | "Couldn't connect. Please try again." |
| 404 Not Found | Show "not found" state | "This item is no longer available." |
| 500 Server Error | Show error state with retry | "Something went wrong. Please try again." |
| 503 Unavailable | Show degraded state | "Service temporarily unavailable." |
| 401/403 Auth Error | Redirect to login or show permission error | "Session expired" or "Access denied" |

---

## 10. UX Mapping and Failure Behavior

### 10.1 Events Domain → UX Mapping

| Data Element | F3 Flow | F4 Screen | When Missing/Delayed |
|--------------|---------|-----------|----------------------|
| Violation list | Flow 1: View Live Violations | Alerts List | Show loading skeleton; retry on failure |
| Violation detail | Flow 2: Drill Down | Violation Detail | Show 404 if not found; show partial if evidence missing |
| Evidence snapshot | Flow 2: Drill Down | Violation Detail | Show placeholder; show "unavailable" if failed |
| Evidence video | Flow 2: Drill Down | Violation Detail | Show "Preparing..." if processing; "unavailable" if failed |
| Violation status | Flow 3: Acknowledge/Dismiss | Alerts List, Detail | Optimistic update; rollback on failure |

### 10.2 Health Domain → UX Mapping

| Data Element | F3 Flow | F4 Screen | When Missing/Delayed |
|--------------|---------|-----------|----------------------|
| Global status | Flow 4: Model Health Degradation | Global Nav | Show "Unknown" if API fails |
| Model status | Flow 4: Model Health Degradation | Overview, Settings | Show "Detection status unknown" |
| Camera status | Flow 5: Model Unavailable | Camera View | Show last known state; indicate staleness |
| Component health | Flow 4 (Admin) | Settings > System Health | Show "Unable to load" per component |

### 10.3 Capabilities Domain → UX Mapping

| Data Element | F3 Flow | F4 Screen | When Missing/Delayed |
|--------------|---------|-----------|----------------------|
| Streaming capability | N/A | Camera View | Disable video player; show message |
| Detection capability | Flow 5: Model Unavailable | Camera View | Show "Detection Paused" |
| Action capability | Flow 3: Acknowledge/Dismiss | Alerts List, Detail | Disable buttons; show message |

### 10.4 Metrics Domain → UX Mapping

| Data Element | F3 Flow | F4 Screen | When Missing/Delayed |
|--------------|---------|-----------|----------------------|
| Open violation count | N/A | Overview, Nav Badge | Show "—" if unknown |
| Camera count | N/A | Overview | Show "— / —" if unknown |
| Model count | N/A | Overview | Show "— / —" if unknown |
| Analytics summary | N/A | Reports Dashboard | Show loading; show stale warning if old |

---

## 11. Polling and Refresh Contracts

### 11.1 Polling Intervals

| Endpoint | Recommended Interval | Rationale |
|----------|---------------------|-----------|
| `/health` | 30 seconds | Balance freshness with overhead |
| `/models/status` | 30 seconds | Same as health |
| `/violations` (list) | 10 seconds | Alert timeliness |
| `/violations/{id}` | On-demand only | User-initiated |
| `/analytics/summary` | 60 seconds | Analytics can be stale |
| `/devices` | 60 seconds | Camera status changes rarely |

### 11.2 Refresh on Action

| User Action | What to Refresh |
|-------------|-----------------|
| Acknowledge violation | Refetch violation detail; refetch list if on list |
| Dismiss violation | Refetch list (item removed) |
| Navigate to Alerts | Refetch list |
| Navigate to Overview | Refetch health, metrics |
| Click System Status | Refetch health |

---

## 12. Data Transformation Rules

### 12.1 Timestamp Transformation

| Source Format | Display Format (Operator) | Display Format (Admin) |
|---------------|---------------------------|------------------------|
| ISO 8601 absolute | Relative ("2m ago", "1h ago") | ISO 8601 or relative |
| ISO 8601 > 24h old | Date + time ("Jan 13, 10:30 AM") | ISO 8601 |

### 12.2 Confidence Transformation

| Source Value | Target Display | Styling Token |
|--------------|----------------|---------------|
| 0.80–1.00 | "High" | `confidence-high` |
| 0.60–0.79 | "Medium" | `confidence-medium` |
| 0.00–0.59 | "Low" | `confidence-low` |

**Hard Rule:** Frontend MUST NOT display decimal, percentage, or any numeric representation.

### 12.3 Model ID Transformation

| Source Value | Operator Display | Admin Display |
|--------------|------------------|---------------|
| `fall_detection` | "Fall Detection" | "Fall Detection" |
| Any model_id | "Detection" (generic) | Humanized model name |

**Hard Rule:** Frontend MUST NOT display raw `model_id` or `model_version` to Operators.

---

## 13. Error Recovery Contracts

### 13.1 Retry Behavior

| Error Type | Retry? | Max Retries | Backoff |
|------------|--------|-------------|---------|
| Network timeout | Yes | 3 | 1s, 2s, 5s |
| 500 Internal | Yes | 2 | 2s, 5s |
| 503 Unavailable | Yes | 3 | 5s, 10s, 30s |
| 400 Bad Request | No | — | — |
| 401 Unauthorized | Yes (with refresh) | 1 | Immediate |
| 403 Forbidden | No | — | — |
| 404 Not Found | No | — | — |

### 13.2 Degraded State Behavior

| Degradation | Frontend Behavior |
|-------------|-------------------|
| Health API fails | Show "Unknown" status; continue with cached data |
| Violations API fails | Show error; enable retry; preserve existing list |
| Evidence fetch fails | Show "unavailable"; allow other actions |
| Action fails | Show inline error; enable retry; preserve form state |

---

## 14. Validation Checklist

### 14.1 Contract Completeness

| Requirement | Status |
|-------------|--------|
| All frontend-visible data has explicit contract | ✓ |
| All optional/required fields documented | ✓ |
| All null handling documented | ✓ |
| All error states documented | ✓ |

### 14.2 Non-Assumption Verification

| Requirement | Status |
|-------------|--------|
| Ordering assumptions documented as forbidden | ✓ |
| Completeness assumptions documented as forbidden | ✓ |
| Freshness assumptions documented as forbidden | ✓ |
| Correlation assumptions documented as forbidden | ✓ |

### 14.3 Non-Inference Verification

| Requirement | Status |
|-------------|--------|
| Health inference rules documented | ✓ |
| Correctness inference rules documented | ✓ |
| Availability inference rules documented | ✓ |
| State inference rules documented | ✓ |

### 14.4 UX Alignment Verification

| Requirement | Status |
|-------------|--------|
| Every domain mapped to F3 flows | ✓ |
| Every domain mapped to F4 screens | ✓ |
| Every failure behavior documented | ✓ |

---

## 15. Summary: Frontend Behavior Guarantees

The frontend, when built to these contracts, guarantees:

| Guarantee | Mechanism |
|-----------|-----------|
| **Functions under partial failure** | Explicit failure handling per endpoint |
| **No hidden backend dependencies** | All assumptions documented as forbidden |
| **No guessed data** | All inference documented as forbidden |
| **Engineers can implement without clarification** | All fields, states, and behaviors explicit |
| **Displays uncertainty when data is uncertain** | Staleness indicators, "unknown" states |

---

## 16. Document Cross-References

| Topic | Source Document | Section |
|-------|-----------------|---------|
| Confidence display rules | F1 (personas.md) | "What Operator Does NOT Care About" |
| Screen inventory | F2 (information-architecture.md) | "Screen Inventory Summary" |
| Failure paths | F3 (ux-flows.md) | All flows |
| Wireframe states | F4 (wireframes.md) | All screens |
| Stress test validation | F5 (operator-workflows.md) | All scenarios |
| API schemas | API Contract Specification | Domain Model Definitions |

---

**Document Status:** Ready for Review

**This document ensures:** The frontend can be implemented defensively, without assuming backend behavior that may not hold under real-world conditions.

---

**End of Document**
