# Ruth AI — Product UX Scope & Personas

**Version:** 1.0
**Owner:** Frontend UX Designer
**Status:** Approved / Frozen
**Last Updated:** January 2026

---

## Purpose

This document defines **who the Ruth AI frontend is for**, what success looks like for each user type, and what must be intentionally hidden or de-emphasized.

All frontend UX decisions—screens, workflows, components, and visual language—must trace back to this document. If a design choice cannot be justified by a persona goal, it should be questioned.

---

## Design Principles Derived from Personas

Before defining personas, these cross-cutting principles shape how we think about Ruth AI users:

1. **Operators are not engineers** — They don't know or care about WebRTC, frame rates, or model architectures.
2. **Trust must be calibrated** — AI confidence is not certainty. The UI must never suggest otherwise.
3. **Stress tolerance varies** — Operators may be fatigued, distracted, or managing multiple priorities.
4. **System state must be obvious** — No one should wonder "is this thing working?"
5. **Failure is not shameful** — When AI fails or video drops, the UI should explain what happened, not hide it.

---

## Persona 1: Operator (Live Monitoring)

### Role Definition

The **Operator** is the primary user of Ruth AI. They monitor live video feeds, observe AI detections in real time, and respond to potential safety violations such as fall incidents.

Operators work in **control room environments** or dedicated monitoring stations. They may be responsible for multiple camera feeds simultaneously. Their job is to **detect, acknowledge, and escalate** — not to investigate, configure, or manage systems.

### Context of Use

| Dimension | Description |
|-----------|-------------|
| **Environment** | Control room, security desk, or remote monitoring station |
| **Time pressure** | High — falls require immediate acknowledgment |
| **Frequency of use** | Continuous during shift (4-12 hour shifts typical) |
| **Typical session length** | Full shift (with breaks) |
| **Concurrent tasks** | May monitor multiple feeds, other security systems, phone, radio |
| **Physical context** | Seated, multiple monitors possible, ambient noise |

### Technical Sophistication Level

**Low to Medium**

- Comfortable with basic desktop/web applications
- Understands concepts like "camera," "alert," "video playback"
- Does **not** understand:
  - Video encoding, RTSP, WebRTC
  - AI models, confidence scores as raw numbers
  - Backend services, databases, APIs
  - Network architecture or connectivity details

### Decision Authority

| Authority | Scope |
|-----------|-------|
| **Can do** | Acknowledge violations, mark as reviewed, dismiss false positives |
| **Cannot do** | Resolve violations (requires Supervisor), configure cameras, change AI settings |
| **Escalation path** | Flags critical violations for Supervisor review |

---

### Primary Goals (What Success Looks Like)

| Goal | Description | Time-Critical? |
|------|-------------|----------------|
| **G1.1** See active violations immediately | When a fall is detected, the Operator knows within seconds | Yes |
| **G1.2** Understand what was detected | See the camera, timestamp, and visual representation of the detection | Yes |
| **G1.3** View live video with AI context | Watch the feed with detection overlays or status indicators | Yes |
| **G1.4** Acknowledge violations quickly | Mark a violation as "seen" with minimal clicks | Yes |
| **G1.5** Dismiss obvious false positives | Quickly mark detections that are clearly wrong | No |
| **G1.6** Know when something is broken | Immediately understand if a camera or AI model is not working | Yes |

### Secondary Goals (Nice-to-Have)

| Goal | Description |
|------|-------------|
| **G1.7** Review recent violations | Scroll through recent activity without leaving the main view |
| **G1.8** Replay evidence video | Play the bookmark/clip associated with a violation |
| **G1.9** Filter violations by camera | Narrow the view to a specific camera of interest |

---

### What the Operator Does NOT Care About

This section is **critical**. Exposing these details harms usability and trust.

| Category | What to Hide | Why |
|----------|--------------|-----|
| **AI Internals** | Model name (e.g., "fall_detection_v1.2.3"), model architecture, inference latency, batch size | Operators evaluate results, not models. Exposing version numbers suggests the system is unstable. |
| **Frame Pipeline** | FPS, frame queue depth, dropped frames, backpressure status | This is system health, not operator-relevant. Show simplified status instead. |
| **Video Transport** | WebRTC, MediaSoup, RTSP, codecs, transport errors | The video either works or doesn't. Technical details don't help operators fix it. |
| **Backend/Infrastructure** | Service names, pod status, database queries, API errors | Operators don't troubleshoot infrastructure. Show "system issue" not "PostgreSQL timeout." |
| **Confidence as Raw Numbers** | Showing "0.8723" or "87.23%" | Numbers create false precision. Use categorical buckets: "High Confidence," "Medium Confidence," "Low Confidence." |
| **Raw Bounding Box Coordinates** | x:142, y:234, w:200, h:400 | Meaningless to operators. Show visual overlays instead. |
| **Event vs. Violation Distinction** | The fact that multiple "events" aggregate into one "violation" | Operators see violations. The event abstraction is internal. |
| **VAS as a Separate System** | That video comes from "VAS" and AI comes from "Ruth AI" | The UI should present a unified experience. "Camera offline" not "VAS stream unavailable." |

---

### Failure Tolerance

| Failure Type | Acceptable Response | Unacceptable Response |
|--------------|---------------------|----------------------|
| Camera offline | Show clear "Camera Offline" status with last known timestamp | Blank screen with no explanation |
| AI model not responding | Show "Detection Paused" status, continue showing video | Freeze the UI or show cryptic errors |
| Video stuttering | Show degraded indicator, continue best-effort display | Hide the problem or pretend video is fine |
| Backend unavailable | Show "System Connectivity Issue" with retry indication | Crash, white screen, or vague "Error" |

---

## Persona 2: Supervisor (Review & Escalation)

### Role Definition

The **Supervisor** manages the operator team and is responsible for **reviewing escalated violations**, making final disposition decisions, and ensuring quality of response. They may also investigate incidents that require historical playback.

Supervisors are not continuously monitoring live feeds. They are **called upon** when something significant happens.

### Context of Use

| Dimension | Description |
|-----------|-------------|
| **Environment** | Office adjacent to control room, or remote access |
| **Time pressure** | Medium — urgent for escalations, low for routine reviews |
| **Frequency of use** | Periodic — several times per shift, more during incidents |
| **Typical session length** | 5-30 minutes per session |
| **Concurrent tasks** | Managing team, incident reports, coordination calls |
| **Physical context** | Often on laptop, may be mobile |

### Technical Sophistication Level

**Medium**

- Comfortable with business applications, dashboards
- Understands incident management workflows
- May grasp basic concepts like "AI detected this"
- Does **not** understand:
  - Model training, inference, or architecture
  - Network or infrastructure details
  - API or service-level concepts

### Decision Authority

| Authority  | Scope |
|------------|-------|
| **Can do** | Resolve violations, override operator decisions, access historical data |
| **Cannot do** | Configure AI settings, manage cameras, administer users |
| **Escalation path** | Escalates to Admin for system issues |

---

### Primary Goals (What Success Looks Like)

| Goal | Description | Time-Critical? |
|------|-------------|----------------|
| **G2.1** Review escalated violations | See violations flagged by operators for review | Medium |
| **G2.2** Make final disposition | Mark violations as "resolved" or "dismissed" with authority | Medium |
| **G2.3** Investigate incidents | Replay video evidence, see timeline of related detections | No |
| **G2.4** Understand shift activity | See summary of violations during a time period | No |
| **G2.5** Verify operator performance | See how operators handled violations (acknowledgment times, dispositions) | No |

### Secondary Goals (Nice-to-Have)

| Goal | Description |
|------|-------------|
| **G2.6** Export incident data | Generate reports for external stakeholders |
| **G2.7** Compare camera activity | See which cameras have the most violations |

---

### What the Supervisor Does NOT Care About

| Category | What to Hide | Why |
|----------|--------------|-----|
| **AI Model Details** | Version numbers, inference metrics, model switching | Supervisors evaluate outcomes, not models |
| **Frame/Pipeline Stats** | FPS, latency, queue depth | Not relevant to incident review |
| **Real-Time System Health** | They're not monitoring; Admins handle this | Show only if it affects an incident they're reviewing |
| **Raw API/Backend Data** | JSON responses, database IDs, service names | Abstraction is key |
| **Operator Workflow Details** | The exact screens operators use | Supervisors need outcomes, not process |

---

### Failure Tolerance

| Failure Type | Acceptable Response | Unacceptable Response |
|--------------|---------------------|----------------------|
| Evidence video unavailable | Show "Video Processing" or "Video Unavailable" with snapshot fallback | Broken video player with no explanation |
| Historical data slow to load | Show loading indicator, allow other actions | Freeze entire UI |
| Export fails | Clear error with retry option | Silent failure |

---

## Persona 3: Admin (Configuration & Health)

### Role Definition

The **Admin** is responsible for **system configuration, health monitoring, and troubleshooting**. They ensure Ruth AI is operational, cameras are correctly configured, and AI models are performing as expected.

Admins are the **only persona** who may need to see some system internals — but even then, the UI should present actionable information, not raw metrics.

### Context of Use

| Dimension | Description |
|-----------|-------------|
| **Environment** | IT office, remote access, or server room |
| **Time pressure** | Low (routine) to High (incident response) |
| **Frequency of use** | Daily for health checks; on-demand for configuration |
| **Typical session length** | 10-60 minutes |
| **Concurrent tasks** | Managing other IT systems, tickets, documentation |
| **Physical context** | Desktop with multiple tools open |

### Technical Sophistication Level

**High**

- Understands system architecture at a conceptual level
- Comfortable with dashboards, logs, and metrics
- Knows terms like "service," "API," "health check"
- May **not** deeply understand:
  - AI/ML concepts (training, inference, models)
  - Video encoding internals
  - Ruth AI codebase

### Decision Authority

| Authority | Scope |
|-----------|-------|
| **Can do** | Configure cameras, adjust AI settings (thresholds), view system health, manage users |
| **Cannot do** | Resolve violations (that's Supervisor), deploy new AI models (that's DevOps/AI Team) |
| **Escalation path** | Escalates to DevOps/Engineering for infrastructure issues |

---

### Primary Goals (What Success Looks Like)

| Goal | Description | Time-Critical? |
|------|-------------|----------------|
| **G3.1** See system health at a glance | Know if all cameras, AI models, and services are working | Medium |
| **G3.2** Identify failing components | Quickly pinpoint what is broken when something goes wrong | Yes (during incidents) |
| **G3.3** Configure camera→AI assignment | Control which cameras are monitored by AI | No |
| **G3.4** Adjust detection thresholds | Change confidence thresholds per camera or globally | No |
| **G3.5** Manage user access | Add/remove operators, supervisors, admins | No |
| **G3.6** View operational analytics | See violation counts, false positive rates, system performance trends | No |

### Secondary Goals (Nice-to-Have)

| Goal | Description |
|------|-------------|
| **G3.7** View AI model performance | See detection accuracy metrics over time |
| **G3.8** Audit user actions | See who changed settings and when |

---

### What the Admin Does NOT Care About

| Category | What to Hide | Why |
|----------|--------------|-----|
| **Individual Violation Details** | Full violation review workflows | That's Operator/Supervisor territory |
| **Model Weights/Architecture** | Internal model structure | Admins configure, not train |
| **Infrastructure Primitives** | Pod names, node IPs, container hashes | Admins see service health, not K8s internals |
| **Raw Logs** | Full log streams | Provide searchable, filtered views instead |
| **VAS Internal Details** | MediaSoup routers, transport IDs | Abstract to "camera status" |

---

### What the Admin MAY See (with Appropriate Abstraction)

Unlike Operators and Supervisors, Admins may see **some** system internals, but always **abstracted and actionable**:

| Concept | Acceptable Presentation | Unacceptable Presentation |
|---------|------------------------|---------------------------|
| AI Model health | "Fall Detection: Healthy" / "Degraded" / "Offline" | "fall_detection_v1.2.3 pod 3/3 running" |
| Inference rate | "Processing 45 frames/second across 8 cameras" | "ruth_ai_inference_throughput_fps: 45.23" |
| Video connectivity | "Camera X: Connected" / "Camera X: No video signal" | "WebRTC ICE state: failed" |
| Service health | "Ruth AI Backend: Healthy" / "Ruth AI Backend: Degraded (slow responses)" | "HTTP 503 from ruth-ai-backend-7d9f8" |

---

### Failure Tolerance

| Failure Type | Acceptable Response | Unacceptable Response |
|--------------|---------------------|----------------------|
| Service down | Clear status indicator with "Last seen X minutes ago" | Stale "Healthy" status |
| Config save fails | Error message with specific issue and retry option | Silent failure |
| Health data stale | Timestamp showing data age | Presenting stale data as current |

---

## UX Success Metrics

Success is measured by whether users can accomplish their goals efficiently and confidently. These metrics apply across personas.

### Quantitative Metrics

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| **Time to acknowledge violation** | < 10 seconds from detection | Measure timestamp delta: detection → acknowledgment |
| **False positive dismissal rate** | Track trend over time | Count dismissals vs. resolutions |
| **Violation backlog** | < 5 unacknowledged violations | Monitor open violation count |
| **System health check time** | Admin can assess health in < 30 seconds | Usability testing |
| **Evidence playback success rate** | > 99% successful playback | Track video load failures |

### Qualitative Metrics

| Metric | Description | Measurement Method |
|--------|-------------|-------------------|
| **Perceived latency** | Users feel the system is responsive | User interviews, satisfaction surveys |
| **Cognitive load** | Users are not overwhelmed by information | Usability testing, heuristic evaluation |
| **Error clarity** | Users understand what went wrong and what to do | Error message comprehension testing |
| **System state confidence** | Users trust they know what is working and what isn't | Usability testing, interviews |
| **AI trust calibration** | Users appropriately trust/distrust AI outputs | Track over-reliance (accepting all) vs. under-reliance (dismissing all) |

### Trust Calibration Indicators

| Indicator | Healthy Sign | Unhealthy Sign |
|-----------|--------------|----------------|
| **Dismissal patterns** | Dismissals correlate with low-confidence detections | Dismissals are random or excessive |
| **Investigation frequency** | Operators investigate before dismissing uncertain detections | Operators never investigate, or investigate everything |
| **Escalation rate** | Appropriate escalations to Supervisor | No escalations (over-confidence) or excessive escalations (under-confidence) |

---

## Persona → Capability Matrix

This matrix defines what each persona can **see** and **do** within Ruth AI.

### Read/View Capabilities

| Capability                   | Operator             | Supervisor       | Admin            |
|------------------------------|----------------------|------------------|------------------|
| View live video feed         | ✓                    | ✓                | ✓                |
| View AI detection overlays   | ✓                    | ✓                | ✓                |
| View active violations       | ✓                    | ✓                | ✓                |
| View violation details       | ✓                    | ✓                | ✓                |
| View evidence (snapshot)     | ✓                    | ✓                | ✓                |
| View evidence (video clip)   | ✓                    | ✓                | ✓                |
| View historical violations   | Limited (shift only) | ✓ (full history) | ✓ (full history) |
| View violation analytics     | —                    | ✓                | ✓                |
| View system health dashboard | —                    | —                | ✓                |
| View AI model status         | —                    | —                | ✓                |
| View camera configuration    | —                    | —                | ✓                |
| View user list               | —                    | —                | ✓                |
| View audit logs              | —                    | —                | ✓                |

### Action Capabilities

| Capability                         | Operator | Supervisor | Admin |
|------------------------------------|----------|------------|-------|
| Acknowledge violation              | ✓        | ✓          | —     |
| Mark violation as reviewed         | ✓        | ✓          | —     |
| Mark violation as reviewed         | ✓        | ✓          | —     |
| Dismiss violation (false positive) | ✓        | ✓          | —     |
| Resolve violation                  | —        | ✓          | —     |
| Override operator decision         | —        | ✓          | —     |
| Escalate violation                 | ✓        | —          | —     |
| Configure cameras                  | —        | —          | ✓     |
| Configure AI thresholds            | —        | —          | ✓     |
| Enable/disable cameras for AI      | —        | —          | ✓     |
| Manage users                       | —        | —          | ✓     |
| Restart/recover services           | —        | —          | ✓ (if exposed) |
| Export reports                     | —        | ✓          | ✓     |

### Forbidden Capabilities (Principle of Least Surprise)

| Capability | Forbidden For | Reason |
|------------|---------------|--------|
| Access raw API responses | All | Leaks implementation details |
| View model weights/architecture | All | Leaks AI internals |
| Modify AI models | All (including Admin) | Requires engineering deployment |
| Access VAS directly | All | Ruth AI is the interface, VAS is abstracted |
| View other users' sessions | Operator, Supervisor | Privacy, scope creep |
| Delete violations | All | Audit trail integrity |
| Bypass authentication | All | Security |

---

## Summary: Persona Differentiation

| Persona | Primary Focus | Session Pattern | Stress Level | Technical Depth |
|---------|---------------|-----------------|--------------|-----------------|
| **Operator** | Real-time monitoring & response | Continuous (full shift) | High (time-critical) | Low |
| **Supervisor** | Review, escalation, investigation | Periodic (on-demand) | Medium | Medium |
| **Admin** | Configuration, health, troubleshooting | Scheduled + incident response | Variable | High |

---

## Appendix: Terminology Alignment

To ensure consistency with project documents, the following terms are used:

| UI Term | Internal/Technical Term | Source |
|---------|------------------------|--------|
| Camera | Device (VAS) | VAS API |
| Detection | Event (Ruth AI Backend) | Architecture |
| Violation | Violation (Ruth AI Backend) | PRD, Architecture |
| Video Clip | Bookmark (VAS) | VAS API |
| Snapshot | Snapshot (VAS) | VAS API |
| AI Status | Model health / AI Runtime status | Architecture |
| System Health | Service health (Backend, Runtime, VAS) | Infrastructure |

---

**End of Document**
