# Ruth AI — Core UX Flows

**Version:** 1.0
**Owner:** Frontend UX Designer
**Status:** Approved / Frozen
**Last Updated:** January 2026
**Dependencies:**
- [F1 - Personas](personas.md) — Frozen
- [F2 - Information Architecture](information-architecture.md) — Frozen

---

## Purpose

This document defines the **behavioral truth** for critical user journeys in Ruth AI. It specifies:
- What happens, in what order
- What the user understands at each step
- How the system responds to failures

This is the single source of truth for wireframes, interaction design, error handling, and frontend state modeling.

---

## Design Constraints (Enforced)

All flows in this document must adhere to these constraints:

| Constraint | Enforcement |
|------------|-------------|
| Operators must never see model names or versions | Use "Detection" or "AI" not "fall_detection_v1.2.3" |
| Operators must never see error stacks or system internals | Use "Something went wrong" not "gRPC DEADLINE_EXCEEDED" |
| Supervisors must not configure the system | No settings access; escalate to Admin |
| Admins see abstracted health, not infrastructure | "Backend: Degraded" not "pod restart count: 5" |
| All failure paths must preserve user trust | No blame-oriented language |
| All failure paths must preserve continuity of work | User can continue other tasks |
| No flow requires page refresh to recover | Auto-retry or manual retry button |

---

## Flow 1: View Live Violations (Operator)

### Primary Persona
**Operator**

### Trigger / Entry Points

| Entry Point | Screen (F2) | Context |
|-------------|-------------|---------|
| Alert badge on nav bar | Global Nav | Badge shows count of open violations |
| "Recent Violations" card | Overview Dashboard (`/`) | Shows top 5 recent violations |
| "View Violations" link | Camera View (`/cameras/:id`) | Shows violations for this camera |
| Push notification (future) | Any screen | Notification appears globally |

---

### Happy Path

1. **Operator is on any screen** (most commonly Overview or Camera View)
2. **Alert badge updates** — The nav bar "Alerts" item shows a badge with the count of open violations (e.g., "3")
3. **Operator clicks Alerts** — Navigates to Alerts List (`/alerts`)
4. **Alerts List loads immediately** — Shows violations sorted by timestamp (newest first)
5. **Violation card displays:**
   - Camera name (not ID)
   - Timestamp (relative: "2 minutes ago")
   - Confidence indicator (categorical: "High Confidence" badge)
   - Snapshot thumbnail (if available)
   - Status badge ("New" / "Reviewed")
6. **Urgency is communicated via:**
   - Color-coded border (e.g., high confidence = solid, low confidence = dashed)
   - Position (newest at top)
   - Badge pulse animation for new violations (subtle, not alarming)
7. **Operator understands the situation** — They know how many violations exist, which cameras are affected, and which need immediate attention

---

### Failure / Degraded Paths

#### F1.1: Video is delayed (live feed lag)

| Step | What Happens | What User Sees |
|------|--------------|----------------|
| 1 | Video feed lags >3 seconds behind real-time | Video continues playing |
| 2 | System detects delay | Status indicator changes: "Live" → "Delayed" (subtle label) |
| 3 | Operator continues viewing | No interruption to workflow |
| 4 | Feed recovers | Status returns to "Live" (no notification) |

**User Understanding:** "The video is slightly behind, but detections are still happening."

**What We Do NOT Say:** "WebRTC buffer overrun" or "Frame queue depth exceeded"

---

#### F1.2: AI confidence is low

| Step | What Happens | What User Sees |
|------|--------------|----------------|
| 1 | Detection has confidence score < 0.7 | Violation card shows "Low Confidence" badge |
| 2 | Card styling differs | Muted colors, dashed border (not alarm colors) |
| 3 | Operator can still act | All actions available (acknowledge, dismiss, escalate) |
| 4 | If dismissed | Counts as false positive for analytics |

**User Understanding:** "The AI isn't sure about this one. I should look more carefully before deciding."

**What We Do NOT Say:** Confidence score as a number (e.g., "0.62") or "Model uncertainty is high"

---

#### F1.3: Camera goes offline mid-view

| Step | What Happens | What User Sees |
|------|--------------|----------------|
| 1 | Camera feed disconnects | Video freezes on last frame |
| 2 | System detects within 5 seconds | Overlay appears: "Camera Offline" with timestamp of last frame |
| 3 | Detection status updates | "Detection Paused — Camera offline" |
| 4 | Existing violations remain | User can still review/action existing violations |
| 5 | Auto-reconnect attempts | Small "Reconnecting..." indicator (non-blocking) |
| 6 | If reconnected | Overlay disappears, video resumes, "Detection Active" returns |
| 7 | If not reconnected after 60s | Message changes to "Camera Offline — Last seen [timestamp]" |

**User Understanding:** "The camera is disconnected. I can still handle the violations I have. Someone should check the camera."

**What We Do NOT Say:** "RTSP connection failed" or "VAS stream unavailable"

---

### User Understanding Check

| What the user believes | What the user does next |
|------------------------|-------------------------|
| "There are N violations I need to review" | Opens Alerts List |
| "This violation is from [camera] at [time]" | Clicks to see details |
| "The AI thinks this is likely a fall" | Investigates if high confidence, scrutinizes if low |
| "The camera is having issues but I can still work" | Continues with existing violations, may escalate camera issue |

---

### Explicit Non-Goals

The UI must NOT:
- Show inference latency or FPS
- Display model name or version
- Expose event-to-violation aggregation logic
- Show raw confidence numbers
- Require page refresh to see new violations
- Block the UI while waiting for video to load

---

## Flow 2: Drill Down Into a Violation

### Primary Persona
**Operator** (triage), **Supervisor** (investigation)

### Trigger / Entry Point

| Entry Point | Screen (F2) | Action |
|-------------|-------------|--------|
| Click violation card | Alerts List (`/alerts`) | Opens Violation Detail |
| Click violation in "Recent" | Overview Dashboard (`/`) | Opens Violation Detail |
| Click violation in camera context | Camera View (`/cameras/:id`) | Opens Violation Detail |
| Deep link | Direct URL (`/alerts/:id`) | Opens Violation Detail directly |

---

### Happy Path

1. **Operator clicks a violation card** in Alerts List
2. **Violation Detail loads** (`/alerts/:id`)
3. **Key information displays immediately:**
   - Camera name
   - Timestamp (absolute and relative)
   - Confidence category (High / Medium / Low)
   - Status (Open / Reviewed)
4. **Snapshot displays** — Full-size image with detection overlay (bounding box)
5. **Video clip available** — "Play Evidence" button, video loads on demand
6. **Context preserved:**
   - "View Camera" link (opens Camera View for this camera)
   - "View All Violations" link (opens Violations filtered by this camera)
7. **Actions available:**
   - Acknowledge (marks as reviewed)
   - Dismiss (marks as false positive)
   - Escalate (flags for Supervisor)
   - Resolve (Supervisor only)

---

### Failure / Degraded Paths

#### F2.1: Evidence video is still processing

| Step | What Happens | What User Sees |
|------|--------------|----------------|
| 1 | User opens Violation Detail | Snapshot displays normally |
| 2 | Video is not ready | "Play Evidence" button shows "Preparing video..." |
| 3 | User waits | Progress indicator (not a spinner — show estimated time if known) |
| 4 | Video becomes ready | Button changes to "Play Evidence" |
| 5 | If video still processing after 30s | Message: "Video is taking longer than usual. You can continue without it." |

**User Understanding:** "The video clip is being created. I can see the snapshot and make a decision if needed."

**What We Do NOT Say:** "Bookmark processing" or "VAS encoding in progress"

---

#### F2.2: Evidence is unavailable (failed)

| Step | What Happens | What User Sees |
|------|--------------|----------------|
| 1 | User opens Violation Detail | Snapshot may or may not display |
| 2 | Video evidence failed permanently | Message: "Video clip unavailable" |
| 3 | Snapshot fallback | If snapshot exists, it's shown prominently |
| 4 | No snapshot either | Placeholder: "Evidence not available. Detection occurred at [timestamp] on [camera]." |
| 5 | Actions still available | User can still acknowledge/dismiss based on live feed or context |

**User Understanding:** "There's no recording for this one, but I can still make a decision based on what I know."

**What We Do NOT Say:** "Evidence creation failed" or "Bookmark failed — retry?" (no retry exposed to Operator)

---

#### F2.3: Violation no longer exists (deleted or corrupted)

| Step | What Happens | What User Sees |
|------|--------------|----------------|
| 1 | User navigates to `/alerts/:id` | Page attempts to load |
| 2 | Violation not found (404) | "This violation is no longer available. It may have been resolved or removed." |
| 3 | User is offered navigation | "Return to Alerts" button |
| 4 | Alerts List loads | User continues normal workflow |

**User Understanding:** "This violation was handled already. I can move on."

---

### User Understanding Check

| What the user believes | What the user does next |
|------------------------|-------------------------|
| "I'm looking at a specific incident" | Reviews evidence |
| "I can see what the AI detected" | Examines snapshot with bounding box |
| "I can watch the video if I need more context" | Clicks Play Evidence |
| "I can act on this now" | Acknowledges, dismisses, or escalates |

---

### Explicit Non-Goals

The UI must NOT:
- Show event IDs or raw timestamps in ISO format
- Expose the bounding box coordinates as numbers
- Show model version that made the detection
- Require the video to load before allowing actions
- Block navigation while evidence loads

---

## Flow 3: Acknowledge / Dismiss an Alert

### Primary Personas
- **Operator:** Acknowledge, Dismiss, Escalate
- **Supervisor:** Resolve, Override

### Trigger / Entry Points

| Action | Available On | Who Can Do It |
|--------|--------------|---------------|
| Acknowledge | Alerts List (inline), Violation Detail | Operator, Supervisor |
| Dismiss | Alerts List (inline), Violation Detail | Operator, Supervisor |
| Escalate | Violation Detail | Operator |
| Resolve | Violation Detail | Supervisor only |

---

### Happy Path: Operator Acknowledge

1. **Operator views violation** (Alerts List or Detail)
2. **Clicks "Acknowledge"** button
3. **Button shows brief loading state** (< 500ms typical)
4. **Status updates immediately** — "Open" → "Reviewed"
5. **Violation remains in Alerts** (status = reviewed, not closed)
6. **Badge count updates** — Only counts "Open", not "Reviewed"
7. **Operator continues** — No modal, no confirmation, minimal friction

**Total clicks:** 1 (from Alerts List) or 2 (navigate + click)

---

### Happy Path: Operator Dismiss (False Positive)

1. **Operator views violation** (Alerts List or Detail)
2. **Clicks "Dismiss"** button
3. **Brief confirmation appears:**
   - "Mark as false positive?"
   - Two buttons: "Yes, Dismiss" / "Cancel"
4. **If confirmed:**
   - Status updates: "Open" → "Dismissed"
   - Status updates: "Open" → "Dismissed"
   - Badge count decrements
   - Brief toast: "Violation dismissed"
   - Violation remains accessible via status filter (Dismissed)
5. **If cancelled:** No change, operator returns to previous state

**Why confirmation for Dismiss but not Acknowledge:**
- Acknowledge is reversible and low-stakes
- Dismiss is a judgment call that affects analytics (false positive rate)

---

### Happy Path: Supervisor Resolve

1. **Supervisor views escalated violation** in Alerts
2. **Reviews evidence** (snapshot, video)
3. **Clicks "Resolve"** button
4. **Resolution dialog appears:**
   - Optional notes field (max 500 chars)
   - "Resolve" / "Cancel" buttons
5. **If resolved:**
   - Status updates: "Reviewed" → "Resolved"
   - Resolution notes saved with timestamp and Supervisor name
   - Toast: "Violation resolved"
   - Violation remains accessible via status filter (Resolved)
6. **Supervisor can access resolved violations** via Violations page with "Resolved" filter for audit purposes

---

### Failure / Degraded Paths

#### F3.1: Backend write fails

| Step | What Happens | What User Sees |
|------|--------------|----------------|
| 1 | User clicks action button | Button shows loading state |
| 2 | Backend returns error | Button returns to normal state |
| 3 | Error message displays | Toast: "Couldn't save. Please try again." |
| 4 | User can retry | Same button, same action |
| 5 | If repeated failures | Toast: "Having trouble saving. Your work is not lost — please try again in a moment." |

**User Understanding:** "It didn't save. I'll try again."

**What We Do NOT Say:** "Database connection timeout" or "500 Internal Server Error"

---

#### F3.2: Duplicate action (already processed)

| Step | What Happens | What User Sees |
|------|--------------|----------------|
| 1 | User clicks "Dismiss" | Button shows loading state |
| 2 | Backend reports already dismissed | UI updates to show current state |
| 3 | No error message | Toast: "Already dismissed" (informational, not error) |
| 4 | Violation shows correct state | "Dismissed" status (visible with Dismissed filter) |

**User Understanding:** "Someone else already handled this. Done."

**What We Do NOT Say:** "Conflict: concurrent modification" or "Optimistic lock failed"

---

#### F3.3: Network offline during action

| Step | What Happens | What User Sees |
|------|--------------|----------------|
| 1 | User clicks action button | Button shows loading state |
| 2 | Request times out | Button returns to normal |
| 3 | Offline indicator appears | Global status: "Connection lost" |
| 4 | Retry available | Toast: "Couldn't reach server. Please check your connection." |
| 5 | When connection restored | Global status returns to normal |
| 6 | User retries | Action succeeds |

**User Understanding:** "I'm offline. I'll try again when connected."

---

### User Understanding Check

| What the user believes | What the user does next |
|------------------------|-------------------------|
| "I've acknowledged this — it's marked as seen" | Moves to next violation |
| "I dismissed this — it was a false positive" | Moves to next violation |
| "I escalated this — a supervisor will review" | Moves to next violation |
| "I resolved this — the incident is closed" | Reviews next escalated violation |
| "The save failed but I can retry" | Clicks the button again |

---

### Explicit Non-Goals

The UI must NOT:
- Require mandatory notes for Acknowledge or Dismiss (friction reduction)
- Show database IDs or transaction details
- Expose optimistic update rollback to the user
- Lock the entire Alerts List during a single action
- Require page refresh after action

---

## Flow 4: View Model Health Degradation

### Primary Personas
- **Operator:** Read-only awareness
- **Supervisor:** Read-only awareness
- **Admin:** Diagnostic view

### Trigger

System automatically surfaces health issues. No user action triggers this flow.

---

### Where Health Degradation Is Surfaced

| Persona | Location | What They See | Can They Act? |
|---------|----------|---------------|---------------|
| **Operator** | Global status indicator (nav bar) | "System Degraded" | No — read-only modal |
| **Operator** | Camera View (per-camera) | "Detection Paused" | No — informational only |
| **Supervisor** | Global status indicator | "System Degraded" | No — read-only modal |
| **Admin** | Global status indicator | "System Degraded" | Yes — deep link to Settings > System Health |
| **Admin** | Settings > System Health | Full diagnostic dashboard | Yes — can see per-service status |

---

### Happy Path: Operator Sees Degradation

1. **System detects AI model degradation** (latency elevated, errors occurring)
2. **Global status changes** — "Healthy" → "Degraded" (color change: green → yellow)
3. **Operator notices** (next time they glance at nav bar)
4. **Operator clicks status indicator**
5. **Modal appears:**
   - Title: "System Performance Reduced"
   - Body: "AI detection may be slower or less accurate. Video monitoring continues normally."
   - Footer: "Contact your supervisor if you notice issues."
   - Single button: "OK" (closes modal)
6. **Operator closes modal** — Can continue normal work
7. **Per-camera indicators update** — Cameras with degraded AI show "Detection Delayed" or "Detection Paused"

---

### Happy Path: Admin Sees Degradation

1. **System detects AI model degradation**
2. **Global status changes** — "Healthy" → "Degraded"
3. **Admin clicks status indicator**
4. **Navigates to Settings > System Health** (`/settings/health`)
5. **Dashboard shows:**
   - Service status cards (Backend, AI Runtime, Video Service)
   - AI Model status: "Fall Detection: Degraded — High latency"
   - Timestamp: "Status since 10:45 AM"
   - Metrics (abstracted): "Processing at 50% normal speed"
6. **Admin can investigate** — Links to Audit Log, model config, etc.
7. **Admin takes action** (outside Ruth AI: restarts service, contacts DevOps)
8. **When recovered** — Status returns to "Healthy", dashboard updates

---

### How Severity Is Communicated (Without Technical Jargon)

| Internal State | Operator/Supervisor Sees | Admin Sees |
|----------------|-------------------------|------------|
| Model latency 2x normal | (Not surfaced) | "Fall Detection: Healthy — slightly elevated latency" |
| Model latency 5x normal | "System Degraded" | "Fall Detection: Degraded — high latency" |
| Model returning errors 10% of frames | "System Degraded" | "Fall Detection: Degraded — intermittent errors" |
| Model not responding | "Detection Paused" | "Fall Detection: Offline" |
| Backend slow to respond | "System Degraded" | "Backend: Degraded — slow responses" |
| Backend down | "System Offline" | "Backend: Offline — not responding" |

---

### What the System Explicitly Does NOT Say

| Never Say | Say Instead |
|-----------|-------------|
| "fall_detection_v1.2.3 unhealthy" | "Detection degraded" |
| "gRPC DEADLINE_EXCEEDED" | "AI is responding slowly" |
| "Pod restarting" | (Not surfaced to users) |
| "Queue depth exceeded" | "Detection may be delayed" |
| "Inference latency P99 > 500ms" | "Detection performance reduced" |

---

### User Understanding Check

| What the user believes | What the user does next |
|------------------------|-------------------------|
| Operator: "The system is having issues but I can still work" | Continues monitoring, expects slower detections |
| Supervisor: "There's a system issue; Admin is probably aware" | Continues normal work, may mention to Admin |
| Admin: "The AI is running slowly; I need to investigate" | Checks System Health, escalates to DevOps if needed |

---

### Explicit Non-Goals

The UI must NOT:
- Show infrastructure metrics (CPU, memory, pod count)
- Expose log messages or error codes
- Let Operators "restart" or "fix" the issue
- Hide degradation from Operators (transparency is key)
- Create alarm fatigue with excessive notifications

---

## Flow 5: Handle "Model Unavailable" Gracefully

### Primary Personas
- **Operator:** Awareness, continuity
- **Admin:** Diagnosis, recovery

### Trigger Conditions

| Condition | Cause | Duration |
|-----------|-------|----------|
| Model temporarily unavailable | Service restart, brief outage | Seconds to minutes |
| Model disabled due to failures | Repeated errors, circuit breaker | Until Admin intervention |
| Model upgrading | Version rollout in progress | Minutes |

---

### Happy Path: Temporary Unavailability (Auto-Recovery)

1. **Model becomes unavailable** (e.g., service restart)
2. **Per-camera status updates** — "Detection Active" → "Detection Paused"
3. **Global status may update** — Depends on severity
4. **Video continues normally** — Operators still see live feeds
5. **Existing violations remain** — All previous detections are actionable
6. **System auto-retries** connection to model
7. **Model recovers** (within 60 seconds typical)
8. **Status returns to normal** — "Detection Paused" → "Detection Active"
9. **No user action required**

---

### Degraded Path: Prolonged Unavailability

| Step | What Happens | Operator Sees | Admin Sees |
|------|--------------|---------------|------------|
| 1 | Model unavailable > 60 seconds | "Detection Paused" persists | "Fall Detection: Offline" |
| 2 | Global status updates | "System Degraded" | "AI Runtime: Degraded" |
| 3 | Cameras show clear status | Per-camera: "Detection Paused" | Per-camera: "Not receiving detections" |
| 4 | Video continues | Live feeds work normally | (Same) |
| 5 | No new violations created | Violations list doesn't update | Audit log shows gap |
| 6 | When model returns | "Detection Active" resumes | Status returns to "Healthy" |

---

### How the UI Avoids Panic or Blame

| Principle | Implementation |
|-----------|----------------|
| **Video still works** | Live feeds continue. Make this explicit: "Video monitoring continues." |
| **Detection is paused, not broken** | Use "paused" not "failed" or "broken" |
| **Not the operator's fault** | Never suggest operator action caused the issue |
| **Recovery will happen** | "Detection will resume automatically" (if auto-recovery expected) |
| **Existing work is preserved** | "Your pending violations are still available" |

---

### Messaging Examples

| Situation | Message |
|-----------|---------|
| Brief pause (< 30s) | (No message — status indicator only) |
| Extended pause (> 60s) | "AI detection paused. Video monitoring continues normally. Detection will resume shortly." |
| Prolonged outage (> 5 min) | "AI detection is currently unavailable. Video monitoring continues. Contact your administrator if this persists." |
| Model disabled by Admin | "Detection is disabled for this camera." |

---

### User Understanding Check

| What the user believes | What the user does next |
|------------------------|-------------------------|
| "Detection is paused but I can still watch video" | Continues monitoring live feeds |
| "My existing violations are still there" | Continues triaging Alerts |
| "This will probably fix itself" | Waits, checks back later |
| "If it doesn't fix, I should tell someone" | Escalates to Supervisor or Admin |

---

### Explicit Non-Goals

The UI must NOT:
- Show "Model crashed" or "Model failed"
- Display retry countdowns or technical retry logic
- Suggest the operator restart anything
- Hide the issue (transparency builds trust)
- Stop showing video when AI is unavailable

---

## Flow 6: Version Upgrade Visibility (Read-Only)

### Primary Personas
- **Admin:** Full visibility
- **Operator / Supervisor:** Minimal or no visibility

### Design Principle

Version upgrades are infrastructure concerns. Operators and Supervisors should not see version numbers, upgrade status, or rollback events. They see only the **effect** on detection behavior.

---

### What Admins See

#### Scenario: New Model Version Deployed

1. **Admin navigates to Settings > System Health** (`/settings/health`)
2. **AI Model Status section shows:**
   - "Fall Detection: Healthy"
   - "Version: Current" (not the actual version number initially)
3. **If detailed view desired**, Admin clicks to expand:
   - "Updated: January 14, 2026 at 2:30 PM"
   - "Previous version retired"
4. **No disruption messaging** unless there was an issue

#### Scenario: Version Rollback Occurred

1. **System experienced issues with new version**
2. **Automatic rollback executed**
3. **Admin sees in System Health:**
   - "Fall Detection: Healthy — Rolled back"
   - "Rolled back at 3:15 PM due to elevated error rate"
4. **Audit Log shows:**
   - Timestamp, action ("Model rollback"), reason ("Error rate exceeded threshold")
5. **Admin understands** — A problem was detected and automatically resolved

---

### What Operators / Supervisors See

| Event | What They See |
|-------|---------------|
| New version deployed (successful) | Nothing — system continues normally |
| New version deployed (brief pause) | "Detection Paused" for a few seconds, then "Detection Active" |
| Rollback occurred (successful) | Nothing — system continues normally |
| Rollback with disruption | "Detection Paused" during rollback, then "Detection Active" |
| Upgrade in progress | If detection paused: "Detection Paused — will resume shortly" |

---

### Explicitly Defined: What Is Hidden

| What Is Hidden | From Whom | Why |
|----------------|-----------|-----|
| Model version numbers (v1.2.3) | Operators, Supervisors | Technical detail that erodes trust if seen |
| "Upgrading to v1.3.0" messages | Operators, Supervisors | Suggests instability |
| Rollback events | Operators, Supervisors | Implies failure; they only need to know current state |
| Deployment timestamps | Operators, Supervisors | Not relevant to their work |
| Upgrade progress percentage | All | Creates anxiety; either it works or it doesn't |

---

### Explicitly Defined: What Is Summarized

| What Is Summarized | For Whom | Presentation |
|--------------------|----------|--------------|
| "Model was recently updated" | Admin | In System Health detail view |
| "Rolled back due to issues" | Admin | In System Health with reason |
| "Last updated: [date]" | Admin | In AI Configuration settings |
| Upgrade history | Admin | In Audit Log |

---

### User Understanding Check

| Persona | What they believe | What they do next |
|---------|-------------------|-------------------|
| **Operator** | "Detection is working" (or paused, if applicable) | Continues normal monitoring |
| **Supervisor** | "System is fine" (or degraded, if applicable) | Continues normal work |
| **Admin** | "A new version was deployed successfully" | Monitors for issues |
| **Admin** | "There was a problem and it was rolled back" | Investigates in Audit Log |

---

### Explicit Non-Goals

The UI must NOT:
- Show version numbers to Operators or Supervisors
- Display "Upgrading..." progress bars
- Announce rollbacks to non-Admin users
- Expose deployment or CI/CD pipeline status
- Create upgrade-related anxiety

---

## Cross-Flow Validation

### Every Flow Maps to F2 Screens

| Flow | Screens Used |
|------|--------------|
| Flow 1: View Live Violations | Overview (`/`), Alerts List (`/alerts`), Camera View (`/cameras/:id`) |
| Flow 2: Drill Down | Alerts List (`/alerts`), Violation Detail (`/alerts/:id`) |
| Flow 3: Acknowledge/Dismiss | Violations List (`/alerts`), Violation Detail (`/alerts/:id`) |
| Flow 4: Model Health Degradation | Global Nav (all screens), Settings > System Health (`/settings/health`) |
| Flow 5: Model Unavailable | Camera View (`/cameras/:id`), Settings > System Health (`/settings/health`) |
| Flow 6: Version Upgrade | Settings > System Health (`/settings/health`), Audit Log (`/settings/audit`) |

---

### Every Failure State Has Clear User Explanation

| Failure | User Explanation |
|---------|------------------|
| Video delayed | "Delayed" indicator; no alarm |
| Low AI confidence | "Low Confidence" badge; muted styling |
| Camera offline | "Camera Offline" with last-seen timestamp |
| Evidence processing | "Preparing video..." with progress indication |
| Evidence unavailable | "Video clip unavailable" with snapshot fallback |
| Backend write failed | "Couldn't save. Please try again." |
| Duplicate action | "Already [action]" — informational, not error |
| Network offline | "Connection lost. Please check your connection." |
| Model degraded | "Detection may be slower or less accurate" |
| Model offline | "Detection Paused — will resume when available" |

---

### No Backend or AI Internals Exposed

Verified across all flows:
- No model names (fall_detection_v1.2.3)
- No event IDs
- No stream IDs
- No API error codes
- No database errors
- No pod/container references
- No confidence as raw numbers

---

### Operators Can Recover Without Admin Intervention

| Failure | Operator Recovery |
|---------|-------------------|
| Evidence not ready | Wait for processing; snapshot available immediately |
| Backend save failed | Retry button available |
| Network offline | Wait for connection; retry available |
| Camera offline | Continue with other cameras; existing violations remain |
| Model unavailable | Continue monitoring video; existing violations remain |

---

### Admins Can Diagnose Without Reading Logs

| Issue | Admin Diagnostic Path |
|-------|----------------------|
| Model slow | Settings > System Health > AI Model Status: "Degraded — high latency" |
| Model offline | Settings > System Health > AI Model Status: "Offline" |
| Service down | Settings > System Health > Service Status: "[Service]: Offline" |
| Recent changes | Settings > Audit Log |
| Version issues | Settings > System Health > "Rolled back" indicator |

---

### No Flow Requires Page Refresh

| Flow | Recovery Method |
|------|-----------------|
| New violations | Automatic updates (polling or WebSocket) |
| Action failed | Retry button (inline) |
| Network restored | Automatic reconnection |
| Model recovered | Automatic status update |
| Evidence ready | Automatic button update |

---

## Validation Checklist

- [x] Every flow maps to an existing F2 screen
- [x] Every failure state has a clear user explanation
- [x] No backend or AI internals are exposed
- [x] Operators can recover without Admin intervention
- [x] Admins can diagnose without reading logs
- [x] No flow requires a page refresh to recover
- [x] Confidence displayed categorically, never numerically
- [x] Model versions hidden from Operators and Supervisors
- [x] All messaging avoids blame-oriented language
- [x] Continuity of work preserved in all failure paths

---

**End of Document**

*This document allows a designer or engineer to simulate every critical user journey without seeing a single wireframe.*
