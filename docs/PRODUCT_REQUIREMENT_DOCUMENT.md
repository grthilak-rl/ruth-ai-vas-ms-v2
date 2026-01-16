# Ruth AI – Product Requirement Document (PRD)

**Version:** 0.1 (Draft)

**Prepared By:** Rajthilak

**Audience:** Product, Architecture, Backend, AI, Frontend, DevOps teams

---

## 1. Purpose of This Document

This document defines the **functional and non-functional requirements** for **Ruth AI**, an AI-powered video intelligence platform that consumes video streams from **VAS-MS-V2** and applies computer vision models to detect, record, and present events (e.g., fall detection).

This PRD serves as the **single source of truth** for:

* Product scope and boundaries
* What Ruth AI *will* and *will not* do
* Inputs for the Software Architect agent

---

## 2. Product Vision

**Ruth AI** is a **VAS-dependent video intelligence platform** whose primary responsibility is:

> *Consume live video streams via VAS APIs, apply AI models in real time, generate meaningful events, and present those events to operators and downstream systems.*

Ruth AI **does not manage cameras, RTSP, MediaSoup, or video transport**. These concerns are explicitly owned by VAS.

---

## 3. Key Design Principles (Non-Negotiable)

1. **VAS is the single video gateway**
   Ruth AI must *only* interact with video via documented VAS APIs.

2. **AI-first, not video-first**
   Ruth AI treats video as input data, not as a media product.

3. **Contract-driven integration**
   Ruth AI relies on canonical API contracts, not raw documentation.

4. **Pluggable AI models**
   AI models must be treated as interchangeable components.

5. **Fail-safe behavior**
   Video failures must not crash the AI system.

---

## 4. In-Scope Capabilities (What Ruth AI Will Do)

### 4.1 Video Consumption

* Consume **live WebRTC streams** via VAS-MS-V2
* Support **multiple concurrent camera streams**
* Handle stream reconnects gracefully
* Extract frames from live streams for AI inference

### 4.2 AI Inference & Execution Model

* Apply computer vision models to live video frames
* **AI models run as shared services**:

  * A **single model container/runtime** can subscribe to **multiple camera streams**
  * Models are **not instantiated per camera**
* Models receive frames from multiple sources through a scheduling layer
* Initial supported model:

  * **Fall Detection**
* Support configurable inference FPS per model
* Ensure one model failure does not crash other streams

### 4.3 Event Generation

* Convert AI model outputs into structured **events**
* Example events:

  * `fall_detected`
  * `no_fall`
* Attach metadata:

  * Timestamp
  * Confidence
  * Bounding boxes (if available)

### 4.4 Violation & Incident Management

* Introduce **Violation** as a first-class domain concept
* A Violation represents a confirmed or potential safety incident detected by AI
* Each Violation must include:

  * Violation type (e.g., fall_detected)
  * Associated camera / stream
  * Timestamp(s)
  * Confidence score
  * AI model version
  * Status (`open`, `reviewed`, `dismissed`, `resolved`)

### 4.5 Evidence Creation (via VAS)

* Create **snapshots** using VAS Snapshot APIs
* Create **bookmarks (video clips)** using VAS Bookmark APIs
* Link evidence explicitly to Violations

### 4.6 Analytics (Operational)

* Provide **basic operational analytics** in v1:

  * Number of violations per camera
  * Violations per time window
  * Last detected event per camera
* Analytics are **derived from events and violations**, not raw video

### 4.7 User Interface (Operator Portal)

* List available devices (via VAS)
* View live video feeds
* Display AI detection status (overlay or panel)
* View violations and event timeline

### 4.8 API Exposure

* Expose Ruth AI APIs for:

  * Violation retrieval
  * Event retrieval
  * Analytics summaries
  * Model status
  * Health monitoring

---

## 5. Out-of-Scope (Explicitly Not Included)

Ruth AI **will not**:

* Manage RTSP connections
* Run FFmpeg
* Manage MediaSoup routers or transports
* Perform camera provisioning
* Store raw video permanently
* Replace VAS recording mechanisms
* Provide video analytics without VAS
* Provide **advanced analytics dashboards or BI tooling** in v1
* Perform automated incident resolution

---

## 6. Primary User Personas

### 6.1 System Operator

* Views live feeds
* Monitors AI detections
* Reviews incidents

### 6.2 Platform Integrator (Future)

* Consumes Ruth AI APIs
* Integrates events into external systems

---

## 7. Functional Requirements

### 7.1 Device & Stream Management

* Fetch device list from VAS
* Start or reuse existing streams
* Track active streams locally

### 7.2 Frame Pipeline

* Extract frames from WebRTC video
* Normalize frames for model input
* Throttle frame rate per model

### 7.3 AI Model Execution

* Load models at startup or on demand
* Execute inference safely
* Handle model failures without stopping streams

### 7.4 Event Handling

* Generate structured event records
* Deduplicate noisy detections
* Apply confidence thresholds

### 7.5 Evidence Linking

* Trigger snapshot creation on events
* Trigger bookmark creation on significant events
* Store mapping between event ↔ evidence

---

## 8. Non-Functional Requirements

### 8.1 Performance

* Live inference latency target: < 1 second
* Support minimum 10 FPS per stream for inference

### 8.2 Scalability

* Support multiple cameras per instance
* Horizontal scalability preferred

### 8.3 Reliability

* Graceful degradation if:

  * Stream drops
  * Model crashes
  * VAS API temporarily unavailable

### 8.4 Security

* No direct exposure of VAS credentials
* Secure handling of access tokens
* Role-based access for UI and APIs

### 8.5 Observability

* Logging of:

  * Stream lifecycle
  * AI inference results
  * Errors
* Basic metrics:

  * FPS processed
  * Inference latency

---

## 9. Assumptions & Constraints

* VAS-MS-V2 is stable and authoritative for video
* WebRTC is the primary transport
* Initial deployment is controlled (not public SaaS)
* Fall detection model is considered production-ready for v1

---

## 10. MVP Definition

**Ruth AI v1 MVP includes:**

* Device listing via VAS
* Live video feed consumption
* Shared AI model runtime (single model container, multiple cameras)
* Fall detection on live streams
* Violation creation and lifecycle management
* Snapshot & bookmark creation on fall events
* Basic operational analytics
* Simple operator UI

**Excluded from MVP:**

* Multi-model orchestration
* Advanced analytics dashboards
* Alerting systems (SMS, email, etc.)
* Long-term data warehousing
* Automated incident resolution

---

## 11. Success Criteria

The product is considered successful if:

* Live VAS streams are consumed reliably
* AI models run on live feeds
* Fall events are detected and verifiable
* Evidence (snapshot/bookmark) is generated correctly
* Operators can visually confirm detections

---

**End of Document**
