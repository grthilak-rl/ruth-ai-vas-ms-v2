# Ruth AI — Screen Wireframes (Low-Fidelity)

| Meta             | Value                                      |
|------------------|--------------------------------------------|
| Document ID      | RUTH-UX-F4                                 |
| Version          | 1.0                                        |
| Status           | Draft                                      |
| Owner            | Frontend UX Designer Agent                 |
| Input Documents  | F1 (Personas), F2 (IA), F3 (UX Flows)      |
| Output           | Low-fidelity wireframes for all screens    |

---

## 1. Document Purpose

This document provides **low-fidelity wireframes** for all Ruth AI screens identified in F2 (Information Architecture). Each wireframe includes:

- **Default State** — Normal operation with data
- **Loading State** — Data being fetched
- **Empty State** — No data available
- **Error State** — System/network failure
- **Degraded State** — Partial functionality (where applicable)

Wireframes use ASCII/text representation suitable for developer handoff without graphic design tooling.

---

## 2. Design Principles (Applied)

From F1 (Personas) and F3 (UX Flows):

| Principle | Application in Wireframes |
|-----------|---------------------------|
| **Glanceable** | Key metrics visible without scrolling |
| **Confidence = Categorical** | Always "High/Medium/Low", never numeric |
| **Violation-Centric** | Violations are primary data object |
| **Role-Gated** | Admin sections clearly marked |
| **Failure-Visible** | System status always in header |
| **No Infrastructure Noise** | No ports, endpoints, internal IDs |

---

## 3. Global Layout Structure

All screens share this layout:

```
┌─────────────────────────────────────────────────────────────────┐
│  [Logo]   Ruth AI                    [System Status] [User ▼]   │
├─────────────────────────────────────────────────────────────────┤
│  ┌────────────┐                                                 │
│  │ Overview   │  ← Active tab highlighted                       │
│  ├────────────┤                                                 │
│  │ Cameras    │                                                 │
│  ├────────────┤                                                 │
│  │ Violations │  ← Badge shows open count                       │
│  ├────────────┤                                                 │
│  │ Analytics  │  ← Hidden for Operator                          │
│  ├────────────┤                                                 │
│  │ Settings   │  ← Hidden for Operator/Supervisor               │
│  └────────────┘                                                 │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │                    CONTENT AREA                             ││
│  │                                                             ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### Header Components

```
┌─────────────────────────────────────────────────────────────────┐
│  [●] Ruth AI                [● All Systems OK]    [J. Smith ▼]  │
└─────────────────────────────────────────────────────────────────┘
```

**System Status Indicator States:**
- `[● All Systems OK]` — Green dot, all models healthy
- `[◐ Degraded]` — Yellow dot, some models unhealthy
- `[○ Offline]` — Red dot, critical failure

**System Status Click Behavior (per F2):**
| Persona    | Click Action                    |
|------------|---------------------------------|
| Operator   | Opens modal with summary        |
| Supervisor | Opens modal with summary        |
| Admin      | Deep link to Runtime Health     |

---

## 4. Screen 1: Main Dashboard (Overview)

**URL:** `/overview`
**Primary Personas:** Operator, Supervisor
**Purpose:** Glanceable summary of system state and recent activity

### 4.1 Default State (With Data)

```
┌─────────────────────────────────────────────────────────────────┐
│  OVERVIEW                                        Last: 10s ago  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   OPEN ALERTS   │  │  CAMERAS LIVE   │  │  MODELS ACTIVE  │  │
│  │                 │  │                 │  │                 │  │
│  │       12        │  │     8 / 10      │  │     3 / 3       │  │
│  │                 │  │                 │  │                 │  │
│  │  [View All →]   │  │  [View All →]   │  │  (info hover)   │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  RECENT VIOLATIONS                            [View All →]  ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │  ● Fall Detected        Lobby Cam       High      2m ago    ││
│  │  ● PPE Missing          Loading Dock    Medium    5m ago    ││
│  │  ● Unauthorized Entry   Gate A          High      8m ago    ││
│  │  ● Fall Detected        Warehouse 2     Low       12m ago   ││
│  │  ● PPE Missing          Entrance        Medium    15m ago   ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌──────────────────────────────┐ ┌────────────────────────────┐│
│  │  TODAY'S SUMMARY             │ │  CAMERA GRID (2x2)         ││
│  │                              │ │  ┌──────┐ ┌──────┐         ││
│  │  Total Violations: 47        │ │  │ Cam1 │ │ Cam2 │         ││
│  │  Reviewed:         35        │ │  │ ●    │ │ ●    │         ││
│  │  Pending:          12        │ │  └──────┘ └──────┘         ││
│  │                              │ │  ┌──────┐ ┌──────┐         ││
│  │  By Type:                    │ │  │ Cam3 │ │ Cam4 │         ││
│  │  - Fall: 15                  │ │  │ ●    │ │ ○    │ ← Offline││
│  │  - PPE: 22                   │ │  └──────┘ └──────┘         ││
│  │  - Access: 10                │ │                            ││
│  └──────────────────────────────┘ └────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Annotations:**
- `Open Alerts` card links to Alerts page
- `Cameras Live` shows active/total ratio
- `Models Active` shows info on hover (no click for Operator/Supervisor)
- Recent Violations list shows last 5, newest first
- Confidence shown as words (High/Medium/Low), never percentages
- `●` = live indicator, `○` = offline indicator

### 4.2 Loading State

```
┌─────────────────────────────────────────────────────────────────┐
│  OVERVIEW                                        Loading...     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   OPEN ALERTS   │  │  CAMERAS LIVE   │  │  MODELS ACTIVE  │  │
│  │                 │  │                 │  │                 │  │
│  │    ░░░░░░░      │  │    ░░░░░░░      │  │    ░░░░░░░      │  │
│  │   (loading)     │  │   (loading)     │  │   (loading)     │  │
│  │                 │  │                 │  │                 │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  RECENT VIOLATIONS                                          ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Skeleton loaders shown for each card
- No spinners on entire page (cards load independently)
- Header remains interactive

### 4.3 Empty State (No Violations Today)

```
┌─────────────────────────────────────────────────────────────────┐
│  OVERVIEW                                        Last: 10s ago  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   OPEN ALERTS   │  │  CAMERAS LIVE   │  │  MODELS ACTIVE  │  │
│  │                 │  │                 │  │                 │  │
│  │        0        │  │     8 / 10      │  │     3 / 3       │  │
│  │                 │  │                 │  │                 │  │
│  │                 │  │  [View All →]   │  │                 │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  RECENT VIOLATIONS                                          ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │                                                             ││
│  │              ┌─────────────────────────┐                    ││
│  │              │                         │                    ││
│  │              │    No violations yet    │                    ││
│  │              │    today. All clear!    │                    ││
│  │              │                         │                    ││
│  │              └─────────────────────────┘                    ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Zero shown in Open Alerts (not hidden)
- Friendly message in violations list
- No "Add Violation" button (violations come from AI, not user)

### 4.4 Error State (API Failure)

```
┌─────────────────────────────────────────────────────────────────┐
│  OVERVIEW                                        ⚠ Error        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │     ┌─────────────────────────────────────────────────┐     ││
│  │     │                                                 │     ││
│  │     │   ⚠  Unable to load dashboard data             │     ││
│  │     │                                                 │     ││
│  │     │   Could not connect to Ruth AI services.       │     ││
│  │     │   This may be a temporary issue.               │     ││
│  │     │                                                 │     ││
│  │     │              [ Retry ]                          │     ││
│  │     │                                                 │     ││
│  │     └─────────────────────────────────────────────────┘     ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Single retry button
- No technical details (no "500 error", no endpoints)
- Error message is actionable ("may be temporary")

### 4.5 Degraded State (Some Data Available)

```
┌─────────────────────────────────────────────────────────────────┐
│  OVERVIEW                                        Last: 10s ago  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   OPEN ALERTS   │  │  CAMERAS LIVE   │  │  MODELS ACTIVE  │  │
│  │                 │  │                 │  │   ⚠ Degraded    │  │
│  │       12        │  │     8 / 10      │  │                 │  │
│  │                 │  │                 │  │     2 / 3       │  │
│  │  [View All →]   │  │  [View All →]   │  │  1 model down   │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  ⚠ Fall Detection model is currently unavailable.          ││
│  │    Falls will not be detected until the model recovers.    ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  RECENT VIOLATIONS                            [View All →]  ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │  ● PPE Missing          Loading Dock    Medium    5m ago    ││
│  │  ● Unauthorized Entry   Gate A          High      8m ago    ││
│  │  ...                                                        ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Yellow warning banner explains what's affected
- User understands capability gap ("falls will not be detected")
- Rest of dashboard remains functional
- Models card shows degraded indicator

---

## 5. Screen 2: Live Events View (Alerts List)

**URL:** `/alerts`
**Primary Personas:** Operator, Supervisor
**Purpose:** View and triage unreviewed violations

### 5.1 Default State (With Alerts)

```
┌─────────────────────────────────────────────────────────────────┐
│  ALERTS (12 Unreviewed)                          [Filter ▼]     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Filter by: [All Types ▼] [All Cameras ▼] [All Confidence ▼]   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ ● HIGH │ Fall Detected                                      ││
│  │        │ Lobby Camera • 2 minutes ago                       ││
│  │        │ Confidence: High                                   ││
│  │        │ [View Details] [Mark Reviewed] [Dismiss]           ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │ ● MED  │ PPE Violation - No Helmet                          ││
│  │        │ Loading Dock Cam • 5 minutes ago                   ││
│  │        │ Confidence: Medium                                 ││
│  │        │ [View Details] [Mark Reviewed] [Dismiss]           ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │ ● HIGH │ Unauthorized Entry                                 ││
│  │        │ Gate A Camera • 8 minutes ago                      ││
│  │        │ Confidence: High                                   ││
│  │        │ [View Details] [Mark Reviewed] [Dismiss]           ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │ ● LOW  │ Fall Detected                                      ││
│  │        │ Warehouse 2 Cam • 12 minutes ago                   ││
│  │        │ Confidence: Low                                    ││
│  │        │ [View Details] [Mark Reviewed] [Dismiss]           ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  Showing 1-10 of 12                    [← Prev] [1] [2] [Next →]│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Annotations:**
- Color-coded severity: HIGH (red), MED (yellow), LOW (gray)
- Confidence always as word, never percentage
- Actions: View Details, Mark Reviewed, Dismiss
- Per F3: "Dismiss" requires confirmation
- Per F2: Status changes reflected via filters (no separate History page)

### 5.2 Loading State

```
┌─────────────────────────────────────────────────────────────────┐
│  ALERTS                                          Loading...     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Filter by: [All Types ▼] [All Cameras ▼] [All Confidence ▼]   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 Empty State (No Unreviewed Alerts)

```
┌─────────────────────────────────────────────────────────────────┐
│  ALERTS (0 Unreviewed)                           [Filter ▼]     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Filter by: [All Types ▼] [All Cameras ▼] [All Confidence ▼]   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │              ┌─────────────────────────────┐                ││
│  │              │                             │                ││
│  │              │   ✓ All caught up!          │                ││
│  │              │                             │                ││
│  │              │   No open alerts.           │                ││
│  │              │   Use status filter to      │                ││
│  │              │   view past violations.     │                ││
│  │              │                             │                ││
│  │              └─────────────────────────────┘                ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Clear positive message
- Guides user to use status filters for reviewed/dismissed violations
- All violation statuses accessible from same page

### 5.4 Error State

```
┌─────────────────────────────────────────────────────────────────┐
│  ALERTS                                          ⚠ Error        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │     ┌─────────────────────────────────────────────────┐     ││
│  │     │                                                 │     ││
│  │     │   ⚠  Unable to load alerts                     │     ││
│  │     │                                                 │     ││
│  │     │   Could not retrieve alert data.               │     ││
│  │     │   Please try again.                            │     ││
│  │     │                                                 │     ││
│  │     │              [ Retry ]                          │     ││
│  │     │                                                 │     ││
│  │     └─────────────────────────────────────────────────┘     ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.5 Filter Applied (No Results)

```
┌─────────────────────────────────────────────────────────────────┐
│  ALERTS (12 Unreviewed)                          [Filter ▼]     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Filter by: [Fall Only ▼] [All Cameras ▼] [High Only ▼]        │
│             ↑ Active                       ↑ Active             │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │              ┌─────────────────────────────┐                ││
│  │              │                             │                ││
│  │              │   No alerts match filters   │                ││
│  │              │                             │                ││
│  │              │   Try adjusting your        │                ││
│  │              │   filter criteria.          │                ││
│  │              │                             │                ││
│  │              │   [Clear Filters]           │                ││
│  │              │                             │                ││
│  │              └─────────────────────────────┘                ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Screen 3: Event / Violation Detail

**URL:** `/alerts/{violation_id}` or Drawer overlay
**Primary Personas:** Operator, Supervisor
**Purpose:** Deep-dive into single violation with evidence

### 6.1 Default State (Full Detail)

```
┌─────────────────────────────────────────────────────────────────┐
│  ← Back to Alerts                                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  VIOLATION DETAIL                                               │
│  ═══════════════                                                │
│                                                                 │
│  ┌────────────────────────────────────────┐ ┌──────────────────┐│
│  │                                        │ │  METADATA        ││
│  │                                        │ │                  ││
│  │         [ Snapshot Image ]             │ │  Type:           ││
│  │                                        │ │  Fall Detected   ││
│  │         ┌─────────────────┐            │ │                  ││
│  │         │  ▶ Play Clip    │            │ │  Camera:         ││
│  │         └─────────────────┘            │ │  Lobby Camera    ││
│  │                                        │ │                  ││
│  │  Timestamp: 2024-01-15 14:32:18        │ │  Confidence:     ││
│  │                                        │ │  High            ││
│  └────────────────────────────────────────┘ │                  ││
│                                             │  Status:         ││
│  ┌────────────────────────────────────────┐ │  ● Unreviewed    ││
│  │  AI DETECTION SUMMARY                  │ │                  ││
│  │                                        │ │  Detected:       ││
│  │  Detection: Person fell in frame       │ │  2 min ago       ││
│  │  Confidence: High                      │ │                  ││
│  │  Model: Fall Detection v2.1            │ └──────────────────┘│
│  │                                        │                     │
│  │  ┌──────────────────────────────────┐  │                     │
│  │  │  Why High Confidence?            │  │                     │
│  │  │  • Clear visibility              │  │                     │
│  │  │  • No occlusion                  │  │                     │
│  │  │  • Motion pattern matched        │  │                     │
│  │  └──────────────────────────────────┘  │                     │
│  └────────────────────────────────────────┘                     │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  ACTIONS                                                    ││
│  │                                                             ││
│  │  [Mark as Reviewed]  [Dismiss with Reason ▼]  [Export]      ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  NOTES (Supervisor only)                                    ││
│  │  ┌─────────────────────────────────────────────────────────┐││
│  │  │                                                         │││
│  │  │  (Add investigation notes here...)                      │││
│  │  │                                                         │││
│  │  └─────────────────────────────────────────────────────────┘││
│  │  [Save Note]                                                ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Annotations:**
- Snapshot/clip from VAS bookmark
- AI detection summary with confidence explanation
- Model version shown (per F3: user knows which model)
- Notes section visible to Supervisor only (per F1)
- Per F3: Dismiss requires reason selection

### 6.2 Loading State

```
┌─────────────────────────────────────────────────────────────────┐
│  ← Back to Alerts                                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  VIOLATION DETAIL                                               │
│  ═══════════════                                                │
│                                                                 │
│  ┌────────────────────────────────────────┐ ┌──────────────────┐│
│  │                                        │ │  METADATA        ││
│  │                                        │ │                  ││
│  │         ░░░░░░░░░░░░░░░░░░░            │ │  ░░░░░░░░░░░     ││
│  │         ░░░░░░░░░░░░░░░░░░░            │ │  ░░░░░░░░░░░     ││
│  │         ░░░░░░░░░░░░░░░░░░░            │ │  ░░░░░░░░░░░     ││
│  │         ░░░░░░░░░░░░░░░░░░░            │ │  ░░░░░░░░░░░     ││
│  │         ░░░░░░░░░░░░░░░░░░░            │ │  ░░░░░░░░░░░     ││
│  │                                        │ │                  ││
│  └────────────────────────────────────────┘ └──────────────────┘│
│                                                                 │
│  Loading violation details...                                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.3 Error State (Violation Not Found)

```
┌─────────────────────────────────────────────────────────────────┐
│  ← Back to Alerts                                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │     ┌─────────────────────────────────────────────────┐     ││
│  │     │                                                 │     ││
│  │     │   ⚠  Violation not found                       │     ││
│  │     │                                                 │     ││
│  │     │   This violation may have been deleted         │     ││
│  │     │   or you don't have access to view it.         │     ││
│  │     │                                                 │     ││
│  │     │         [← Return to Alerts]                    │     ││
│  │     │                                                 │     ││
│  │     └─────────────────────────────────────────────────┘     ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.4 Error State (Media Unavailable)

```
┌─────────────────────────────────────────────────────────────────┐
│  ← Back to Alerts                                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  VIOLATION DETAIL                                               │
│  ═══════════════                                                │
│                                                                 │
│  ┌────────────────────────────────────────┐ ┌──────────────────┐│
│  │                                        │ │  METADATA        ││
│  │    ┌────────────────────────────┐      │ │                  ││
│  │    │                            │      │ │  Type:           ││
│  │    │  ⚠ Media unavailable      │      │ │  Fall Detected   ││
│  │    │                            │      │ │                  ││
│  │    │  The snapshot/clip for     │      │ │  Camera:         ││
│  │    │  this violation could not  │      │ │  Lobby Camera    ││
│  │    │  be loaded. Recording may  │      │ │                  ││
│  │    │  have expired.             │      │ │  Confidence:     ││
│  │    │                            │      │ │  High            ││
│  │    │  [Retry]                   │      │ │                  ││
│  │    └────────────────────────────┘      │ │  ...             ││
│  │                                        │ │                  ││
│  └────────────────────────────────────────┘ └──────────────────┘│
│                                                                 │
│  (Rest of violation detail still shown)                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Media failure doesn't block viewing metadata
- Clear explanation of why media unavailable
- Retry available

### 6.5 Dismiss Confirmation Dialog

```
┌─────────────────────────────────────────────────────────────────┐
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    DISMISS VIOLATION                        ││
│  │                                                             ││
│  │  Are you sure you want to dismiss this alert?               ││
│  │                                                             ││
│  │  Select a reason:                                           ││
│  │  ┌─────────────────────────────────────────────────────────┐││
│  │  │ ○ False Positive - AI error                             │││
│  │  │ ○ Already Handled - Addressed offline                   │││
│  │  │ ○ Test/Training - Not a real incident                   │││
│  │  │ ○ Other: [________________________]                     │││
│  │  └─────────────────────────────────────────────────────────┘││
│  │                                                             ││
│  │  Note: Dismissed violations can be found using the          ││
│  │  "Dismissed" status filter and cannot be un-dismissed.      ││
│  │                                                             ││
│  │                    [Cancel]    [Dismiss]                    ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. Screen 4: Camera Overview

**URL:** `/cameras`
**Primary Personas:** Operator, Supervisor, Admin
**Purpose:** View all cameras and their current status

### 7.1 Default State (Grid View)

```
┌─────────────────────────────────────────────────────────────────┐
│  CAMERAS (8 Active, 2 Offline)           [Grid ◉] [List ○]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Filter: [All Status ▼] [All Locations ▼]        [Search 🔍]   │
│                                                                 │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐   │
│  │ ┌─────────────┐ │ │ ┌─────────────┐ │ │ ┌─────────────┐ │   │
│  │ │             │ │ │ │             │ │ │ │             │ │   │
│  │ │  Live Feed  │ │ │ │  Live Feed  │ │ │ │  Live Feed  │ │   │
│  │ │  Thumbnail  │ │ │ │  Thumbnail  │ │ │ │  Thumbnail  │ │   │
│  │ │             │ │ │ │             │ │ │ │             │ │   │
│  │ └─────────────┘ │ │ └─────────────┘ │ │ └─────────────┘ │   │
│  │ ● Lobby Camera  │ │ ● Loading Dock  │ │ ● Gate A        │   │
│  │   3 violations  │ │   1 violation   │ │   2 violations  │   │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘   │
│                                                                 │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐   │
│  │ ┌─────────────┐ │ │ ┌─────────────┐ │ │ ┌─────────────┐ │   │
│  │ │             │ │ │ │             │ │ │ │   OFFLINE   │ │   │
│  │ │  Live Feed  │ │ │ │  Live Feed  │ │ │ │             │ │   │
│  │ │  Thumbnail  │ │ │ │  Thumbnail  │ │ │ │   ○ ○ ○     │ │   │
│  │ │             │ │ │ │             │ │ │ │             │ │   │
│  │ └─────────────┘ │ │ └─────────────┘ │ │ └─────────────┘ │   │
│  │ ● Warehouse 1   │ │ ● Warehouse 2   │ │ ○ Parking Lot   │   │
│  │   0 violations  │ │   1 violation   │ │   Last: 2h ago  │   │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘   │
│                                                                 │
│  Showing 1-6 of 10                       [← Prev] [Next →]      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Annotations:**
- `●` = live, `○` = offline
- Violation count is today's count for that camera
- Click camera card → Camera Detail view
- Grid/List toggle for user preference

### 7.2 List View

```
┌─────────────────────────────────────────────────────────────────┐
│  CAMERAS (8 Active, 2 Offline)           [Grid ○] [List ◉]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Filter: [All Status ▼] [All Locations ▼]        [Search 🔍]   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Status │ Camera Name    │ Location    │ Violations │ Models ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │   ●    │ Lobby Camera   │ Building A  │     3      │ 3/3    ││
│  │   ●    │ Loading Dock   │ Warehouse   │     1      │ 3/3    ││
│  │   ●    │ Gate A         │ Perimeter   │     2      │ 2/3    ││
│  │   ●    │ Warehouse 1    │ Warehouse   │     0      │ 3/3    ││
│  │   ●    │ Warehouse 2    │ Warehouse   │     1      │ 3/3    ││
│  │   ○    │ Parking Lot    │ External    │     -      │ -      ││
│  │   ○    │ Back Entrance  │ Building A  │     -      │ -      ││
│  │   ●    │ Main Entrance  │ Building A  │     0      │ 3/3    ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.3 Camera Detail (Click-through)

```
┌─────────────────────────────────────────────────────────────────┐
│  ← Back to Cameras                                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  LOBBY CAMERA                                      ● Live       │
│  ════════════                                                   │
│                                                                 │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                                                            │ │
│  │                                                            │ │
│  │                   [ LIVE VIDEO FEED ]                      │ │
│  │                                                            │ │
│  │                                                            │ │
│  │                                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─────────────────────────┐  ┌──────────────────────────────┐  │
│  │  CAMERA INFO            │  │  ACTIVE MODELS               │  │
│  │                         │  │                              │  │
│  │  Location: Building A   │  │  ● Fall Detection    v2.1    │  │
│  │  Stream: Active         │  │  ● PPE Detection     v1.3    │  │
│  │  Resolution: 1080p      │  │  ● Access Control    v1.0    │  │
│  │  FPS: 30                │  │                              │  │
│  └─────────────────────────┘  └──────────────────────────────┘  │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  TODAY'S VIOLATIONS FROM THIS CAMERA              [View All]││
│  ├─────────────────────────────────────────────────────────────┤│
│  │  ● Fall Detected         High        14:32    [View →]      ││
│  │  ● PPE Missing           Medium      12:15    [View →]      ││
│  │  ● Fall Detected         Low         09:45    [View →]      ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.4 Loading State

```
┌─────────────────────────────────────────────────────────────────┐
│  CAMERAS                                         Loading...     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐   │
│  │ ░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░ │   │
│  │ ░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░ │   │
│  │ ░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░ │   │
│  │ ░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░ │   │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.5 Empty State (No Cameras Configured)

```
┌─────────────────────────────────────────────────────────────────┐
│  CAMERAS                                                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │              ┌─────────────────────────────┐                ││
│  │              │                             │                ││
│  │              │   No cameras configured     │                ││
│  │              │                             │                ││
│  │              │   Contact your admin to     │                ││
│  │              │   add cameras to the        │                ││
│  │              │   system.                   │                ││
│  │              │                             │                ││
│  │              └─────────────────────────────┘                ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Note:** Per F1, Operators/Supervisors cannot add cameras. Admin-only action.

### 7.6 Error State

```
┌─────────────────────────────────────────────────────────────────┐
│  CAMERAS                                         ⚠ Error        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │     ┌─────────────────────────────────────────────────┐     ││
│  │     │                                                 │     ││
│  │     │   ⚠  Unable to load cameras                    │     ││
│  │     │                                                 │     ││
│  │     │   Could not retrieve camera list.              │     ││
│  │     │                                                 │     ││
│  │     │              [ Retry ]                          │     ││
│  │     │                                                 │     ││
│  │     └─────────────────────────────────────────────────┘     ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. Screen 5: Model & Version Status (Admin-Only)

**URL:** `/settings/models`
**Primary Persona:** Admin
**Purpose:** View deployed AI models, versions, and health

### 8.1 Default State

```
┌─────────────────────────────────────────────────────────────────┐
│  SETTINGS > MODEL STATUS                      [Admin Only]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  AI MODELS                                   Last sync: 30s ago │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  Model              │ Version │ Status  │ Cameras │ Health  ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │  Fall Detection     │ v2.1.0  │ ● Active│  8/10   │ Healthy ││
│  │  PPE Detection      │ v1.3.2  │ ● Active│  10/10  │ Healthy ││
│  │  Access Control     │ v1.0.1  │ ● Active│  5/10   │ Healthy ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  FALL DETECTION - EXPANDED                          [▼]     ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │                                                             ││
│  │  Model ID:        fall-detection                            ││
│  │  Current Version: v2.1.0                                    ││
│  │  Deployed:        2024-01-10 09:00                          ││
│  │  Status:          ● Running                                 ││
│  │                                                             ││
│  │  Capabilities:                                              ││
│  │  - Detects: Person falls, near-falls                        ││
│  │  - Min confidence threshold: 0.7                            ││
│  │  - Frame rate: 5 FPS                                        ││
│  │                                                             ││
│  │  Assigned Cameras:                                          ││
│  │  ┌───────────────────────────────────────────────────────┐  ││
│  │  │ ● Lobby Camera    ● Loading Dock    ● Gate A          │  ││
│  │  │ ● Warehouse 1     ● Warehouse 2     ● Main Entrance   │  ││
│  │  │ ● Back Entrance   ● Conference      ○ Parking (off)   │  ││
│  │  └───────────────────────────────────────────────────────┘  ││
│  │                                                             ││
│  │  Recent Performance (24h):                                  ││
│  │  - Inferences: 45,230                                       ││
│  │  - Detections: 15                                           ││
│  │  - Avg latency: 45ms                                        ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Annotations:**
- Admin-only badge visible
- Model details expandable
- Per F1: Admin sees model internals that Operator/Supervisor don't
- Version numbers, deployment dates, performance metrics
- No "Deploy New Model" button (per F3: deployment is external)

### 8.2 Loading State

```
┌─────────────────────────────────────────────────────────────────┐
│  SETTINGS > MODEL STATUS                      [Admin Only]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  AI MODELS                                   Loading...         │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 8.3 Degraded State (Model Unhealthy)

```
┌─────────────────────────────────────────────────────────────────┐
│  SETTINGS > MODEL STATUS                      [Admin Only]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  ⚠ 1 model requires attention                               ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  AI MODELS                                   Last sync: 30s ago │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  Model              │ Version │ Status  │ Cameras │ Health  ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │  Fall Detection     │ v2.1.0  │ ⚠ Degraded│ 8/10  │ Warning ││
│  │  PPE Detection      │ v1.3.2  │ ● Active│  10/10  │ Healthy ││
│  │  Access Control     │ v1.0.1  │ ● Active│  5/10   │ Healthy ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  ⚠ FALL DETECTION - HEALTH ISSUE                    [▼]     ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │                                                             ││
│  │  Status: ⚠ Degraded                                         ││
│  │  Issue:  High latency detected (avg 250ms, threshold 100ms) ││
│  │  Since:  2024-01-15 13:45                                   ││
│  │                                                             ││
│  │  Impact:                                                    ││
│  │  - Detection may be delayed                                 ││
│  │  - Some frames may be skipped                               ││
│  │                                                             ││
│  │  Recommended Action:                                        ││
│  │  - Check AI Runtime resource utilization                    ││
│  │  - Consider reducing assigned camera count                  ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 8.4 Error State

```
┌─────────────────────────────────────────────────────────────────┐
│  SETTINGS > MODEL STATUS                      [Admin Only]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │     ┌─────────────────────────────────────────────────┐     ││
│  │     │                                                 │     ││
│  │     │   ⚠  Unable to load model status               │     ││
│  │     │                                                 │     ││
│  │     │   Could not connect to AI Runtime.             │     ││
│  │     │                                                 │     ││
│  │     │              [ Retry ]                          │     ││
│  │     │                                                 │     ││
│  │     └─────────────────────────────────────────────────┘     ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 8.5 Empty State (No Models Deployed)

```
┌─────────────────────────────────────────────────────────────────┐
│  SETTINGS > MODEL STATUS                      [Admin Only]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │              ┌─────────────────────────────┐                ││
│  │              │                             │                ││
│  │              │   No AI models deployed     │                ││
│  │              │                             │                ││
│  │              │   Models are deployed via   │                ││
│  │              │   the AI Runtime system.    │                ││
│  │              │   Contact platform team     │                ││
│  │              │   to add models.            │                ││
│  │              │                             │                ││
│  │              └─────────────────────────────┘                ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. Screen 6: Runtime Health View (Admin-Only)

**URL:** `/settings/health`
**Primary Persona:** Admin
**Purpose:** Monitor system health, service status, resource usage

### 9.1 Default State (All Healthy)

```
┌─────────────────────────────────────────────────────────────────┐
│  SETTINGS > SYSTEM HEALTH                     [Admin Only]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SYSTEM STATUS: ● All Systems Operational     Last: 15s ago     │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  SERVICE HEALTH                                             ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │                                                             ││
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ ││
│  │  │  RUTH BACKEND   │  │  AI RUNTIME     │  │  VAS         │ ││
│  │  │                 │  │                 │  │              │ ││
│  │  │   ● Healthy     │  │   ● Healthy     │  │  ● Healthy   │ ││
│  │  │                 │  │                 │  │              │ ││
│  │  │  Response: 45ms │  │  Response: 23ms │  │  Resp: 120ms │ ││
│  │  │  Uptime: 99.9%  │  │  Uptime: 99.8%  │  │  Uptime: 99% │ ││
│  │  └─────────────────┘  └─────────────────┘  └──────────────┘ ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  RESOURCE UTILIZATION                                       ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │                                                             ││
│  │  CPU Usage:    [████████░░░░░░░░░░░░]  42%                  ││
│  │  Memory:       [██████████░░░░░░░░░░]  55%                  ││
│  │  GPU (if any): [████████████░░░░░░░░]  65%                  ││
│  │  Disk:         [██████░░░░░░░░░░░░░░]  30%                  ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  RECENT EVENTS                                    [View All]││
│  ├─────────────────────────────────────────────────────────────┤│
│  │  ● System startup completed              2024-01-15 08:00   ││
│  │  ● Model fall-detection loaded           2024-01-15 08:01   ││
│  │  ● Model ppe-detection loaded            2024-01-15 08:01   ││
│  │  ● Model access-control loaded           2024-01-15 08:02   ││
│  │  ● Health check passed                   2024-01-15 14:30   ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 9.2 Degraded State (Service Issue)

```
┌─────────────────────────────────────────────────────────────────┐
│  SETTINGS > SYSTEM HEALTH                     [Admin Only]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SYSTEM STATUS: ⚠ Degraded Performance        Last: 15s ago     │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  ⚠ AI Runtime experiencing high latency                     ││
│  │    Impact: Detection delays possible                        ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  SERVICE HEALTH                                             ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │                                                             ││
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ ││
│  │  │  RUTH BACKEND   │  │  AI RUNTIME     │  │  VAS         │ ││
│  │  │                 │  │   ⚠ DEGRADED    │  │              │ ││
│  │  │   ● Healthy     │  │                 │  │  ● Healthy   │ ││
│  │  │                 │  │  Response: 450ms│  │              │ ││
│  │  │  Response: 45ms │  │  Uptime: 98.5%  │  │  Resp: 120ms │ ││
│  │  │  Uptime: 99.9%  │  │  ↑ High latency │  │  Uptime: 99% │ ││
│  │  └─────────────────┘  └─────────────────┘  └──────────────┘ ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  RESOURCE UTILIZATION                                       ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │                                                             ││
│  │  CPU Usage:    [██████████████████░░]  92%  ⚠ HIGH          ││
│  │  Memory:       [████████████████░░░░]  82%                  ││
│  │  GPU (if any): [████████████████████]  98%  ⚠ HIGH          ││
│  │  Disk:         [██████░░░░░░░░░░░░░░]  30%                  ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 9.3 Critical State (Service Down)

```
┌─────────────────────────────────────────────────────────────────┐
│  SETTINGS > SYSTEM HEALTH                     [Admin Only]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SYSTEM STATUS: ○ Critical Issues             Last: 15s ago     │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  ✖ AI Runtime is not responding                             ││
│  │    Impact: No AI detections are being processed             ││
│  │    Duration: 5 minutes                                      ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  SERVICE HEALTH                                             ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │                                                             ││
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ ││
│  │  │  RUTH BACKEND   │  │  AI RUNTIME     │  │  VAS         │ ││
│  │  │                 │  │    ✖ OFFLINE    │  │              │ ││
│  │  │   ● Healthy     │  │                 │  │  ● Healthy   │ ││
│  │  │                 │  │  Not responding │  │              │ ││
│  │  │  Response: 45ms │  │  Last seen:     │  │  Resp: 120ms │ ││
│  │  │  Uptime: 99.9%  │  │  5 min ago      │  │  Uptime: 99% │ ││
│  │  └─────────────────┘  └─────────────────┘  └──────────────┘ ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  RECENT EVENTS                                    [View All]││
│  ├─────────────────────────────────────────────────────────────┤│
│  │  ✖ AI Runtime connection lost            2024-01-15 14:25   ││
│  │  ⚠ AI Runtime high latency detected      2024-01-15 14:23   ││
│  │  ● Health check passed                   2024-01-15 14:20   ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 9.4 Loading State

```
┌─────────────────────────────────────────────────────────────────┐
│  SETTINGS > SYSTEM HEALTH                     [Admin Only]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SYSTEM STATUS: Loading...                                      │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  SERVICE HEALTH                                             ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  RESOURCE UTILIZATION                                       ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 9.5 Error State

```
┌─────────────────────────────────────────────────────────────────┐
│  SETTINGS > SYSTEM HEALTH                     [Admin Only]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │     ┌─────────────────────────────────────────────────┐     ││
│  │     │                                                 │     ││
│  │     │   ⚠  Unable to load health data                │     ││
│  │     │                                                 │     ││
│  │     │   Could not retrieve system status.            │     ││
│  │     │                                                 │     ││
│  │     │              [ Retry ]                          │     ││
│  │     │                                                 │     ││
│  │     └─────────────────────────────────────────────────┘     ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 10. Screen 7: Error & Edge States (Universal Patterns)

This section defines reusable patterns applied across all screens.

### 10.1 Network Error (Toast)

```
┌─────────────────────────────────────────────────────────────────┐
│  (Any screen content)                                           │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  ⚠ Network error. Some data may be outdated.    [Dismiss]   ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Non-blocking toast at bottom
- Auto-dismiss after 5 seconds
- Manual dismiss available

### 10.2 Session Expired

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │              ┌─────────────────────────────┐                ││
│  │              │                             │                ││
│  │              │   Session Expired           │                ││
│  │              │                             │                ││
│  │              │   Your session has timed    │                ││
│  │              │   out for security.         │                ││
│  │              │                             │                ││
│  │              │   [Log In Again]            │                ││
│  │              │                             │                ││
│  │              └─────────────────────────────┘                ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Full-screen modal, blocks interaction
- Single action: re-authenticate

### 10.3 Permission Denied

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │     ┌─────────────────────────────────────────────────┐     ││
│  │     │                                                 │     ││
│  │     │   🚫  Access Denied                            │     ││
│  │     │                                                 │     ││
│  │     │   You don't have permission to view            │     ││
│  │     │   this page.                                   │     ││
│  │     │                                                 │     ││
│  │     │   [← Go to Dashboard]                           │     ││
│  │     │                                                 │     ││
│  │     └─────────────────────────────────────────────────┘     ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**When shown:**
- Operator/Supervisor navigating to Admin-only routes
- Direct URL access to unauthorized pages

### 10.4 Action Failed (Inline)

```
┌─────────────────────────────────────────────────────────────────┐
│  │ ● HIGH │ Fall Detected                                      │
│  │        │ Lobby Camera • 2 minutes ago                       │
│  │        │                                                    │
│  │        │ ⚠ Could not mark as reviewed. [Retry]              │
│  │        │                                                    │
│  │        │ [View Details] [Mark Reviewed] [Dismiss]           │
└─────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Error shown inline, near the failed action
- Retry immediately available
- Rest of UI remains functional

### 10.5 Partial Load (Graceful Degradation)

```
┌─────────────────────────────────────────────────────────────────┐
│  OVERVIEW                                        Last: 10s ago  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   OPEN ALERTS   │  │  CAMERAS LIVE   │  │  MODELS ACTIVE  │  │
│  │                 │  │                 │  │                 │  │
│  │       12        │  │  ⚠ Load failed  │  │     3 / 3       │  │
│  │                 │  │    [Retry]      │  │                 │  │
│  │  [View All →]   │  │                 │  │                 │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                                                                 │
│  (Rest of page loads normally)                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Individual cards fail independently
- Successful cards still shown
- Retry per-card, not whole page

### 10.6 Stale Data Warning

```
┌─────────────────────────────────────────────────────────────────┐
│  OVERVIEW                                    ⚠ Last: 2 min ago  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  ⚠ Data may be outdated. Unable to refresh.    [Retry Now]  ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  (Shows last known data)                                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Show stale data rather than nothing
- Clear indicator of staleness
- Manual refresh available

### 10.7 First Run / Onboarding Empty States

**No Cameras (First Run):**
```
┌─────────────────────────────────────────────────────────────────┐
│  Welcome to Ruth AI                                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                                                             ││
│  │              ┌─────────────────────────────┐                ││
│  │              │                             │                ││
│  │              │   Getting Started           │                ││
│  │              │                             │                ││
│  │              │   1. Add cameras            │                ││
│  │              │   2. Configure AI models    │                ││
│  │              │   3. Start monitoring       │                ││
│  │              │                             │                ││
│  │              │   [Go to Settings →]        │                ││
│  │              │   (Admin only)              │                ││
│  │              │                             │                ││
│  │              └─────────────────────────────┘                ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**For Non-Admin on First Run:**
```
│              │   System not yet configured   │                ││
│              │                               │                ││
│              │   Contact your administrator  │                ││
│              │   to set up cameras and       │                ││
│              │   AI models.                  │                ││
```

---

## 11. Role-Based Visibility Summary

| Screen / Element | Operator | Supervisor | Admin |
|------------------|----------|------------|-------|
| Main Dashboard | ✓ | ✓ | ✓ |
| Live Events (Violations) | ✓ | ✓ | ✓ |
| Violation Detail | ✓ | ✓ | ✓ |
| Violation Notes Section | ✗ | ✓ | ✓ |
| Camera Overview | ✓ | ✓ | ✓ |
| Camera Configuration | ✗ | ✗ | ✓ |
| Analytics | ✗ | ✓ | ✓ |
| Settings Nav Item | ✗ | ✗ | ✓ |
| Model Status | ✗ | ✗ | ✓ |
| Runtime Health | ✗ | ✗ | ✓ |
| System Status → Deep Link | Modal | Modal | Deep Link |

---

## 12. Interaction Patterns

### 12.1 Click/Tap Targets

| Element | Action | Result |
|---------|--------|--------|
| Alert row | Click | Navigate to Violation Detail |
| Camera card | Click | Navigate to Camera Detail |
| "View All" link | Click | Navigate to full list |
| System Status (header) | Click | Modal (Operator/Supervisor) or Deep Link (Admin) |
| Filter dropdown | Click | Open filter options |
| Pagination | Click | Load next/prev page |

### 12.2 Keyboard Navigation

- Tab order follows visual layout
- Enter activates focused button/link
- Escape closes modals/drawers
- Arrow keys navigate lists (when focused)

### 12.3 Responsive Breakpoints (Conceptual)

| Breakpoint | Layout Change |
|------------|---------------|
| Desktop (>1200px) | Side nav + full content |
| Tablet (768-1200px) | Collapsible nav + reduced grid |
| Mobile (<768px) | Bottom nav + single column |

---

## 13. Document Cross-References

| Reference | Source Document | Section |
|-----------|-----------------|---------|
| Persona Goals | F1 (personas.md) | Section 3 |
| Navigation Structure | F2 (information-architecture.md) | Section 3 |
| Role Visibility Rules | F2 (information-architecture.md) | Section 6 |
| Happy/Failure Paths | F3 (ux-flows.md) | All Flows |
| Confidence Display Rule | F1 (personas.md) | UX Success Metrics |
| Status Filters | F2 (information-architecture.md) | Section 3 (Violations) |

---

## 14. Deferred Decisions

The following design decisions are deferred to implementation phase:

| Decision | Options | Criteria for Decision |
|----------|---------|----------------------|
| Violation Detail: Page vs Drawer | Full page navigation vs slide-out drawer | Depends on typical workflow (frequent back-and-forth vs deep investigation) |
| Camera Grid: Thumbnail source | Live frame grab vs static image | Depends on VAS performance and bandwidth |
| Toast duration | 3s / 5s / 8s | User testing feedback |
| Pagination vs Infinite Scroll | Traditional pagination vs virtual scrolling | Data volume and performance testing |
| Color palette specifics | Specific hex values | Brand guidelines (not UX scope) |

---

## 15. Approval Checklist

| Requirement | Status |
|-------------|--------|
| All 7 required screens wireframed | ✓ |
| Loading state for each screen | ✓ |
| Empty state for each screen | ✓ |
| Error state for each screen | ✓ |
| Degraded state (where applicable) | ✓ |
| Role-based annotations | ✓ |
| Cross-reference to F1, F2, F3 | ✓ |
| ASCII/markdown format (no images) | ✓ |

---

**Document Status:** Ready for Review

**Next Phase:** F5 — Component Library (if approved)
