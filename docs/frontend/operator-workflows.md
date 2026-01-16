# Ruth AI — Operator Workflow Validation (Stress Testing)

| Meta             | Value                                           |
|------------------|-------------------------------------------------|
| Document ID      | RUTH-UX-F5                                      |
| Version          | 1.0                                             |
| Status           | Draft                                           |
| Owner            | Frontend UX Designer Agent                      |
| Input Documents  | F1 (Personas), F2 (IA), F3 (UX Flows), F4 (Wireframes) |
| Purpose          | Validate UX under operational chaos             |

---

## 1. Document Purpose

This document **stress-tests** the Ruth AI frontend design against real-world operational chaos. It validates that:

- Operators can continue working under pressure
- The UI handles ambiguity without confusion
- Partial system failure doesn't block core tasks
- Trust is maintained even when the backend is imperfect

**This task validates; it does not invent.** No new screens, components, or APIs are introduced.

---

## 2. Chaos Scenarios Overview

| Scenario | Category | Why It Matters |
|----------|----------|----------------|
| A1 | High Alert Volume | Tests queue management, priority visibility, cognitive load |
| A2 | Rapid-Fire Multi-Camera Alerts | Tests simultaneous attention demands |
| A3 | Mixed Confidence Flood | Tests trust calibration under volume |
| B1 | Some Cameras Offline | Tests partial visibility awareness |
| B2 | AI Detection Paused, Video Working | Tests understanding of split functionality |
| B3 | Backend Slow, Not Down | Tests patience and retry behavior |
| B4 | Evidence Unavailable for Some Violations | Tests graceful degradation of evidence |
| C1 | Model Healthy → Degraded → Healthy | Tests status flapping tolerance |
| C2 | Temporary Detection Pause | Tests recovery awareness |
| C3 | Auto-Recovery Without Action | Tests non-intervention confidence |

---

## 3. Scenario A: High Alert Volume

### A1: 20–50 Violations Arriving Within Minutes

**Context:** A genuine incident or environmental trigger causes a burst of detections across multiple cameras. Operators must triage rapidly without losing track.

#### Step-by-Step Operator Walkthrough

| Step | System State | Operator Action | UI Response |
|------|--------------|-----------------|-------------|
| 1 | First violation detected | Operator sees badge update: "1" → "5" rapidly | Badge animates count increase; no sound/alarm |
| 2 | Badge reaches "12" | Operator clicks Alerts nav item | Navigates to `/alerts` |
| 3 | Alerts List loads | Operator scans list | Sorted newest-first; high-confidence items have solid color borders |
| 4 | Operator processes first alert | Clicks "Acknowledge" on top item | Button shows brief loading, status updates to "Reviewed" |
| 5 | New violations arrive while working | — | New items prepend to list; badge updates; current position preserved |
| 6 | Operator acknowledges rapidly | Clicks through 5 items | Each action completes independently; no blocking |
| 7 | Operator needs to dismiss one | Clicks "Dismiss" | Confirmation dialog appears ("Mark as false positive?") |
| 8 | Confirms dismissal | Clicks "Yes, Dismiss" | Status changes to "Dismissed"; badge decrements; toast confirms |
| 9 | Volume stabilizes | Operator continues at normal pace | No special recovery needed |

#### Perception vs. Reality Table

| Dimension | System Truth | Operator Sees | Operator Believes | Why Acceptable | Intentionally Hidden |
|-----------|--------------|---------------|-------------------|----------------|----------------------|
| **Volume origin** | 47 events aggregated into 23 violations | "23 Open Alerts" | "There are 23 things I need to check" | Simple mental model | Event aggregation logic, model inference counts |
| **Arrival rate** | 3.2 violations/minute for 8 minutes | Badge updates frequently; list grows | "A lot is happening right now" | Matches reality without overwhelming | Exact timing, queue depth, processing backlog |
| **Priority order** | Confidence + recency sorting | High-confidence items visually distinct | "The important ones are easy to spot" | Visual hierarchy works | Sorting algorithm, confidence thresholds |
| **Action latency** | 150ms average API response | Instant feedback | "The system is keeping up with me" | Perceived responsiveness | Actual latency, retry logic, optimistic updates |
| **Scroll position** | New items prepend without scroll jump | List grows but view stays stable | "I can work without losing my place" | No cognitive disruption | DOM manipulation, virtual scrolling |

---

### A2: Multiple Cameras Triggering Simultaneously

**Context:** Three cameras detect violations within the same 30-second window. Each requires attention.

#### Step-by-Step Operator Walkthrough

| Step | System State | Operator Action | UI Response |
|------|--------------|-----------------|-------------|
| 1 | Camera A, B, C each detect a violation | — | Badge jumps to "3"; all three appear in Alerts |
| 2 | Operator scans Alerts List | Reviews the three items | Each shows camera name prominently; distinct confidence badges |
| 3 | Operator prioritizes | Clicks highest-confidence item (Camera B) | Opens Violation Detail |
| 4 | Reviews evidence | Views snapshot, considers playing video | Evidence available; actions visible |
| 5 | Takes action | Clicks "Acknowledge" | Returns to Alerts List (or stays on detail, per navigation) |
| 6 | Moves to next | Clicks Camera A violation | Opens that Violation Detail |
| 7 | Completes triage | Acknowledges or dismisses remaining | All three processed |

#### Perception vs. Reality Table

| Dimension | System Truth | Operator Sees | Operator Believes | Why Acceptable | Intentionally Hidden |
|-----------|--------------|---------------|-------------------|----------------|----------------------|
| **Simultaneous detection** | Events within 30s from different cameras | Three cards in list, different camera names | "Three cameras saw something" | Clear separation by camera | Detection timestamps at millisecond precision |
| **Which camera first** | Camera C was 2.1s before Camera A | All three appear in list | "They happened around the same time" | Sub-minute timing irrelevant for triage | Exact ordering if < 60s apart |
| **Why these cameras** | Model ran inference on all, three had detections | Three violations | "The AI found three things" | Result-oriented, not process-oriented | Inference pipeline, frames processed per camera |
| **Evidence availability** | All three have snapshots; video processing | Snapshot visible, "Play Evidence" available | "I can see what happened" | Primary evidence (snapshot) immediate | Bookmark encoding status, VAS internal state |

---

### A3: Mixed Confidence Flood

**Context:** 25 violations arrive with varied confidence levels (5 High, 12 Medium, 8 Low). Operator must calibrate trust appropriately.

#### Step-by-Step Operator Walkthrough

| Step | System State | Operator Action | UI Response |
|------|--------------|-----------------|-------------|
| 1 | 25 violations arrive | Operator opens Alerts List | List shows all 25 with confidence badges |
| 2 | Operator notices visual patterns | Scans for high-confidence items | 5 items have solid red borders, "High" badge |
| 3 | Processes high-confidence first | Clicks first high-confidence item | Opens Violation Detail |
| 4 | Evidence is clear | Views snapshot with clear detection | "High Confidence" badge reinforces |
| 5 | Acknowledges | Clicks "Acknowledge" | Status updates; moves to next |
| 6 | Reaches low-confidence item | Opens a "Low Confidence" violation | Muted styling, dashed border |
| 7 | Evidence is ambiguous | Snapshot shows unclear scene | No bounding box or faint overlay |
| 8 | Scrutinizes more carefully | May play video for context | Video provides additional context |
| 9 | Dismisses as false positive | Clicks "Dismiss" → confirms | Toast: "Violation dismissed" |
| 10 | Trusts categorization | Uses confidence as decision input | No numerical confusion |

#### Perception vs. Reality Table

| Dimension | System Truth | Operator Sees | Operator Believes | Why Acceptable | Intentionally Hidden |
|-----------|--------------|---------------|-------------------|----------------|----------------------|
| **Confidence mapping** | High: ≥0.8, Medium: 0.6-0.8, Low: <0.6 | "High / Medium / Low" badges | "High means the AI is pretty sure" | Categorical is actionable | Exact thresholds, raw scores |
| **Visual distinction** | CSS classes differ by confidence | Border weight, color saturation | "I can see which are important" | Immediate visual parsing | Styling implementation details |
| **Low confidence meaning** | Model less certain; possibly correct | "Low Confidence" badge, muted card | "I should look carefully at this one" | Appropriate skepticism encouraged | Why model was uncertain (occlusion, angle, etc.) |
| **False positive correlation** | Low confidence has higher FP rate | Low confidence items get scrutinized | "Low confidence = might be wrong" | Correct mental model | Statistical FP rates, model calibration curves |
| **No numbers shown** | Scores are 0.0-1.0 floats | Words only | "The AI gives me guidance, not precision" | Numbers create false certainty | All numerical confidence values |

---

## 4. Scenario B: Partial System Outages

### B1: Some Cameras Offline, Others Live

**Context:** 3 of 10 cameras lose connectivity. The other 7 continue operating normally.

#### Step-by-Step Operator Walkthrough

| Step | System State | Operator Action | UI Response |
|------|--------------|-----------------|-------------|
| 1 | Cameras 4, 7, 9 go offline | — | Per-camera status updates immediately |
| 2 | Operator is on Overview | Glances at camera summary | "7 / 10 Cameras Live" (was 10/10) |
| 3 | Operator notices change | Navigates to Cameras | Camera List shows 3 with "● Offline" indicator |
| 4 | Clicks offline camera | Opens Camera View for Camera 4 | Video frozen on last frame; "Camera Offline - Last seen 2m ago" overlay |
| 5 | Understands limitation | — | "Detection Paused" shown for this camera |
| 6 | Returns to live camera | Navigates to Camera 2 | Live video; "Detection Active" |
| 7 | Continues monitoring | Works with available cameras | No workflow blockage |
| 8 | Cameras reconnect | — | Status returns to "Live"; no notification needed |

#### Perception vs. Reality Table

| Dimension | System Truth | Operator Sees | Operator Believes | Why Acceptable | Intentionally Hidden |
|-----------|--------------|---------------|-------------------|----------------|----------------------|
| **Why offline** | Network switch failure, camera power loss, or VAS internal issue | "Camera Offline" | "The camera isn't working right now" | Operator can't fix it anyway | RTSP errors, VAS connection state, network diagnostics |
| **Which cameras** | Cameras 4, 7, 9 | Three show "Offline" indicator | "Three cameras are down" | Clear identification | Device IDs, stream IDs, VAS internal mapping |
| **Detection status** | AI has no frames to process | "Detection Paused" | "It can't detect anything if there's no video" | Logical causality | Frame pipeline state, model queue depth |
| **Last frame** | Frozen on most recent decoded frame | Last frame visible with overlay | "I can see what it last saw" | Context for investigation | Frame timestamp, decode state |
| **Recovery** | VAS auto-reconnects when possible | Status flips back to "Live" | "It fixed itself" | No operator action required | Reconnection logic, retry attempts |

---

### B2: AI Detection Paused, Video Working

**Context:** AI Runtime is down/slow, but VAS video streaming is unaffected. Operators can watch but not detect.

#### Step-by-Step Operator Walkthrough

| Step | System State | Operator Action | UI Response |
|------|--------------|-----------------|-------------|
| 1 | AI Runtime stops responding | — | Global status: "Healthy" → "Degraded" |
| 2 | Operator is watching Camera 3 | Continues viewing | Live video plays normally |
| 3 | Notices detection status | Reads per-camera indicator | "Detection Paused" (was "Detection Active") |
| 4 | Clicks global status indicator | — | Modal: "AI detection may be slower or less accurate. Video monitoring continues normally." |
| 5 | Closes modal | Clicks "OK" | Returns to Camera View |
| 6 | Continues monitoring visually | Watches video feeds | No blocking of video access |
| 7 | Existing violations still visible | Navigates to Alerts | Previous violations remain actionable |
| 8 | No new violations appear | — | List doesn't grow (expected) |
| 9 | AI recovers | — | Status returns; "Detection Active" resumes |

#### Perception vs. Reality Table

| Dimension | System Truth | Operator Sees | Operator Believes | Why Acceptable | Intentionally Hidden |
|-----------|--------------|---------------|-------------------|----------------|----------------------|
| **Split functionality** | VAS ≠ AI Runtime; independent systems | "Video works, detection doesn't" | "The cameras work but the AI is having issues" | Matches functional reality | System architecture, service boundaries |
| **Why paused** | AI Runtime pod crashed / high latency / circuit breaker | "Detection Paused" | "Something is wrong with the AI part" | Actionable awareness without blame | Pod status, gRPC errors, circuit breaker state |
| **Video unaffected** | VAS streaming independent of AI | Video plays normally | "At least I can still watch" | Core monitoring capability preserved | Transport layer separation |
| **Existing violations** | Database persists all prior detections | Alerts List unchanged | "My work isn't lost" | Continuity of work | Database state, API caching |
| **Recovery transparency** | Auto-recovery with health checks | Status returns to normal | "It fixed itself" | No operator intervention needed | Retry logic, pod restart, health probe sequence |

---

### B3: Backend Slow, Not Down

**Context:** Ruth AI Backend is responding slowly (2-5 second response times instead of <500ms). Not failing, just slow.

#### Step-by-Step Operator Walkthrough

| Step | System State | Operator Action | UI Response |
|------|--------------|-----------------|-------------|
| 1 | Backend latency increases | — | No immediate indicator (within threshold) |
| 2 | Operator clicks "Acknowledge" | — | Button shows loading state for 3 seconds |
| 3 | Action completes | — | Status updates; toast confirms |
| 4 | Latency persists | — | Global status may show "Degraded" if severe |
| 5 | Operator clicks another action | — | Same slow response |
| 6 | Operator continues working | — | Each action works, just slowly |
| 7 | Backend recovers | — | Response times return to normal |

#### Perception vs. Reality Table

| Dimension | System Truth | Operator Sees | Operator Believes | Why Acceptable | Intentionally Hidden |
|-----------|--------------|---------------|-------------------|----------------|----------------------|
| **Slowness source** | Database connection pool exhaustion | Buttons take longer | "The system is a bit slow right now" | Accurate perception | Database metrics, connection pool state |
| **Threshold for visibility** | Latency > 2s triggers loading state | Loading spinner on button | "It's working, just taking a moment" | Expected slow-response pattern | Exact latency, SLA thresholds |
| **When to show "Degraded"** | Latency P95 > 3s for 60 seconds | Global "Degraded" indicator | "There's a system issue" | Pattern recognition over individual events | P95 calculation, window size |
| **Actions succeed** | Requests eventually complete | Confirmation appears | "It worked, just slowly" | Functional success | Retry logic, timeout handling |
| **No data loss** | All mutations are persisted | Actions reflected in UI | "My work is saved" | Trust in persistence | Write-ahead log, transaction state |

---

### B4: Evidence Unavailable for Some Violations

**Context:** Some violations have full evidence (snapshot + video), some have snapshot only, some have nothing.

#### Step-by-Step Operator Walkthrough

| Step | System State | Operator Action | UI Response |
|------|--------------|-----------------|-------------|
| 1 | Operator opens Violation A | Full evidence available | Snapshot visible; "Play Evidence" button active |
| 2 | Operator opens Violation B | Video failed, snapshot exists | Snapshot visible; "Video clip unavailable" message |
| 3 | Operator opens Violation C | No evidence at all | "Evidence not available. Detection occurred at [timestamp] on [camera]." |
| 4 | For Violation C | Operator can still act | "Acknowledge", "Dismiss", "Escalate" all available |
| 5 | Operator makes decision | Based on camera context or escalates | Action completes normally |

#### Perception vs. Reality Table

| Dimension | System Truth | Operator Sees | Operator Believes | Why Acceptable | Intentionally Hidden |
|-----------|--------------|---------------|-------------------|----------------|----------------------|
| **Why no video** | VAS bookmark failed, recording gap, storage full | "Video clip unavailable" | "The recording didn't work for this one" | Explains limitation without blame | VAS error code, storage metrics, bookmark failure reason |
| **Why no snapshot** | Frame capture failed at detection time | Placeholder message | "There's no picture for this" | Honest about gap | Frame extraction failure, pipeline state |
| **Can still act** | Violation record exists independently | Action buttons available | "I can still handle this" | Evidence is helpful, not required | Evidence-action coupling logic |
| **Fallback strategy** | Snapshot → live camera → metadata only | Progressive disclosure | "I have what I have" | Best available information | Priority chain, fallback logic |
| **Future violations** | Next detection may have full evidence | Each violation independent | "This was a one-off" | No pattern anxiety | Success rate metrics |

---

## 5. Scenario C: Flapping Model Health

### C1: Model Transitioning Healthy → Degraded → Healthy

**Context:** AI model experiences intermittent issues, causing status to flip multiple times over 10 minutes.

#### Step-by-Step Operator Walkthrough

| Step | Time | System State | Operator Sees | Operator Action |
|------|------|--------------|---------------|-----------------|
| 1 | 0:00 | Model healthy | "Detection Active" | Normal monitoring |
| 2 | 2:00 | Model latency spikes | "Degraded" indicator appears | Notices yellow indicator |
| 3 | 2:30 | — | Clicks status indicator | Reads modal: "AI detection may be slower..." |
| 4 | 3:00 | Model recovers | "Healthy" indicator returns | Closes modal; continues |
| 5 | 5:00 | Model degrades again | "Degraded" indicator | Glances, doesn't click |
| 6 | 6:00 | Model recovers | "Healthy" indicator | Continues working |
| 7 | 8:00 | Model degrades | "Degraded" indicator | May mention to supervisor |
| 8 | 10:00 | Stabilizes healthy | "Healthy" indicator | Resumes normal confidence |

#### Perception vs. Reality Table

| Dimension | System Truth | Operator Sees | Operator Believes | Why Acceptable | Intentionally Hidden |
|-----------|--------------|---------------|-------------------|----------------|----------------------|
| **Flapping cause** | Resource contention, GC pauses, network jitter | Status changes color | "The AI is having intermittent issues" | Accurate high-level summary | Pod metrics, GC logs, network traces |
| **Number of transitions** | 6 state changes in 10 minutes | ~3 noticed changes | "It's been flaky for a bit" | Operator doesn't count; perceives pattern | Exact transition count, timing |
| **Alert fatigue** | System suppresses rapid transitions | No notification per change | "It's not spamming me" | Intentional UX decision | Debounce logic, notification suppression |
| **Detection gap** | Some frames may be skipped | "Detection may be delayed" | "It might miss something right now" | Honest about capability | Frame skip count, inference queue depth |
| **When to escalate** | Operator judgment | Can mention to supervisor | "Someone should know about this" | Appropriate escalation path | Formal escalation threshold |

---

### C2: Temporary Detection Pause (Auto-Recovery)

**Context:** AI model restarts (planned or crash), causing 45-second detection gap. Auto-recovers.

#### Step-by-Step Operator Walkthrough

| Step | Time | System State | Operator Sees | Operator Action |
|------|------|--------------|---------------|-----------------|
| 1 | 0:00 | Normal operation | "Detection Active" | Monitoring |
| 2 | 0:05 | Model process exits | "Detection Paused" | Notices indicator change |
| 3 | 0:10 | — | Status persists | Continues watching video |
| 4 | 0:30 | — | May click status | Modal: "Detection paused. Video continues." |
| 5 | 0:45 | Model restarts successfully | "Detection Active" returns | Notices recovery |
| 6 | 1:00 | Normal operation | — | Resumes normal workflow |

#### Perception vs. Reality Table

| Dimension | System Truth | Operator Sees | Operator Believes | Why Acceptable | Intentionally Hidden |
|-----------|--------------|---------------|-------------------|----------------|----------------------|
| **Pause cause** | OOM kill, scheduled restart, crash | "Detection Paused" | "The AI stopped for a minute" | No need to know cause | Pod lifecycle, OOM metrics, restart policy |
| **Recovery mechanism** | Kubernetes restarts pod, health check passes | Status returns to active | "It came back on its own" | Auto-recovery is expected | K8s orchestration, health probe sequence |
| **Gap coverage** | No detections during 45s window | No new violations in that period | "Nothing happened in that window" | Either true, or missed (acceptable risk) | Actual frame coverage, detection queue |
| **Video continuity** | VAS unaffected | Video never interrupted | "At least I could still watch" | Core capability preserved | System architecture separation |
| **Historical violations** | All prior detections persist | Alerts List unchanged | "My work wasn't affected" | Continuity of work | Database isolation |

---

### C3: Auto-Recovery Without Operator Action

**Context:** System experiences and recovers from an issue entirely in the background. Operator notices nothing or minimal disruption.

#### Step-by-Step Operator Walkthrough

| Step | Time | System State | Operator Sees | Operator Action |
|------|------|--------------|---------------|-----------------|
| 1 | 0:00 | Normal | "Healthy" | Working |
| 2 | 0:10 | Brief issue (< 10s) | — | Doesn't notice |
| 3 | 0:15 | Recovered | — | Continues normally |
| 4 | — | Logs show event | — | Never sees logs |

#### Perception vs. Reality Table

| Dimension | System Truth | Operator Sees | Operator Believes | Why Acceptable | Intentionally Hidden |
|-----------|--------------|---------------|-------------------|----------------|----------------------|
| **Issue occurred** | Transient network hiccup, retry succeeded | Nothing | "Everything is fine" | Brief issues don't warrant notification | Retry logs, transient errors |
| **System resilience** | Built-in retry, circuit breaker, fallback | Seamless operation | "The system is reliable" | Correct trust calibration | Resilience implementation |
| **Transparency threshold** | Only surface issues > 10s | No indicator change | "If I don't see it, it's not a problem" | Appropriate information filtering | Threshold configuration |
| **Admin visibility** | Full detail in Audit Log | (Operator doesn't see) | — | Role-appropriate access | Log entries, metrics |

---

## 6. Workflow Integrity Verification

### 6.1 No Dead Ends

Every scenario ends with a clear next action:

| Scenario | Dead End Risk | Prevention |
|----------|--------------|------------|
| High alert volume | Overwhelmed, freeze | Visual priority hierarchy; actions work independently |
| Camera offline | Can't monitor that camera | Can switch to other cameras; existing violations remain |
| AI paused | Can't detect | Video continues; existing work continues |
| Evidence missing | Can't verify | Can still act on detection; escalation available |
| Model flapping | Uncertainty | Status always visible; modal explains impact |

### 6.2 No Ambiguous States

Every state is clearly named and explained:

| Potential Ambiguity | Resolution |
|---------------------|------------|
| "Is the camera working?" | "Camera Offline" vs. "Live" indicator |
| "Is detection running?" | "Detection Active" vs. "Detection Paused" indicator |
| "Is the system working?" | Global status: "Healthy" / "Degraded" / "Offline" |
| "Is this action completing?" | Button loading state visible |
| "Did my action save?" | Toast confirmation appears |

### 6.3 Clear Trust Signals

| What System Knows | UI Signal |
|-------------------|-----------|
| Violation detected with high confidence | "High Confidence" badge, solid border |
| Violation detected with low confidence | "Low Confidence" badge, muted styling |
| Camera is connected and streaming | "● Live" indicator |
| Camera is disconnected | "○ Offline" with last-seen timestamp |
| AI is processing normally | "Detection Active" |
| AI is experiencing issues | "Degraded" indicator + modal explanation |

| What System Doesn't Know | UI Signal |
|--------------------------|-----------|
| Whether detection is correct | Confidence category (not certainty) |
| When camera will reconnect | "Camera Offline" (no ETA) |
| When AI will recover | "Detection Paused — will resume when available" |
| What happened during gap | (Honest about gap; no false claims) |

| What Operator Should Do Next | UI Signal |
|------------------------------|-----------|
| Review violation | Click card → Violation Detail |
| After acknowledging | Return to Alerts or stay on detail |
| If action fails | "Retry" button immediately available |
| If camera offline | Monitor other cameras; escalate if needed |
| If AI paused | Continue watching video; existing violations remain |

---

## 7. Trust Analysis

### 7.1 Where Trust Could Be Lost

| Trust Risk | Scenario | Consequence |
|------------|----------|-------------|
| **Silent failures** | Error occurs, UI shows nothing | Operator thinks system is working when it isn't |
| **Over-alerting** | Every minor issue triggers notification | Operator ignores all status indicators |
| **Blame language** | "Your action caused an error" | Operator hesitates to act |
| **Technical jargon** | "gRPC timeout on inference service" | Operator feels incompetent |
| **False precision** | "Confidence: 87.23%" | Operator over-trusts numerical appearance |
| **Hidden degradation** | AI is slow but status shows "Healthy" | Missed detections with no explanation |

### 7.2 How Design Prevents Trust Loss

| Prevention | Implementation | Source Document |
|------------|----------------|-----------------|
| **Visible status** | Global indicator always visible; per-camera indicators | F4 § Global Layout |
| **Debounced notifications** | Rapid transitions suppressed | F3 § Flow 4 |
| **Neutral language** | "Detection Paused" not "AI Failed" | F3 § Flow 5 |
| **Human-readable errors** | "Couldn't save. Please try again." | F3 § Flow 3 |
| **Categorical confidence** | "High / Medium / Low" only | F1 § UX Success Metrics |
| **Honest degradation** | "Degraded" shown when appropriate | F3 § Flow 4, F4 § 4.5 |

### 7.3 Trust Invariants (Confirmed)

| Invariant | Verification |
|-----------|--------------|
| **Operators never see runtime internals** | No pod names, no service names, no error codes in any wireframe |
| **Operators are never blamed** | All error messages use passive voice or system-focused language |
| **Operators are never blocked unnecessarily** | Every failure path preserves access to existing violations and live video |
| **Confidence is always categorical** | No numerical confidence values in any screen |
| **Status is always current** | "Last: X ago" timestamp on all data views |
| **Recovery is automatic where possible** | No "restart" buttons for operators; auto-retry built in |

---

## 8. UX Validation Checklist

### 8.1 Core Questions

| Question | Answer | Evidence |
|----------|--------|----------|
| **Can an operator continue work without Admin?** | Yes | Camera offline → other cameras work. AI paused → video works. Evidence missing → can still act. |
| **Are all states explainable in one sentence?** | Yes | "Camera Offline" = camera isn't connected. "Detection Paused" = AI isn't running. "Degraded" = AI is slow. |
| **Is "doing nothing" ever the correct action — and is that clear?** | Yes | During auto-recovery, operator can simply wait. Modal says "will resume when available." No action button suggests no action needed. |
| **Does the UI over-communicate failures?** | No | Transient issues (<10s) are not surfaced. Status changes are visual, not notification-based. No sound/alarm for degradation. |

### 8.2 Scenario-Specific Verification

| Scenario | Operator Can Continue? | System State Clear? | Trust Preserved? |
|----------|------------------------|---------------------|------------------|
| A1: High volume | ✓ Actions work independently | ✓ Badge count accurate | ✓ Visual priority guides |
| A2: Multi-camera | ✓ Each camera distinct | ✓ Camera names visible | ✓ No confusion about source |
| A3: Mixed confidence | ✓ All confidence levels actionable | ✓ Categorical badges clear | ✓ No false precision |
| B1: Cameras offline | ✓ Other cameras work | ✓ "Offline" indicator | ✓ Last-seen timestamp honest |
| B2: AI paused | ✓ Video continues | ✓ "Detection Paused" | ✓ Split functionality explained |
| B3: Backend slow | ✓ Actions complete | ✓ Loading states visible | ✓ No silent failures |
| B4: Evidence missing | ✓ Can still act | ✓ Clear "unavailable" message | ✓ No false promise of evidence |
| C1: Flapping health | ✓ Work continues | ✓ Status tracks reality | ✓ Debounced notifications |
| C2: Temp pause | ✓ Video continues | ✓ "Paused" indicator | ✓ Auto-recovery expected |
| C3: Silent recovery | ✓ Never interrupted | ✓ (Not surfaced) | ✓ System appears reliable |

### 8.3 Anti-Patterns Verified Absent

| Anti-Pattern | Present? | Check |
|--------------|----------|-------|
| **Spinner blocking entire UI** | No | Loading states are per-component |
| **"Error" with no retry option** | No | All errors have retry or navigation |
| **Technical error codes visible** | No | All errors in plain language |
| **Numerical confidence shown** | No | Categorical only |
| **Model version shown to operator** | No | "Detection" not "fall_detection_v1.2.3" |
| **Blame-oriented language** | No | Passive voice, system-focused |
| **Actions disabled during degradation** | No | Operators can always act on existing violations |
| **Silent data loss** | No | All failures produce visible feedback |
| **Required page refresh** | No | All recovery is automatic or button-based |

---

## 9. Edge Case Matrix

| Edge Case | System Behavior | Operator Experience |
|-----------|-----------------|---------------------|
| 100+ violations in queue | List paginated; badge shows count | Can page through; priority clear |
| All cameras offline | All show "Offline" | Clear there's a major issue; nothing blocked |
| All AI models down | "Detection Paused" everywhere | Video works; existing violations remain |
| Backend completely down | Actions fail with retry | Toast explains; can retry; work preserved |
| Network disconnected | Global "Connection lost" | Clear message; retry when reconnected |
| Only low-confidence violations | All show "Low Confidence" | Understands to scrutinize each |
| Evidence takes 5+ minutes | "Preparing video..." persists | Can act without video; snapshot available |
| Violation deleted while viewing | 404 with friendly message | "Return to Alerts" navigation |
| Duplicate dismiss attempt | "Already dismissed" toast | Informational, not error |
| Session expires during work | Modal with login prompt | Re-authenticate; work may need re-action |

---

## 10. Summary: Stress Test Results

### The Frontend Holds

| Dimension | Verdict |
|-----------|---------|
| **High volume** | Operators can process rapidly; visual hierarchy guides; no blocking |
| **Partial outages** | Operators understand what works vs. what doesn't; can continue |
| **Flapping health** | Status reflects reality; no alert fatigue; auto-recovery expected |
| **Evidence gaps** | Graceful degradation; actions remain available |
| **Backend slowness** | Actions complete; loading states visible; no silent failures |

### Trust Is Maintained

| Trust Dimension | Maintained? |
|-----------------|-------------|
| Operators understand system state | ✓ Always visible, always honest |
| Operators know what to do | ✓ Clear actions, no dead ends |
| Operators aren't blamed | ✓ Neutral language throughout |
| Operators can continue working | ✓ No blocking on peripheral failures |
| AI confidence is appropriately calibrated | ✓ Categorical, not numerical |

### The UI Never

- Lies about system state
- Panics with alarming notifications
- Goes silent during failures
- Blocks core work due to secondary failures
- Exposes technical internals
- Requires page refresh to recover

---

## 11. Document Cross-References

| Validation Point | Source Document | Section |
|------------------|-----------------|---------|
| Confidence categories | F1 (personas.md) | "What Operator Does NOT Care About" |
| Status indicators | F4 (wireframes.md) | "System Status Indicator States" |
| Error messaging | F3 (ux-flows.md) | "Failure / Degraded Paths" |
| Role visibility | F2 (information-architecture.md) | "Role-Based Visibility Summary" |
| Status filters | F2 (information-architecture.md) | "Design Decision: No Separate History Section" |
| Modal behavior | F4 (wireframes.md) | "System Status Click Behavior" |

---

**Document Status:** Ready for Review

**This document confirms:** The Ruth AI frontend design, as specified in F1–F4, maintains operator trust and workflow continuity under realistic operational stress.

---

**End of Document**
