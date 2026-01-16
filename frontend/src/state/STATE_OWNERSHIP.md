# Ruth AI Frontend — State Ownership Document

**Version:** 1.0
**Status:** Approved
**Dependencies:** F2, F3, F5, F6, CLAUDE.md

---

## 1. State Strategy Decision

### Server State: TanStack Query (React Query)

**Chosen over SWR because:**
- Built-in polling with `refetchInterval`
- Automatic background refetch on window focus
- Configurable stale time and cache time per query
- Automatic pause on tab inactive (visibility-based)
- Better TypeScript support and error handling
- Query invalidation patterns for mutation side effects

**Server state includes:**
- Health status (`/api/v1/health`)
- Violations list and detail (`/api/v1/violations`)
- Devices/Cameras list (`/api/v1/devices`)
- Model status (`/api/v1/models/status`)
- Analytics summary (`/api/v1/analytics/summary`)

### UI/View State: Local Component State (useState, useReducer)

**Includes:**
- Modal open/close states
- Filter/sort selections (before applied to query)
- Form input values
- Pagination UI state
- Expanded/collapsed toggles
- Tab selections

**Why local state:**
- Does not need to persist across page navigation
- Does not need to synchronize with backend
- Component-scoped lifecycle is appropriate

---

## 2. Polling Strategy (F6-Compliant)

### Polling Intervals

| Query Key | Endpoint | Interval | Rationale (F6 §11.1) |
|-----------|----------|----------|----------------------|
| `health` | `/api/v1/health` | 30s | Balance freshness with overhead |
| `violations` | `/api/v1/violations` | 10s | Alert timeliness |
| `models-status` | `/api/v1/models/status` | 30s | Same as health |
| `devices` | `/api/v1/devices` | 60s | Camera status changes rarely |
| `analytics` | `/api/v1/analytics/summary` | 60s | Analytics can be stale |

### Polling Rules

1. **Explicit intervals** — Each query specifies its own `refetchInterval`
2. **Cancelable** — Queries can be disabled via `enabled: false`
3. **Pause on tab inactive** — `refetchIntervalInBackground: false` (default)
4. **No shared timers** — Each query maintains independent polling
5. **Refetch on window focus** — Enabled for all queries

### On-Demand Queries (No Polling)

| Query Key | Endpoint | Trigger |
|-----------|----------|---------|
| `violation-detail` | `/api/v1/violations/{id}` | User navigates to detail page |

---

## 3. Global App State Definition

### 3.1 Health Status

| Property | Source | Update Mechanism | Consumers |
|----------|--------|------------------|-----------|
| `status` | `/api/v1/health` → `status` field | 30s polling | Global status indicator, Overview |
| `components` | `/api/v1/health` → `components` field | 30s polling | Settings > System Health (Admin) |

**Derivation rule (F6 §4.2):**
- `status = "healthy"` → Display "All Systems OK" (green)
- `status = "unhealthy"` with any component unhealthy → Display "Degraded" (yellow)
- API call fails → Display "Offline" (red)

**Source of truth:** `useHealthQuery()` hook only. No inference from other signals.

### 3.2 Auth/Session State

| Property | Source | Update Mechanism | Consumers |
|----------|--------|------------------|-----------|
| `isAuthenticated` | Token presence in storage | On app load, on login/logout | All protected routes |
| `token` | localStorage or sessionStorage | On login, on token refresh | API client (Authorization header) |

**401 Handling:**
- On 401 response → Attempt token refresh (1 retry)
- If refresh fails → Clear token, redirect to login
- Display: "Session expired"

**403 Handling:**
- On 403 response → Display "Access denied"
- No retry — this is a permission error, not auth error

### 3.3 User Role

| Property | Source | Update Mechanism | Consumers |
|----------|--------|------------------|-----------|
| `role` | Token payload or `/api/v1/me` | On login, on token refresh | Navigation visibility, action permissions |

**Role values:** `operator`, `supervisor`, `admin`

**UI gating only:** Role gates what UI elements are visible. Backend enforces actual permissions. Frontend does NOT infer permissions from role — handles 403 gracefully.

---

## 4. Error & Failure Handling Model

### 4.1 Error Categories (F6 §13.1)

| Error Type | Retry? | Max Retries | Backoff | User Message |
|------------|--------|-------------|---------|--------------|
| Network timeout | Yes | 3 | 1s, 2s, 5s | "Couldn't connect. Please try again." |
| 500 Internal Server Error | Yes | 2 | 2s, 5s | "Something went wrong. Please try again." |
| 503 Service Unavailable | Yes | 3 | 5s, 10s, 30s | "Service temporarily unavailable." |
| 400 Bad Request | No | — | — | "Invalid request." |
| 401 Unauthorized | Yes (token refresh) | 1 | Immediate | "Session expired" |
| 403 Forbidden | No | — | — | "Access denied" |
| 404 Not Found | No | — | — | "This item is no longer available." |

### 4.2 Error vs Degraded States

| Condition | State | UI Behavior |
|-----------|-------|-------------|
| Single endpoint fails, others succeed | **Degraded** | Show error for failed component, continue with others |
| Health endpoint fails | **Degraded** | Show "Unknown" status, continue with cached data |
| All endpoints fail | **Error** | Show full-page error with retry |
| Evidence fetch fails | **Partial** | Show "unavailable", allow other actions |
| Action (mutation) fails | **Inline Error** | Show error toast, preserve form state, enable retry |

### 4.3 Stale Data Rules (F6 §6.3)

| Data Age | UI Behavior |
|----------|-------------|
| < 60 seconds | Display normally |
| 60–300 seconds | Display with "Last updated: X ago" |
| > 300 seconds | Display with "Data may be outdated" warning |

---

## 5. State Ownership Matrix

| State Category | Owner | Location | Updates | Fails |
|----------------|-------|----------|---------|-------|
| System health | `useHealthQuery` | React Query cache | 30s polling | Show "Unknown" |
| Violations list | `useViolationsQuery` | React Query cache | 10s polling | Show error, preserve cached |
| Violation detail | `useViolationQuery` | React Query cache | On-demand | Show 404 or error |
| Devices list | `useDevicesQuery` | React Query cache | 60s polling | Show error, preserve cached |
| Model status | `useModelsStatusQuery` | React Query cache | 30s polling | Show "Unknown" |
| Analytics | `useAnalyticsQuery` | React Query cache | 60s polling | Show error with stale warning |
| Auth token | `AuthContext` | React Context + localStorage | On login/refresh | Redirect to login |
| User role | `AuthContext` | React Context | On login/refresh | Default to restricted |
| Filter selections | Component state | `useState` | User interaction | Reset to default |
| Modal states | Component state | `useState` | User interaction | N/A |

---

## 6. Query Key Structure

```typescript
// Standardized query keys for cache management
const queryKeys = {
  health: ['health'] as const,
  violations: {
    all: ['violations'] as const,
    list: (filters: ViolationFilters) => ['violations', 'list', filters] as const,
    detail: (id: string) => ['violations', 'detail', id] as const,
  },
  devices: {
    all: ['devices'] as const,
    detail: (id: string) => ['devices', 'detail', id] as const,
  },
  models: {
    status: ['models', 'status'] as const,
  },
  analytics: {
    summary: ['analytics', 'summary'] as const,
  },
} as const;
```

---

## 7. Mutation Side Effects

| Mutation | Invalidates | Refetches |
|----------|-------------|-----------|
| Acknowledge violation | `violations.list` | Violation list |
| Dismiss violation | `violations.list` | Violation list |
| Resolve violation | `violations.list` | Violation list |
| Any violation action | `violations.detail(id)` | Specific violation |

---

## 8. Explicit Non-Assumptions

Per F6 §7, the state layer MUST NOT:

- **Assume ordering** — Always use `sort_by` parameter, never assume newest-first
- **Assume completeness** — Handle missing fields gracefully
- **Assume freshness** — Always check `updated_at` or `generated_at`
- **Assume correlation** — Don't infer camera exists from violation
- **Infer health from latency** — Use explicit `/health` endpoint
- **Infer model status from detection frequency** — Use explicit `/models/status`
- **Cache capabilities** — Always derive from latest API response

---

## 9. Alignment with Design Documents

| State Decision | Source Document | Section |
|----------------|-----------------|---------|
| Polling intervals | F6 | §11.1 Polling Intervals |
| Retry behavior | F6 | §13.1 Retry Behavior |
| Staleness rules | F6 | §6.3 Staleness Contract |
| Health derivation | F6 | §4.2 Global Status Mapping |
| Error messages | F3 | All failure paths |
| Non-assumptions | F6 | §7 Frontend Non-Assumptions |
| Non-inference | F6 | §8 Frontend Non-Inference Rules |

---

**End of Document**
