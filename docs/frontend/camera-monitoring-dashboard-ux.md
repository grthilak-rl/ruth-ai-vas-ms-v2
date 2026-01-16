# Ruth AI — Camera Monitoring Dashboard UX Specification

| Meta             | Value                                           |
|------------------|-------------------------------------------------|
| Document ID      | RUTH-UX-F7                                      |
| Version          | 1.0                                             |
| Status           | Draft                                           |
| Owner            | Frontend UX Designer Agent                      |
| Input Documents  | F1 (Personas), F2 (IA), F3 (UX Flows), F4 (Wireframes), F6 (Data Contracts) |
| Purpose          | Consolidated multi-camera monitoring dashboard design |

---

## 1. Document Purpose

This document specifies the **consolidated camera monitoring dashboard** that replaces the current two-page camera architecture:

- **Current State**: Camera list page (tile view) → Camera detail page (single camera with play button)
- **Target State**: Single unified dashboard with configurable multi-camera grid, camera selector, and per-camera AI controls

The design prioritizes **operator efficiency** for simultaneous multi-camera monitoring while maintaining all established UX principles from F1-F6.

---

## 2. Design Rationale

### 2.1 Problem Statement

The current two-page architecture requires operators to:
1. Navigate to camera list
2. Select a camera
3. Click "Play Live Video"
4. Return to list to view another camera

This workflow is inefficient for security operators who need to monitor multiple feeds simultaneously.

### 2.2 Solution Overview

Consolidate into a single dashboard that:
- Displays multiple live video feeds in a configurable grid
- Allows camera selection from a sidebar/dropdown
- Provides per-camera AI model controls
- Supports fullscreen mode via new browser tab
- Maintains all failure state handling from existing UX flows

### 2.3 Persona Alignment

| Persona | How This Serves Them |
|---------|----------------------|
| **Operator** | Simultaneous monitoring reduces context switching; AI status visible at a glance |
| **Supervisor** | Quick overview of all active feeds during incident review |
| **Admin** | Single view to verify AI model assignment and camera health |

---

## 3. Information Architecture

### 3.1 URL Structure

```
/cameras                    → Consolidated monitoring dashboard (replaces list + detail)
/cameras/fullscreen/:id     → Fullscreen camera view (opens in new tab)
```

### 3.2 Navigation Changes

The existing "Cameras" navigation item now leads directly to the monitoring dashboard:

```
┌────────────┐
│ Overview   │
├────────────┤
│ Cameras    │  ← Now opens monitoring dashboard directly
├────────────┤
│ Violations │
├────────────┤
│ Analytics  │  ← Supervisor+ only
└────────────┘
```

---

## 4. Screen Layout: Monitoring Dashboard

### 4.1 Default State (4-Camera Grid)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  [●] Ruth AI                      [● All Systems OK]         [J. Smith ▼]   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  CAMERA MONITORING                                                          │
│  ════════════════                                                           │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  Grid Layout: [1×1] [2×2 ◉] [3×3] [4×4] [5×5]     [Camera Selector ▼]  ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
│  ┌─────────────────────────────────┐ ┌─────────────────────────────────┐   │
│  │ ┌─────────────────────────────┐ │ │ ┌─────────────────────────────┐ │   │
│  │ │                             │ │ │ │                             │ │   │
│  │ │                             │ │ │ │                             │ │   │
│  │ │      [LIVE VIDEO FEED]      │ │ │ │      [LIVE VIDEO FEED]      │ │   │
│  │ │                             │ │ │ │                             │ │   │
│  │ │                             │ │ │ │                             │ │   │
│  │ └─────────────────────────────┘ │ │ └─────────────────────────────┘ │   │
│  │ ┌─────────────────────────────┐ │ │ ┌─────────────────────────────┐ │   │
│  │ │ Lobby Camera        ● LIVE  │ │ │ │ Loading Dock      ● LIVE    │ │   │
│  │ │ ┌───────────────────────────┘ │ │ │ ┌───────────────────────────┘ │   │
│  │ │ │ [AI Models ▼] │ ● Detection │ │ │ │ [AI Models ▼] │ ● Detection │ │   │
│  │ │ │               │   Active    │ │ │ │               │   Active    │ │   │
│  │ │ └───────────────┴─────────────┤ │ │ └───────────────┴─────────────┤ │   │
│  │ │ [⛶ Fullscreen]   2 violations│ │ │ │ [⛶ Fullscreen]   0 violations│ │   │
│  │ └─────────────────────────────┘ │ │ └─────────────────────────────┘ │   │
│  └─────────────────────────────────┘ └─────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────┐ ┌─────────────────────────────────┐   │
│  │ ┌─────────────────────────────┐ │ │ ┌─────────────────────────────┐ │   │
│  │ │                             │ │ │ │         OFFLINE             │ │   │
│  │ │                             │ │ │ │                             │ │   │
│  │ │      [LIVE VIDEO FEED]      │ │ │ │      Camera Offline         │ │   │
│  │ │                             │ │ │ │      Last seen: 2h ago      │ │   │
│  │ │                             │ │ │ │                             │ │   │
│  │ └─────────────────────────────┘ │ │ └─────────────────────────────┘ │   │
│  │ ┌─────────────────────────────┐ │ │ ┌─────────────────────────────┐ │   │
│  │ │ Gate A             ● LIVE   │ │ │ │ Parking Lot      ○ OFFLINE  │ │   │
│  │ │ ┌───────────────────────────┘ │ │ │ ┌───────────────────────────┘ │   │
│  │ │ │ [AI Models ▼] │ ● Detection │ │ │ │ [AI Models ▼] │ Detection   │ │   │
│  │ │ │               │   Active    │ │ │ │               │ Unavailable │ │   │
│  │ │ └───────────────┴─────────────┤ │ │ └───────────────┴─────────────┤ │   │
│  │ │ [⛶ Fullscreen]   1 violation │ │ │ │ [⛶ Fullscreen]   --         │ │   │
│  │ └─────────────────────────────┘ │ │ └─────────────────────────────┘ │   │
│  └─────────────────────────────────┘ └─────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Component Breakdown

#### 4.2.1 Grid Layout Selector

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Grid Layout: [1×1] [2×2 ◉] [3×3] [4×4] [5×5]     [Camera Selector ▼]      │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Grid Size | Cameras | Use Case |
|-----------|---------|----------|
| 1×1 | 1 | Single camera focus / detailed investigation |
| 2×2 | 4 | Default operational view |
| 3×3 | 9 | Medium-scale monitoring |
| 4×4 | 16 | Large facility coverage |
| 5×5 | 25 | Maximum density monitoring |

**Behavior:**
- Current selection highlighted with filled indicator (◉)
- Clicking a size instantly reflows the grid
- Persists in browser localStorage per user
- If fewer cameras than grid slots, show empty slots with "Add Camera" affordance

#### 4.2.2 Camera Selector Dropdown

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Camera Selector                                                    [×]     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  AVAILABLE CAMERAS (8)                                                      │
│  ───────────────────                                                        │
│  □ Lobby Camera           ● Live    [Fall, PPE]                             │
│  ☑ Loading Dock           ● Live    [Fall, PPE]                             │
│  ☑ Gate A                 ● Live    [Fall, Access]                          │
│  □ Warehouse 1            ● Live    [Fall]                                  │
│  ☑ Warehouse 2            ● Live    [Fall, PPE]                             │
│  □ Main Entrance          ● Live    [Fall, PPE, Access]                     │
│  □ Conference Room        ● Live    [Fall]                                  │
│  ☑ Parking Lot            ○ Offline --                                      │
│                                                                             │
│  ───────────────────                                                        │
│  Selected: 4 / 4 (max for 2×2 grid)                                         │
│                                                                             │
│                                            [Clear All]  [Apply]             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Checkboxes for multi-select
- Shows camera name, status, and active AI models
- Maximum selection enforced based on current grid size
- Changes apply immediately on "Apply" or when clicking outside
- Offline cameras can be selected (shows offline state in grid)

#### 4.2.3 Camera Cell (Single Grid Unit)

```
┌─────────────────────────────────────────────────────────────┐
│ ┌─────────────────────────────────────────────────────────┐ │
│ │                                                         │ │
│ │                                                         │ │
│ │                  [LIVE VIDEO FEED]                      │ │
│ │            (with detection overlays if AI active)       │ │
│ │                                                         │ │
│ │                                                         │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Lobby Camera                                   ● LIVE   │ │ ← Status bar
│ ├─────────────────────────────────────────────────────────┤ │
│ │ [AI Models ▼]                          ● Detection      │ │ ← AI controls
│ │                                           Active        │ │
│ ├─────────────────────────────────────────────────────────┤ │
│ │ [⛶ Fullscreen]                          2 violations    │ │ ← Actions bar
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**Sub-components:**

1. **Video Area**: WebRTC live feed with canvas overlay for detection bounding boxes
2. **Status Bar**: Camera name + status indicator (● LIVE / ○ OFFLINE)
3. **AI Controls**: Model selector dropdown + aggregate detection status
4. **Actions Bar**: Fullscreen button + today's violation count (clickable → filters to this camera)

---

## 5. AI Model Selector (Per-Camera)

### 5.1 Dropdown Default State

```
┌─────────────────────────────┐
│ AI Models ▼                 │
└─────────────────────────────┘
```

### 5.2 Dropdown Expanded

```
┌─────────────────────────────────────────────────┐
│ AI DETECTION MODELS                       [×]   │
├─────────────────────────────────────────────────┤
│                                                 │
│ Available for this camera:                      │
│                                                 │
│ ☑ Fall Detection          ● Active             │
│ ☐ PPE Detection           ○ Inactive           │
│ ☐ Unauthorized Access     ○ Inactive           │
│                                                 │
│ ─────────────────────────────────────────────── │
│ Note: Changes apply immediately.                │
│ Detection overlays show for active models.      │
│                                                 │
└─────────────────────────────────────────────────┘
```

### 5.3 AI Model States

| State | Visual | Meaning |
|-------|--------|---------|
| **Active** | ☑ + ● green | Model enabled, detection overlay visible |
| **Inactive** | ☐ + ○ gray | Model available but not enabled |
| **Degraded** | ☑ + ◐ yellow | Model enabled but experiencing issues |
| **Unavailable** | ☐ + ✖ red | Model not accessible (system issue) |

### 5.4 Detection Status Indicator

The aggregate detection status shows next to the AI Models dropdown:

| Status | Display | When |
|--------|---------|------|
| All active models healthy | `● Detection Active` | Default state |
| No models selected | `○ Plain Video` | User disabled all models |
| Some models degraded | `◐ Detection Degraded` | At least one model has issues |
| All models unavailable | `✖ Detection Unavailable` | System-level AI failure |

### 5.5 Plain Video Mode (No AI)

When operator deselects all AI models:

```
┌─────────────────────────────────────────────────────────────┐
│ ┌─────────────────────────────────────────────────────────┐ │
│ │                                                         │ │
│ │                  [LIVE VIDEO FEED]                      │ │
│ │              (no detection overlays)                    │ │
│ │                                                         │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Lobby Camera                                   ● LIVE   │ │
│ ├─────────────────────────────────────────────────────────┤ │
│ │ [AI Models ▼]                            ○ Plain Video  │ │
│ │                                                         │ │
│ ├─────────────────────────────────────────────────────────┤ │
│ │ [⛶ Fullscreen]                              --          │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**Key UX Rules:**
- Video continues playing without any AI overlays
- Violation count shows `--` (not applicable)
- Detection status shows `○ Plain Video`
- Operator understands: "I'm watching video only, no AI monitoring"

---

## 6. Grid Size Variations

### 6.1 1×1 Grid (Single Camera Focus)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  CAMERA MONITORING                                                          │
│                                                                             │
│  Grid Layout: [1×1 ◉] [2×2] [3×3] [4×4] [5×5]     [Camera Selector ▼]      │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │ ┌─────────────────────────────────────────────────────────────────────┐ ││
│  │ │                                                                     │ ││
│  │ │                                                                     │ ││
│  │ │                                                                     │ ││
│  │ │                       [LARGE LIVE VIDEO FEED]                       │ ││
│  │ │                                                                     │ ││
│  │ │                                                                     │ ││
│  │ │                                                                     │ ││
│  │ │                                                                     │ ││
│  │ └─────────────────────────────────────────────────────────────────────┘ ││
│  │ ┌─────────────────────────────────────────────────────────────────────┐ ││
│  │ │ Lobby Camera                                             ● LIVE     │ ││
│  │ ├─────────────────────────────────────────────────────────────────────┤ ││
│  │ │ [AI Models ▼]                                      ● Detection      │ ││
│  │ │                                                       Active        │ ││
│  │ ├─────────────────────────────────────────────────────────────────────┤ ││
│  │ │ [⛶ Fullscreen]                                     2 violations     │ ││
│  │ └─────────────────────────────────────────────────────────────────────┘ ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Use Case:** Detailed investigation, incident review, single-camera stations

### 6.2 3×3 Grid (9 Cameras)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Grid Layout: [1×1] [2×2] [3×3 ◉] [4×4] [5×5]     [Camera Selector ▼]      │
│                                                                             │
│  ┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐         │
│  │ [VIDEO]           │ │ [VIDEO]           │ │ [VIDEO]           │         │
│  │ Lobby      ● LIVE │ │ Loading   ● LIVE  │ │ Gate A    ● LIVE  │         │
│  │ [AI ▼] ● Active   │ │ [AI ▼] ● Active   │ │ [AI ▼] ● Active   │         │
│  │ [⛶]      2 viol   │ │ [⛶]      0 viol   │ │ [⛶]      1 viol   │         │
│  └───────────────────┘ └───────────────────┘ └───────────────────┘         │
│  ┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐         │
│  │ [VIDEO]           │ │ [VIDEO]           │ │ [OFFLINE]         │         │
│  │ Warehouse1 ● LIVE │ │ Warehouse2 ● LIVE │ │ Parking   ○ OFF   │         │
│  │ [AI ▼] ● Active   │ │ [AI ▼] ● Active   │ │ [AI ▼] Unavail    │         │
│  │ [⛶]      0 viol   │ │ [⛶]      1 viol   │ │ [⛶]      --       │         │
│  └───────────────────┘ └───────────────────┘ └───────────────────┘         │
│  ┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐         │
│  │ [VIDEO]           │ │ [VIDEO]           │ │ [+ Add Camera]    │         │
│  │ Main Ent  ● LIVE  │ │ Conf Rm   ● LIVE  │ │                   │         │
│  │ [AI ▼] ● Active   │ │ [AI ▼] ○ Plain    │ │ Click to select   │         │
│  │ [⛶]      0 viol   │ │ [⛶]      --       │ │ a camera          │         │
│  └───────────────────┘ └───────────────────┘ └───────────────────┘         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Note:** Compact display mode with abbreviated labels for density

### 6.3 Empty Slot

When grid has fewer cameras than slots:

```
┌───────────────────┐
│                   │
│   ┌───────────┐   │
│   │           │   │
│   │    [+]    │   │
│   │           │   │
│   └───────────┘   │
│                   │
│   Add Camera      │
│                   │
│   Click to select │
│   from available  │
│   cameras         │
│                   │
└───────────────────┘
```

**Behavior:** Clicking opens camera selector with focus on available (unselected) cameras

---

## 7. Fullscreen Mode

### 7.1 Behavior Specification

| Aspect | Design Decision |
|--------|-----------------|
| **Trigger** | Click [⛶ Fullscreen] button on any camera cell |
| **Action** | Opens new browser tab with URL `/cameras/fullscreen/:camera_id` |
| **Tab title** | "{Camera Name} - Ruth AI Live" |
| **Content** | Single camera view with all controls |
| **Return** | Close tab to return; original dashboard remains open |

### 7.2 Fullscreen View Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  [●] Ruth AI — Lobby Camera                   [● All Systems OK] [Close ✕]  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                                                                         ││
│  │                                                                         ││
│  │                                                                         ││
│  │                                                                         ││
│  │                         [FULL VIEWPORT VIDEO]                           ││
│  │                      (with detection overlays)                          ││
│  │                                                                         ││
│  │                                                                         ││
│  │                                                                         ││
│  │                                                                         ││
│  │                                                                         ││
│  │                                                                         ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                                                                         ││
│  │  ┌─────────────────┐  ┌─────────────────────────────────────────────┐   ││
│  │  │  CAMERA INFO    │  │  AI DETECTION                               │   ││
│  │  │                 │  │                                             │   ││
│  │  │  Status: ● Live │  │  ☑ Fall Detection      ● Active             │   ││
│  │  │  Stream: Active │  │  ☐ PPE Detection       ○ Inactive           │   ││
│  │  │                 │  │  ☐ Access Control      ○ Inactive           │   ││
│  │  └─────────────────┘  └─────────────────────────────────────────────┘   ││
│  │                                                                         ││
│  │  ┌─────────────────────────────────────────────────────────────────────┐││
│  │  │  TODAY'S VIOLATIONS (2)                              [View All →]   │││
│  │  ├─────────────────────────────────────────────────────────────────────┤││
│  │  │  ● Fall Detected    High      14:32    [View Details]               │││
│  │  │  ● Fall Detected    Low       09:45    [View Details]               │││
│  │  └─────────────────────────────────────────────────────────────────────┘││
│  │                                                                         ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.3 Fullscreen Controls

- **Close [✕]**: Closes tab, returns operator to their previous context
- **AI Models**: Full model selector with checkboxes (not abbreviated dropdown)
- **Violations**: Today's violations for this camera with direct links to details
- **View All →**: Links to Alerts filtered by this camera

---

## 8. State Variations

### 8.1 Loading State (Initial Dashboard Load)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  CAMERA MONITORING                                         Loading...       │
│                                                                             │
│  Grid Layout: [1×1] [2×2 ◉] [3×3] [4×4] [5×5]     [Camera Selector ▼]      │
│                                                                             │
│  ┌─────────────────────────────────┐ ┌─────────────────────────────────┐   │
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │   │
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │   │
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │   │
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │   │
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │   │
│  └─────────────────────────────────┘ └─────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────┐ ┌─────────────────────────────────┐   │
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │   │
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │   │
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │   │
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │   │
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │   │
│  └─────────────────────────────────┘ └─────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Skeleton loaders for each grid cell
- Grid controls remain interactive
- Each cell loads independently

### 8.2 Camera Cell: Connecting State

```
┌─────────────────────────────────────────────────────────────┐
│ ┌─────────────────────────────────────────────────────────┐ │
│ │                                                         │ │
│ │                  ┌─────────────┐                        │ │
│ │                  │   ◠ ◠ ◠    │                        │ │
│ │                  │ Connecting  │                        │ │
│ │                  └─────────────┘                        │ │
│ │                                                         │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Lobby Camera                              ◐ Connecting  │ │
│ ├─────────────────────────────────────────────────────────┤ │
│ │ [AI Models ▼]                          ○ Waiting...     │ │
│ ├─────────────────────────────────────────────────────────┤ │
│ │ [⛶ Fullscreen]                              --          │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 8.3 Camera Cell: Offline State

```
┌─────────────────────────────────────────────────────────────┐
│ ┌─────────────────────────────────────────────────────────┐ │
│ │                                                         │ │
│ │                  ┌─────────────┐                        │ │
│ │                  │             │                        │ │
│ │                  │   OFFLINE   │                        │ │
│ │                  │             │                        │ │
│ │                  └─────────────┘                        │ │
│ │                                                         │ │
│ │            Last seen: 2 hours ago                       │ │
│ │                                                         │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Parking Lot                               ○ OFFLINE     │ │
│ ├─────────────────────────────────────────────────────────┤ │
│ │ [AI Models ▼]                          Detection        │ │
│ │                                        Unavailable      │ │
│ ├─────────────────────────────────────────────────────────┤ │
│ │ [⛶] (disabled)                              --          │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 8.4 Camera Cell: Video Error State

```
┌─────────────────────────────────────────────────────────────┐
│ ┌─────────────────────────────────────────────────────────┐ │
│ │                                                         │ │
│ │              ┌─────────────────────┐                    │ │
│ │              │                     │                    │ │
│ │              │ ⚠ Video unavailable│                    │ │
│ │              │                     │                    │ │
│ │              │ Unable to connect   │                    │ │
│ │              │ to live stream.     │                    │ │
│ │              │                     │                    │ │
│ │              │ [Retry]             │                    │ │
│ │              │                     │                    │ │
│ │              └─────────────────────┘                    │ │
│ │                                                         │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Lobby Camera                               ⚠ Error      │ │
│ ├─────────────────────────────────────────────────────────┤ │
│ │ [AI Models ▼]                          Detection        │ │
│ │                                        Unavailable      │ │
│ ├─────────────────────────────────────────────────────────┤ │
│ │ [⛶] (disabled)                              --          │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 8.5 Camera Cell: AI Degraded State

```
┌─────────────────────────────────────────────────────────────┐
│ ┌─────────────────────────────────────────────────────────┐ │
│ │                                                         │ │
│ │                  [LIVE VIDEO FEED]                      │ │
│ │                (video plays normally)                   │ │
│ │                                                         │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Lobby Camera                                   ● LIVE   │ │
│ ├─────────────────────────────────────────────────────────┤ │
│ │ [AI Models ▼]                          ◐ Detection      │ │
│ │                                          Degraded       │ │
│ │ ⚠ AI may be slower or less accurate                     │ │
│ ├─────────────────────────────────────────────────────────┤ │
│ │ [⛶ Fullscreen]                          2 violations    │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**User Understanding:** "Video works fine. AI detection is having issues but still running."

### 8.6 Empty State (No Cameras Configured)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  CAMERA MONITORING                                                          │
│                                                                             │
│  Grid Layout: [1×1] [2×2 ◉] [3×3] [4×4] [5×5]     [Camera Selector ▼]      │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                                                                         ││
│  │                                                                         ││
│  │                    ┌───────────────────────────────┐                    ││
│  │                    │                               │                    ││
│  │                    │    No cameras configured      │                    ││
│  │                    │                               │                    ││
│  │                    │    Contact your admin to      │                    ││
│  │                    │    add cameras to the         │                    ││
│  │                    │    system.                    │                    ││
│  │                    │                               │                    ││
│  │                    └───────────────────────────────┘                    ││
│  │                                                                         ││
│  │                                                                         ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.7 Error State (Dashboard API Failure)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  CAMERA MONITORING                                           ⚠ Error        │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                                                                         ││
│  │                                                                         ││
│  │              ┌─────────────────────────────────────────┐                ││
│  │              │                                         │                ││
│  │              │   ⚠ Unable to load cameras             │                ││
│  │              │                                         │                ││
│  │              │   Could not retrieve camera list.      │                ││
│  │              │   This may be a temporary issue.       │                ││
│  │              │                                         │                ││
│  │              │              [Retry]                    │                ││
│  │              │                                         │                ││
│  │              └─────────────────────────────────────────┘                ││
│  │                                                                         ││
│  │                                                                         ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Interaction Patterns

### 9.1 Keyboard Navigation

| Key | Action |
|-----|--------|
| `Tab` | Navigate between grid cells and controls |
| `Enter` / `Space` | Activate focused button (fullscreen, selector) |
| `Escape` | Close open dropdown/selector |
| `1-5` | Quick switch to grid size (when grid selector focused) |
| `Arrow keys` | Navigate within dropdowns |

### 9.2 Click/Tap Targets

| Element | Action | Result |
|---------|--------|--------|
| Grid size button | Click | Switch to that grid size |
| Camera Selector | Click | Open camera selection dropdown |
| AI Models dropdown | Click | Open model toggle dropdown |
| Fullscreen button | Click | Open camera in new tab |
| Violation count | Click | Navigate to Alerts filtered by camera |
| Camera name | Hover | Show tooltip with full name (if truncated) |
| Empty slot [+] | Click | Open camera selector |

### 9.3 Real-time Updates

| Event | UI Response |
|-------|-------------|
| New violation | Badge count updates; no alert (unless critical) |
| Camera goes offline | Cell transitions to offline state |
| Camera comes online | Cell transitions to connecting → live |
| AI model status change | Detection status indicator updates |
| System health change | Global status indicator updates |

---

## 10. Performance Considerations

### 10.1 WebRTC Stream Management

| Concern | Design Decision |
|---------|-----------------|
| **Max concurrent streams** | Limit to grid size + 1 (preload next) |
| **Off-screen streams** | Pause/disconnect streams not in current grid |
| **Grid size change** | Gracefully disconnect excess, connect new |
| **Background tab** | Reduce to 1fps or pause after 30 seconds |

### 10.2 Resource Optimization

| Scenario | Optimization |
|----------|--------------|
| Large grids (4×4, 5×5) | Reduce video quality for smaller cells |
| Low bandwidth | Show degraded indicator, reduce FPS |
| Multiple fullscreen tabs | Each manages own stream independently |

### 10.3 AI Inference Load

| Concern | Design Decision |
|---------|-----------------|
| Multiple active models | Models run server-side; frontend receives results |
| Detection overlay rendering | Canvas rendering per-cell, batched updates |
| High detection frequency | Throttle overlay updates to 10fps max |

---

## 11. Data Contract Integration

### 11.1 Camera List Contract

**Source:** `GET /api/v1/devices` (per F6)

**Fields consumed:**
- `id`: Camera UUID
- `name`: Display name
- `is_active`: Whether camera is configured
- `streaming.active`: Whether stream is running
- `streaming.ai_enabled`: Whether AI is enabled
- `streaming.model_id`: Current model (if any)

### 11.2 AI Model Status Contract

**Source:** `GET /api/v1/models/status` (per F6)

**Frontend presentation rules:**
- Operators see "Detection Active/Inactive/Degraded"
- Operators do NOT see model_id ("fall_detection") as raw string
- Model names displayed as human-readable labels

### 11.3 Violation Count Contract

**Source:** `GET /api/v1/analytics/summary?camera_id={id}` (per F6)

**Display:** Integer count, "--" if unavailable or AI disabled

---

## 12. Role-Based Visibility

| Element | Operator | Supervisor | Admin |
|---------|----------|------------|-------|
| Grid layout controls | ✓ | ✓ | ✓ |
| Camera selector | ✓ | ✓ | ✓ |
| AI model toggles | ✓ | ✓ | ✓ |
| Fullscreen mode | ✓ | ✓ | ✓ |
| Violation counts | ✓ | ✓ | ✓ |
| Camera configuration | — | — | ✓ (separate screen) |
| System health details | — | — | ✓ (separate screen) |

---

## 13. Responsive Behavior

### 13.1 Breakpoints

| Breakpoint | Layout Change |
|------------|---------------|
| Desktop (>1400px) | Full grid, all controls visible |
| Laptop (1024-1400px) | Compact controls, reduced padding |
| Tablet (768-1024px) | Max 2×2 grid, collapsed selector |
| Mobile (<768px) | 1×1 only, bottom sheet for controls |

### 13.2 Large Displays (Monitoring Stations)

For displays >2560px wide:
- Grid fills viewport proportionally
- Cell aspect ratio maintains 16:9
- Controls scale appropriately

---

## 14. Accessibility Requirements

### 14.1 Screen Reader Support

| Element | Accessible Name |
|---------|-----------------|
| Grid selector | "Grid layout: {current} selected. Options: 1 by 1, 2 by 2, etc." |
| Camera cell | "{Camera name}, {status}. AI detection: {status}. {n} violations today." |
| Model toggle | "{Model name}, currently {enabled/disabled}. Toggle to change." |
| Fullscreen button | "Open {camera name} in fullscreen" |

### 14.2 Visual Accessibility

| Requirement | Implementation |
|-------------|----------------|
| Color contrast | WCAG AA minimum (4.5:1 for text) |
| Status indicators | Color + icon + text (not color alone) |
| Focus indicators | Visible focus ring on all interactive elements |
| Motion | Reduced motion mode available |

---

## 15. Validation Checklist

| Requirement | Status |
|-------------|--------|
| Single page replaces two-page architecture | ✓ Specified |
| Grid layouts 1×1 through 5×5 | ✓ Specified |
| Camera selector for grid population | ✓ Specified |
| Per-camera AI model toggles | ✓ Specified |
| Plain video mode (no AI) | ✓ Specified |
| Fullscreen opens in new tab | ✓ Specified |
| All failure states documented | ✓ Specified |
| Operator-friendly (minimal clicks) | ✓ Designed |
| Aligns with F1-F6 documents | ✓ Cross-referenced |
| Performance considerations addressed | ✓ Specified |
| Accessibility requirements defined | ✓ Specified |

---

## 16. Document Cross-References

| Topic | Source Document | Section |
|-------|-----------------|---------|
| Operator goals | F1 (personas.md) | Persona 1 |
| Camera status derivation | F6 (data-contracts.md) | Section 4.4 |
| AI model presentation | F1 (personas.md) | "What Operator Does NOT Care About" |
| Failure messaging | F3 (ux-flows.md) | Flow 1, Flow 5 |
| Existing camera wireframes | F4 (wireframes.md) | Section 7 |
| Video player component | LiveVideoPlayer.tsx | Existing implementation |

---

## 17. Migration Notes

### 17.1 What Changes

| Current | New |
|---------|-----|
| `/cameras` → Camera list page | `/cameras` → Monitoring dashboard |
| `/cameras/:id` → Camera detail page | Removed (functionality in dashboard + fullscreen) |
| Click to view camera | Camera visible immediately in grid |
| "Play Live Video" button | Video auto-starts when camera added to grid |

### 17.2 URL Redirects

| Old URL | New Behavior |
|---------|--------------|
| `/cameras` | Shows monitoring dashboard |
| `/cameras/:id` | Redirect to `/cameras?focus=:id` (opens that camera in 1×1 grid) |

### 17.3 State Persistence

| State | Storage | Scope |
|-------|---------|-------|
| Grid size preference | localStorage | Per-browser |
| Selected cameras | localStorage | Per-browser |
| AI model toggles per camera | Session (reset on page reload) | Per-session |

---

**Document Status:** Ready for Review

**Next Phase:** Implementation by Frontend Engineer Agent

---

**End of Document**