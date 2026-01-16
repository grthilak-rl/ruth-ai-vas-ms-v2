# Ruth AI — Information Architecture

**Version:** 1.0
**Owner:** Frontend UX Designer
**Status:** Approved / Frozen
**Last Updated:** January 2026
**Dependency:** This document requires [F1 - Personas](personas.md) to be frozen.

---

## Purpose

This document defines the **structural backbone** of the Ruth AI frontend:
- What screens exist
- How they are organized
- How users navigate between them
- What entities are visible to each persona

This is the foundation for all wireframes, workflows, and component designs. No visual design is specified here.

---

## Design Constraints (from F1 Personas)

These constraints shape every structural decision:

| Constraint | Source | Impact on IA |
|------------|--------|--------------|
| Operators need shallow navigation | Persona G1.1, G1.4 | Violations must be reachable in ≤1 click |
| Operators must not see AI internals | Persona "Does NOT Care About" | No model version, FPS, or pipeline screens for Operators |
| Supervisors need historical access | Persona G2.3, G2.4 | History/search must be prominent |
| Admins configure, not resolve | Persona G3 Decision Authority | Admin screens are separate from violation workflows |
| VAS is abstracted | Persona terminology | No "VAS" or "stream" in navigation labels |

---

## Top-Level Navigation Structure

The primary navigation consists of **five sections**, organized by primary use case:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          RUTH AI NAVIGATION BAR                              │
├──────────┬──────────┬──────────┬──────────┬──────────────────────────────────┤
│ Overview │ Cameras  │ Violations │ Analytics │ Settings                      │
└──────────┴──────────┴──────────┴──────────┴──────────────────────────────────┘
```

### Navigation Section Definitions

| Section | Primary Persona(s) | Purpose | Global? |
|---------|-------------------|---------|---------|
| **Overview** | Operator, Supervisor, Admin | At-a-glance system state and active violations | Yes |
| **Cameras** | Operator, Admin | Live video feeds with AI detection status | Yes |
| **Violations** | Operator, Supervisor | All violations (active and historical) with comprehensive filtering | Yes |
| **Analytics** | Supervisor, Admin | Analytics and summary dashboards | Yes |
| **Settings** | Admin | System configuration, user management, AI settings | Yes (role-gated) |

### Design Decision: No Separate History Section

**There is intentionally no standalone "History" page.**

Historical violations are accessed through the **Violations** section using filters:
- **Status filters:** Open, Reviewed, Dismissed, Resolved
- **Date range filters:** Today, Last 7 Days, Last 30 Days, Custom Range
- **Camera filter:** Filter by specific device
- **Confidence filter:** Filter by confidence level

**Rationale:** A separate History page creates confusion about where to find closed violations. The unified Violations page with comprehensive filtering provides a cleaner mental model: "All violations are in one place, filtered by what I need."

### Design Decision: No Standalone "Models" Section

**There is intentionally no top-level "Models" screen.**

AI models are surfaced only through:
- **Camera configuration** (Admin): Enable/disable AI, select model per camera
- **System Health** (Admin): Model status (Healthy/Degraded/Offline)
- **AI Configuration** (Admin): Global thresholds and model settings

**Rationale:** This prevents mental coupling between operators and model internals. Operators interact with *detections* and *violations*, not models. If a stakeholder asks "where is the models page?", the answer is: "Models are managed through Camera and System Health settings, not as a standalone concept."

---

## Section 1: Overview

### Purpose
The default landing screen. Provides immediate situational awareness without navigation.

### Primary Persona
**Operator** (continuous use), **Supervisor** (quick check), **Admin** (health check)

### What Must Be Visible
- Count of open violations (badge)
- Camera health summary (N connected / N total)
- AI detection status (active/paused)
- Most recent violations (top 5)
- System health indicator (simplified: healthy/degraded/offline)

### What Must Be Hidden
- Model names, versions, inference metrics
- Frame rates, queue depths, backend service names
- VAS-specific terminology

### Child Screens
| Screen | Description | Persona Access |
|--------|-------------|----------------|
| Overview Dashboard | Main landing view | All |

### Navigation Behavior
- Clicking a violation badge → navigates to **Alerts**
- Clicking a camera status → navigates to **Cameras**
- Clicking system health → navigates to **Settings > System Health** (Admin only)

---

## Section 2: Cameras

### Purpose
View live video feeds with AI detection overlays. Primary operational screen for Operators.

### Primary Persona
**Operator** (primary), **Admin** (configuration)

### What Must Be Visible
- List of all cameras (grid or list view)
- Live video player with detection overlays
- Camera status: Connected / Offline / Degraded
- AI status per camera: Active / Paused / Not Enabled
- Recent violations for selected camera

### What Must Be Hidden
- Stream IDs, transport details, WebRTC state
- Model internals, inference timing
- VAS API details

### Child Screens

| Screen | Description | Persona Access |
|--------|-------------|----------------|
| Camera List | Grid/list of all cameras with status | Operator, Supervisor, Admin |
| Camera View | Live video player for single camera | Operator, Supervisor, Admin |
| Camera Detail | Expanded view with recent activity | Operator, Supervisor, Admin |
| Camera Settings | Configuration (AI enable, thresholds) | Admin only |

### Entity Nesting
```
Cameras
├── Camera List
│   └── Camera View
│       ├── Live Video (embedded)
│       ├── Detection Status (embedded)
│       └── Recent Violations (contextual list)
└── Camera Settings (Admin only)
```

### Navigation Behavior
- Camera List is the entry point
- Selecting a camera → Camera View (live video)
- Admin badge on camera → Camera Settings
- Violation in "Recent" list → Alerts > Violation Detail

---

## Section 3: Violations

### Purpose
Unified violation management. The single location for viewing, filtering, and acting on all violations regardless of status.

### Primary Persona
**Operator** (primary), **Supervisor** (review)

### What Must Be Visible
- List of all violations with comprehensive filtering
- Filter controls: status (open, reviewed, dismissed, resolved), date range, camera, confidence
- Violation details: camera, timestamp, confidence category (High/Medium/Low)
- Evidence: snapshot preview, video playback
- Action buttons: Acknowledge, Dismiss, Escalate, Resolve

### What Must Be Hidden
- Raw confidence scores (use categorical labels)
- Event aggregation details (show violations only)
- Model version, inference time

### Child Screens

| Screen | Description | Persona Access |
|--------|-------------|----------------|
| Violations List | All violations with filters | Operator, Supervisor |
| Violation Detail | Full violation information | Operator, Supervisor |
| Evidence Viewer | Snapshot and video playback | Operator, Supervisor |

### Entity Nesting
```
Violations
├── Violations List (default view)
│   ├── Filter Sidebar
│   │   ├── Status Filter (open, reviewed, dismissed, resolved)
│   │   ├── Date Range Filter
│   │   ├── Camera Filter
│   │   └── Confidence Filter
│   ├── Violation Detail
│   │   ├── Evidence Viewer (embedded)
│   │   └── Related Camera Link (contextual)
│   └── Quick Actions (inline: Acknowledge, Dismiss)
└── Escalated Alerts (filtered view for Supervisor)
```

### Navigation Behavior
- Violations List is the entry point (defaults to Open status filter)
- Selecting a violation → Violation Detail
- "View Camera" link → Cameras > Camera View
- Filters persist during navigation and are URL-bookmarkable

---

## Section 4: Analytics

### Purpose
Operational analytics and summary dashboards.

### Primary Persona
**Supervisor** (primary), **Admin** (operational health)

### What Must Be Visible
- Violation counts by time period
- Violations by camera
- Violations by status (open, reviewed, dismissed, resolved)
- Time-series charts

### What Must Be Hidden
- Event-level metrics
- AI inference metrics (belongs in Settings > System Health)
- Raw API data

### Child Screens

| Screen | Description | Persona Access |
|--------|-------------|----------------|
| Analytics Dashboard | Summary charts and KPIs | Supervisor, Admin |
| Camera Performance | Per-camera violation stats | Supervisor, Admin |
| Export Data | CSV export | Supervisor, Admin |

### Entity Nesting
```
Analytics
├── Analytics Dashboard (entry point)
│   ├── Summary Cards (embedded)
│   └── Time Series Chart (embedded)
├── Camera Performance
└── Export Data
```

### Navigation Behavior
- Dashboard is the default view
- Clicking a camera in the chart → Violations (filtered by camera)
- Export produces downloadable file

---

## Section 5: Settings

### Purpose
System configuration, user management, and health monitoring. Admin-only section.

### Primary Persona
**Admin** (exclusive)

### What Must Be Visible
- Camera management (enable/disable AI, thresholds)
- User management (add/remove, assign roles)
- System health (services, AI models)
- Audit logs

### What Must Be Hidden
- Infrastructure primitives (pods, containers, IPs)
- Model weights, architecture details
- VAS internals

### What Admins MAY See (Abstracted)
- "Fall Detection: Healthy / Degraded / Offline"
- "Backend: Healthy"
- "Processing 45 frames/sec across 8 cameras"

### Child Screens

| Screen | Description | Persona Access |
|--------|-------------|----------------|
| General Settings | Application-level config | Admin |
| Camera Management | Configure AI per camera | Admin |
| AI Configuration | Confidence thresholds, models | Admin |
| User Management | Users, roles, permissions | Admin |
| System Health | Service status dashboard | Admin |
| Audit Log | Action history | Admin |

### Entity Nesting
```
Settings
├── General Settings
├── Camera Management
│   └── Camera Config Detail
├── AI Configuration
├── User Management
│   └── User Detail
├── System Health
│   ├── Service Status
│   └── AI Model Status
└── Audit Log
```

### Role Gating
The Settings section is **completely hidden** from Operators and Supervisors. Navigation item does not appear for these roles.

---

## Screen Inventory Summary

### Complete Screen List

| Section | Screen | Path | Operator | Supervisor | Admin |
|---------|--------|------|----------|------------|-------|
| Overview | Dashboard | `/` | ✓ | ✓ | ✓ |
| Cameras | Camera List | `/cameras` | ✓ | ✓ | ✓ |
| Cameras | Camera View | `/cameras/:id` | ✓ | ✓ | ✓ |
| Cameras | Camera Detail | `/cameras/:id/detail` | ✓ | ✓ | ✓ |
| Cameras | Camera Settings | `/cameras/:id/settings` | — | — | ✓ |
| Violations | Violations List | `/alerts` | ✓ | ✓ | — |
| Violations | Violation Detail | `/alerts/:id` | ✓ | ✓ | — |
| Violations | Evidence Viewer | `/alerts/:id/evidence` | ✓ | ✓ | — |
| Analytics | Analytics Dashboard | `/analytics` | — | ✓ | ✓ |
| Analytics | Camera Performance | `/analytics/cameras` | — | ✓ | ✓ |
| Analytics | Export Data | `/analytics/export` | — | ✓ | ✓ |
| Settings | General Settings | `/settings` | — | — | ✓ |
| Settings | Camera Management | `/settings/cameras` | — | — | ✓ |
| Settings | Camera Config Detail | `/settings/cameras/:id` | — | — | ✓ |
| Settings | AI Configuration | `/settings/ai` | — | — | ✓ |
| Settings | User Management | `/settings/users` | — | — | ✓ |
| Settings | User Detail | `/settings/users/:id` | — | — | ✓ |
| Settings | System Health | `/settings/health` | — | — | ✓ |
| Settings | Audit Log | `/settings/audit` | — | — | ✓ |

**Total Screens: 19**

### Screen Count by Role

| Role | Accessible Screens | Hidden Screens |
|------|-------------------|----------------|
| Operator | 8 | 11 |
| Supervisor | 11 | 8 |
| Admin | 19 | 0 |

---

## Entity Hierarchy Definition

### Canonical Entity Model

The frontend works with these domain entities:

```
Camera (VAS Device)
  │
  ├── Live Video Feed (transient, not persisted)
  │
  ├── AI Detection Status (real-time)
  │     └── Active / Paused / Not Enabled
  │
  └── Violations (persisted)
        │
        ├── Evidence
        │     ├── Snapshot
        │     └── Video Clip
        │
        └── Events (internal, aggregated)
```

### Entity Visibility Rules

| Entity | Operator | Supervisor | Admin | Notes |
|--------|----------|------------|-------|-------|
| Camera | ✓ | ✓ | ✓ | Primary navigable entity |
| Live Video | ✓ | ✓ | ✓ | Embedded in Camera View |
| AI Detection Status | ✓ (simplified) | ✓ (simplified) | ✓ (detailed) | "Active" vs. metrics |
| Violation | ✓ | ✓ | ✓ (read-only) | Primary navigable entity |
| Evidence | ✓ | ✓ | ✓ | Embedded in Violation |
| Snapshot | ✓ | ✓ | ✓ | Part of Evidence |
| Video Clip | ✓ | ✓ | ✓ | Part of Evidence |
| Event | — | — | — | **Never exposed** - internal aggregation |
| Stream | — | — | — | **Never exposed** - VAS abstraction |
| Model | — | — | ✓ (abstracted) | "Fall Detection" not "fall_detection_v1.2.3" |
| Service | — | — | ✓ (abstracted) | "Backend: Healthy" not pod status |
| User | — | — | ✓ | Admin-only entity |

### Primary Navigable Entities

These are entities that have their own dedicated screens:

| Entity | Primary Screen | Navigation Pattern |
|--------|---------------|-------------------|
| Camera | Camera View | List → Detail |
| Violation | Violation Detail | List → Detail |
| User | User Detail | List → Detail (Admin only) |

### Contextual/Embedded Entities

These appear within other screens but are not directly navigable:

| Entity | Appears In | Presentation |
|--------|-----------|--------------|
| Evidence | Violation Detail | Inline viewer |
| AI Status | Camera View, Overview | Status indicator |
| Analytics | Reports Dashboard | Charts and cards |

### Hidden Entities (System Internals)

These exist in the backend but are **never exposed** in the UI:

| Entity | Reason for Hiding |
|--------|-------------------|
| Event | Internal aggregation; operators see Violations |
| Stream | VAS abstraction; operators see "Camera" |
| Model Version | Technical detail; operators see "Fall Detection: Active" |
| Frame | Internal pipeline; not user-relevant |
| Service/Pod | Infrastructure; operators see "System: Healthy" |

---

## Global vs. Contextual Navigation

### Global Navigation

Always visible regardless of current screen:

| Element | Location | Behavior |
|---------|----------|----------|
| Primary Nav Bar | Top | Section switching |
| Alert Badge | Nav Bar (Alerts item) | Shows count of open violations |
| User Menu | Top-right | Profile, logout |
| System Status Indicator | Top-right or footer | Healthy/Degraded/Offline |

### System Status Click Behavior by Persona

The global System Status indicator is visible to all personas, but click behavior differs:

| Persona | Click System Status | Result |
|---------|---------------------|--------|
| **Operator** | Opens read-only modal | "System Degraded — Contact your supervisor or administrator" |
| **Supervisor** | Opens read-only modal | "System Degraded — Contact administrator for details" |
| **Admin** | Deep link | Navigates to Settings > System Health |

**Rationale:** Operators and Supervisors need to know *that* the system is degraded, but cannot fix it. The modal provides awareness without false agency. Admins can take action, so they navigate to the health dashboard.

### Contextual Navigation

Appears only within specific screens:

| Context | Element | Appears When |
|---------|---------|--------------|
| Camera View | "View Violations" link | Camera has violations |
| Violation Detail | "View Camera" link | Always |
| Violations List | Filter sidebar | Always |
| Settings | Sidebar | Within Settings section |

### Breadcrumb Strategy

Breadcrumbs appear for nested navigation:

```
Cameras > Front Door Camera > Settings
Alerts > Violation #12345
Settings > User Management > John Doe
```

**Breadcrumb Rules:**
- Always show for depth > 1
- Section name is always first
- Entity name (camera, violation, user) is human-readable
- Settings uses sidebar, not breadcrumbs, for sub-navigation

---

## Context Preservation Rules

### When Navigating Between Sections

| From | To | Context Preserved |
|------|-----|-------------------|
| Camera View | Violations (filtered) | Camera filter auto-applied |
| Violation Detail | Camera View | Scrolls to relevant camera |
| Analytics Chart | Violations | Time range and camera filter |
| Any | Overview | No filter (fresh view) |

### When Navigating Within a Section

| Action | Behavior |
|--------|----------|
| List → Detail | Back returns to list with scroll position |
| Search → Results → Detail | Back returns to results, not search |
| Apply filter | URL reflects filter state (bookmarkable) |

### Deep Linking Support

All screens support direct URL access:
- `/cameras/abc123` → Opens Camera View for camera abc123
- `/alerts/def456` → Opens Violation Detail for violation def456
- `/alerts?camera=abc123&status=open` → Opens Violations with filters

---

## Role-Based Visibility Summary

### Navigation Visibility Matrix

| Navigation Item | Operator | Supervisor | Admin |
|-----------------|----------|------------|-------|
| Overview | ✓ | ✓ | ✓ |
| Cameras | ✓ | ✓ | ✓ |
| Violations | ✓ | ✓ | — (can access via deep link) |
| Analytics | — | ✓ | ✓ |
| Settings | — | — | ✓ |

### Section Behavior by Role

| Section | Operator Behavior | Supervisor Behavior | Admin Behavior |
|---------|------------------|--------------------|--------------------|
| Overview | Full access | Full access | Full access |
| Cameras | View only | View only | View + Settings |
| Violations | Action (acknowledge, dismiss, escalate) + filter all statuses | Action (resolve, override) + filter all statuses | View only (no actions) |
| Analytics | Hidden | Full access | Full access |
| Settings | Hidden | Hidden | Full access |

### Permission Enforcement

| Attempt | Response |
|---------|----------|
| Operator navigates to `/reports` | Redirect to Overview |
| Operator navigates to `/settings` | 403 page or redirect |
| Supervisor navigates to `/settings` | 403 page or redirect |
| Deep link to forbidden screen | 403 with "Contact Admin" message |

---

## Sitemap Diagram

### Complete Site Structure

```
Ruth AI Application
│
├── Overview (/)
│   └── Dashboard
│       ├── Violation Summary (badge)
│       ├── Camera Summary
│       ├── System Status
│       └── Recent Violations
│
├── Cameras (/cameras)
│   ├── Camera List
│   │   └── Camera View (/cameras/:id)
│   │       ├── Live Video [embedded]
│   │       ├── Detection Status [embedded]
│   │       ├── Camera Detail (/cameras/:id/detail)
│   │       │   └── Recent Violations [contextual]
│   │       └── Camera Settings (/cameras/:id/settings) [Admin]
│   │           ├── AI Enable/Disable
│   │           └── Confidence Threshold
│
├── Violations (/alerts) [Operator, Supervisor]
│   ├── Violations List
│   │   ├── Filter Sidebar
│   │   │   ├── Status (open, reviewed, dismissed, resolved)
│   │   │   ├── Date Range
│   │   │   ├── Camera Filter
│   │   │   └── Confidence Filter
│   │   └── Quick Actions (inline)
│   └── Violation Detail (/alerts/:id)
│       ├── Violation Info
│       ├── Evidence Viewer [embedded]
│       │   ├── Snapshot
│       │   └── Video Clip
│       └── Actions
│           ├── Acknowledge [Operator]
│           ├── Dismiss [Operator, Supervisor]
│           ├── Escalate [Operator]
│           └── Resolve [Supervisor]
│
├── Analytics (/analytics) [Supervisor, Admin]
│   ├── Analytics Dashboard
│   │   ├── Summary Cards
│   │   ├── Time Series Chart
│   │   └── Camera Breakdown
│   ├── Camera Performance (/analytics/cameras)
│   │   └── Per-Camera Stats
│   └── Export Data (/analytics/export)
│       └── CSV Export
│
└── Settings (/settings) [Admin only]
    ├── General Settings
    │   └── Application Config
    ├── Camera Management (/settings/cameras)
    │   └── Camera Config Detail (/settings/cameras/:id)
    │       ├── AI Enable/Disable
    │       ├── Confidence Threshold
    │       └── Detection Model
    ├── AI Configuration (/settings/ai)
    │   ├── Global Thresholds
    │   └── Model Settings
    ├── User Management (/settings/users)
    │   └── User Detail (/settings/users/:id)
    │       ├── Role Assignment
    │       └── Permissions
    ├── System Health (/settings/health)
    │   ├── Service Status
    │   │   ├── Backend: Healthy/Degraded/Offline
    │   │   ├── AI Runtime: Healthy/Degraded/Offline
    │   │   └── Video Service: Healthy/Degraded/Offline
    │   └── AI Model Status
    │       └── Fall Detection: Active/Paused/Error
    └── Audit Log (/settings/audit)
        ├── Search/Filter
        └── Action History
```

### Simplified View (Top Two Levels)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                               RUTH AI                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Overview ─────────┬─── Dashboard                                           │
│                    │                                                        │
│  Cameras ──────────┼─── Camera List                                         │
│                    │    └── Camera View                                     │
│                    │        └── Camera Settings [Admin]                     │
│                    │                                                        │
│  Violations ───────┼─── Violations List (with comprehensive filters)        │
│  [Operator/Supervisor] └── Violation Detail                                 │
│                    │                                                        │
│  Analytics ────────┼─── Analytics Dashboard                                 │
│  [Supervisor/Admin]│    ├── Camera Performance                              │
│                    │    └── Export Data                                     │
│                    │                                                        │
│  Settings ─────────┼─── General Settings                                    │
│  [Admin only]      │    ├── Camera Management                               │
│                    │    ├── AI Configuration                                │
│                    │    ├── User Management                                 │
│                    │    ├── System Health                                   │
│                    │    └── Audit Log                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Future Extensibility Notes

This IA is designed to accommodate future additions without restructuring:

| Future Feature | Fits In | Impact |
|----------------|---------|--------|
| New AI model (e.g., intrusion detection) | Cameras, Alerts, Settings | Adds filter option, new violation type |
| Real-time notifications | Global | Adds notification bell to nav bar |
| Multi-site support | Overview, Cameras | Adds site filter globally |
| Advanced analytics | Reports | Adds new sub-screens |
| API key management | Settings | Adds new sub-screen |
| Mobile app | All | Same IA, responsive layout |

---

## Deferred Decisions

The following UX concerns are **intentionally deferred** to later tasks (F3/F4) and are not addressed in this IA document:

| Deferred Topic | Reason | Target Task |
|----------------|--------|-------------|
| **Empty states** | Requires wireframe-level detail | F3: UX Principles |
| **Zero cameras** | Edge case UX, not structural | F4: Operator Workflows |
| **Zero violations** | Edge case UX, not structural | F4: Operator Workflows |
| **AI disabled everywhere** | Configuration edge case | F4: Admin Workflows |
| **First-run experience** | Onboarding flow design | F5: Onboarding (future) |
| **Error message copy** | Microcopy, not structure | F3: UX Principles |
| **Loading states** | Visual design, not structure | F3: UX Principles |

This prevents claims that the IA is incomplete. Structure is complete; edge case UX is deferred.

---

## Validation Checklist

Before freezing this document, verify:

- [x] Every screen from API contract has a UI location
- [x] All persona capabilities have corresponding screens
- [x] No persona sees hidden entities (Events, Streams, Models internals)
- [x] Navigation depth is ≤3 for Operators
- [x] Admin-only sections are completely hidden from other roles
- [x] Deep linking is supported for all screens
- [x] Context preservation rules are explicit
- [x] Sitemap is consistent with screen inventory
- [x] Violations page provides unified access to all violation statuses (no separate History)
- [x] System Status click behavior defined per persona
- [x] "No Models section" decision documented
- [x] "No History section" decision documented (filters replace separate page)
- [x] Deferred decisions are explicitly listed

---

**End of Document**

*This document is a frozen input for all subsequent UX wireframe and workflow tasks.*
