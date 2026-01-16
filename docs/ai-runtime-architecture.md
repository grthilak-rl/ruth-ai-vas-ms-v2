# Ruth AI Runtime – Internal Architecture Design

**Version:** 1.0
**Author:** AI Platform Engineer Agent
**Date:** January 2026
**Status:** PHASE 5 – Task A1 Deliverable (DESIGN ONLY)

---

## Executive Summary

This document defines the **internal architecture** of the Ruth AI Runtime as a **multi-model platform**. It specifies how the runtime discovers, loads, isolates, and executes AI models as opaque plugins—without any knowledge of model semantics.

**Key Design Principles:**

1. **Model-Agnostic Runtime Core** – The runtime knows nothing about what models do; it only knows how to load and execute them
2. **Plugin Architecture** – Models are self-describing packages that register capabilities at load time
3. **Failure Isolation** – One model's failure cannot crash the runtime or affect other models
4. **Zero-Disruption Integration** – Adding a new model requires no runtime core changes
5. **Explicit Contracts** – All model behavior is declared, never inferred

**This document is design-only. No implementation code is provided.**

---

## Table of Contents

1. [Design Scope & Boundaries](#1-design-scope--boundaries)
2. [Logical Architecture Overview](#2-logical-architecture-overview)
3. [Model Loading Lifecycle](#3-model-loading-lifecycle)
4. [Plugin Boundaries](#4-plugin-boundaries)
5. [Execution Isolation Model](#5-execution-isolation-model)
6. [Failure Domains](#6-failure-domains)
7. [Capability Registration Flow](#7-capability-registration-flow)
8. [Interaction With Backend AI Runtime Client](#8-interaction-with-backend-ai-runtime-client)
9. [Invariants & Design Constraints](#9-invariants--design-constraints)
10. [Non-Goals](#10-non-goals)
11. [Validation Criteria](#11-validation-criteria)

---

## 1. Design Scope & Boundaries

### 1.1 What This Document Covers

| Aspect | In Scope |
|--------|----------|
| Model discovery mechanism | How models are found at runtime startup |
| Model contract specification | What models must declare to be loadable |
| Loading and validation lifecycle | Steps from discovery to ready-for-inference |
| Plugin boundary definitions | What the runtime owns vs. what models own |
| Execution isolation semantics | How inference is isolated per model |
| Failure domain mapping | What fails when something breaks |
| Capability registration protocol | How models advertise themselves |
| Backend interaction model | Request/response patterns, abstraction preservation |

### 1.2 What This Document Does NOT Cover

| Aspect | Explicitly Excluded | Rationale |
|--------|---------------------|-----------|
| Fall detection model specifics | No | Fall detection is a reference model, not special |
| Implementation code | No | This is design-only |
| GPU/CPU/Jetson specifics | No | Hardware is abstracted via capability declaration |
| Backend API design | No | Covered in Phase 2 API Contract Specification |
| Infrastructure deployment | No | Covered in Phase 3 Infrastructure Design |
| Kubernetes/Docker specifics | No | Platform-agnostic design |

### 1.3 Prerequisite Documents

This design builds upon and must not contradict:

| Document | Path | Status |
|----------|------|--------|
| System Architecture | `docs/RUTH_AI_SYSTEM_ARCHITECTURE_DESIGN.md` | Frozen |
| API Contract Specification | `docs/RUTH_AI_API_CONTRACT_SPECIFICATION.md` | Frozen |
| Infrastructure Design | `docs/infrastructure-deployment-design.md` | Frozen |
| Product Requirements | `docs/PRODUCT_REQUIREMENT_DOCUMENT.md` | Approved |

---

## 2. Logical Architecture Overview

### 2.1 Component Diagram (Textual)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            AI RUNTIME PLATFORM                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                          RUNTIME CORE                                      │ │
│  │                    (Model-Agnostic Orchestration)                          │ │
│  │                                                                            │ │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐ │ │
│  │  │  Model Registry │  │  Model Loader   │  │    Capability Reporter      │ │ │
│  │  │                 │  │                 │  │                             │ │ │
│  │  │  - Discovery    │  │  - Validation   │  │  - Aggregates model caps    │ │ │
│  │  │  - Registration │  │  - Loading      │  │  - Reports to Backend       │ │ │
│  │  │  - Version mgmt │  │  - Lifecycle    │  │  - Health aggregation       │ │ │
│  │  └────────┬────────┘  └────────┬────────┘  └──────────────┬──────────────┘ │ │
│  │           │                    │                          │                │ │
│  │           └────────────────────┼──────────────────────────┘                │ │
│  │                                │                                           │ │
│  │                                ▼                                           │ │
│  │  ┌───────────────────────────────────────────────────────────────────────┐ │ │
│  │  │                      REQUEST ROUTER                                   │ │ │
│  │  │                                                                       │ │ │
│  │  │  - Routes inference requests to correct model executor                │ │ │
│  │  │  - Enforces model version pinning                                     │ │ │
│  │  │  - Handles model-not-found errors                                     │ │ │
│  │  └─────────────────────────────────┬─────────────────────────────────────┘ │ │
│  │                                    │                                       │ │
│  └────────────────────────────────────│───────────────────────────────────────┘ │
│                                       │                                         │
│  ┌────────────────────────────────────│───────────────────────────────────────┐ │
│  │                         ISOLATION BOUNDARY                                 │ │
│  ├────────────────────────────────────│───────────────────────────────────────┤ │
│  │                                    ▼                                       │ │
│  │  ┌────────────────────────────────────────────────────────────────────┐    │ │
│  │  │                      MODEL EXECUTORS                               │    │ │
│  │  │            (One per loaded model, failure-isolated)                │    │ │
│  │  │                                                                    │    │ │
│  │  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐           │    │ │
│  │  │  │  Executor:    │  │  Executor:    │  │  Executor:    │           │    │ │
│  │  │  │  fall_det     │  │  helmet_det   │  │  fire_det     │           │    │ │
│  │  │  │  v1.0.0       │  │  v0.1.0       │  │  v2.1.0       │           │    │ │
│  │  │  │               │  │               │  │               │           │    │ │
│  │  │  │  - Owns model │  │  - Owns model │  │  - Owns model │           │    │ │
│  │  │  │    weights    │  │    weights    │  │    weights    │  ...      │    │ │
│  │  │  │  - Owns       │  │  - Owns       │  │  - Owns       │           │    │ │
│  │  │  │    pre/post   │  │    pre/post   │  │    pre/post   │           │    │ │
│  │  │  │  - Isolated   │  │  - Isolated   │  │  - Isolated   │           │    │ │
│  │  │  │    failure    │  │    failure    │  │    failure    │           │    │ │
│  │  │  └───────────────┘  └───────────────┘  └───────────────┘           │    │ │
│  │  │                                                                    │    │ │
│  │  └────────────────────────────────────────────────────────────────────┘    │ │
│  │                                                                            │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                        MODEL PLUGINS (FILESYSTEM)                        │   │
│  │                                                                          │   │
│  │  ai/models/                                                              │   │
│  │  ├── fall_detection/                                                     │   │
│  │  │   └── 1.0.0/                                                          │   │
│  │  │       ├── model.yaml  ◄── Model contract                              │   │
│  │  │       ├── weights/                                                    │   │
│  │  │       ├── preprocessing.py                                            │   │
│  │  │       ├── inference.py                                                │   │
│  │  │       └── postprocessing.py                                           │   │
│  │  ├── helmet_detection/                                                   │   │
│  │  │   └── 0.1.0/                                                          │   │
│  │  │       ├── model.yaml                                                  │   │
│  │  │       └── ...                                                         │   │
│  │  └── fire_detection/                                                     │   │
│  │      └── 2.1.0/                                                          │   │
│  │          ├── model.yaml                                                  │   │
│  │          └── ...                                                         │   │
│  │                                                                          │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Component Responsibilities

| Component | Responsibility | Owns | Does NOT Own |
|-----------|----------------|------|--------------|
| **Model Registry** | Tracks all discovered and loaded models | Model catalog, version index | Model weights, inference logic |
| **Model Loader** | Validates and loads model plugins | Loading lifecycle, validation | Model semantics, inference |
| **Request Router** | Routes inference requests to correct executor | Request dispatch, version resolution | Frame data, inference results |
| **Capability Reporter** | Reports platform capabilities to Backend | Aggregated capabilities, health | Per-model metrics (only aggregates) |
| **Model Executor** | Executes inference for a single model | Model weights, pre/post processing, inference | Other models, runtime core state |

### 2.3 Key Boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│                     BOUNDARY: Runtime Core                      │
│                                                                 │
│  • Knows: model_id, version, input_type, output_schema          │
│  • Does NOT know: what the model detects, how it works          │
│  • Responsibility: Orchestration, not inference                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │ ISOLATION BOUNDARY │
                    └─────────┬─────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│                     BOUNDARY: Model Plugin                      │
│                                                                 │
│  • Knows: Everything about its domain (fall, helmet, fire, etc.)│
│  • Does NOT know: Other models, runtime internals, Backend      │
│  • Responsibility: Inference only                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Model Loading Lifecycle

### 3.1 Lifecycle States

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  DISCOVERED │───>│  VALIDATING │───>│   LOADING   │───>│    READY    │
└─────────────┘    └──────┬──────┘    └──────┬──────┘    └─────────────┘
                          │                  │                   │
                          ▼                  ▼                   ▼
                   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
                   │   INVALID   │    │   FAILED    │    │    ERROR    │
                   │  (rejected) │    │  (load err) │    │  (runtime)  │
                   └─────────────┘    └─────────────┘    └─────────────┘
                                                                │
                                                                ▼
                                                         ┌─────────────┐
                                                         │  UNLOADING  │
                                                         └─────────────┘
                                                                │
                                                                ▼
                                                         ┌─────────────┐
                                                         │  UNLOADED   │
                                                         └─────────────┘
```

### 3.2 State Definitions

| State | Description | Transitions To |
|-------|-------------|----------------|
| **DISCOVERED** | Model directory found, not yet validated | VALIDATING |
| **VALIDATING** | Contract (model.yaml) being parsed and validated | LOADING, INVALID |
| **INVALID** | Contract validation failed (terminal for this version) | - |
| **LOADING** | Model weights and code being loaded into memory | READY, FAILED |
| **FAILED** | Loading failed (OOM, missing dependencies, etc.) | UNLOADING (after cleanup) |
| **READY** | Model is loaded and available for inference | ERROR, UNLOADING |
| **ERROR** | Runtime error occurred, model needs recovery | UNLOADING |
| **UNLOADING** | Model is being removed from memory | UNLOADED |
| **UNLOADED** | Model removed, can be re-discovered | DISCOVERED |

### 3.3 Discovery Mechanism

**Discovery Algorithm:**

1. **Directory Scan:** On startup, scan the configured model root directory (`ai/models/`)
2. **Model Detection:** Each subdirectory containing a versioned subdirectory with `model.yaml` is a model
3. **Version Enumeration:** All versioned subdirectories (matching semver pattern) are enumerated
4. **Registry Update:** Each discovered model+version pair is added to the Model Registry with state `DISCOVERED`

**Discovery Trigger Points:**

| Trigger | Action |
|---------|--------|
| Runtime startup | Full directory scan |
| Runtime SIGHUP | Re-scan, add new models (no existing model disruption) |
| Admin API call (optional) | Targeted rescan of specific model directory |

**Discovery Rules:**

- New models discovered after startup are added with state `DISCOVERED`
- Existing models are NOT re-validated unless explicitly requested
- Missing model directories result in model state transition to `UNLOADED` (not immediate failure)
- Symlinks are followed (allows dynamic model deployment)

### 3.4 Validation Phase

**Contract Validation Checklist:**

| Check | Failure Behavior |
|-------|------------------|
| `model.yaml` exists | State → INVALID |
| `model.yaml` is valid YAML | State → INVALID |
| Required fields present (model_id, version, input_type, output_schema) | State → INVALID |
| Version matches directory name | State → INVALID |
| Input type is recognized (frame, batch, temporal) | State → INVALID |
| Output schema is parseable | State → INVALID |
| Inference entry point exists (inference.py or declared) | State → INVALID |
| Hardware compatibility matches runtime (if declared) | State → INVALID |

**Validation is non-blocking:**
- Validation failure for one model does NOT block other models
- Failed validation is logged with specific error reason
- Runtime continues with remaining valid models

### 3.5 Loading Phase

**Loading Sequence:**

1. **Allocate Executor:** Create isolated Model Executor for this model+version
2. **Load Weights:** Load model weights into memory (CPU or GPU based on capability)
3. **Load Code:** Import preprocessing, inference, postprocessing modules
4. **Warmup Inference:** Execute one inference with synthetic data to verify pipeline
5. **Register Ready:** Update Model Registry state to READY, report capability

**Loading Failure Handling:**

| Failure Type | Action |
|--------------|--------|
| Out of Memory (OOM) | State → FAILED, log error, do NOT retry automatically |
| Missing dependency | State → FAILED, log dependency name |
| Warmup inference fails | State → FAILED, log inference error |
| Timeout (>60s default) | State → FAILED, kill loading process |

**Critical Rule:** A failed model load NEVER affects other models. Each model loads in its own isolated context.

### 3.6 Version Conflict Handling

**Conflict Scenario:** Multiple versions of the same model exist.

**Resolution Rules:**

1. **All versions are loaded** if sufficient resources exist
2. **Requests specify version:** Backend requests include `model_id` and `version`
3. **No default version:** If version not specified, request fails with `VERSION_REQUIRED` error
4. **Resource exhaustion:** If memory insufficient, load priority is:
   - Explicitly requested versions (via configuration)
   - Higher versions (semver comparison)
   - Stop loading when resources exhausted, log which versions were skipped

**Version Coexistence Invariant:**
- Version 1.0.0 and 1.1.0 of the same model CAN run simultaneously
- Each version has its own Model Executor instance
- No shared state between versions

---

## 4. Plugin Boundaries

### 4.1 What Constitutes a "Model Plugin"

A Model Plugin is a self-contained directory with the following structure:

```
<model_id>/
└── <version>/
    ├── model.yaml           # REQUIRED: Model contract
    ├── weights/             # REQUIRED: Model weights directory
    │   └── model.onnx       # or model.pt, model.pth, etc.
    ├── inference.py         # REQUIRED: Inference entry point
    ├── preprocessing.py     # OPTIONAL: Input preprocessing
    ├── postprocessing.py    # OPTIONAL: Output postprocessing
    ├── requirements.txt     # OPTIONAL: Model-specific dependencies
    └── config.yaml          # OPTIONAL: Model-specific configuration
```

### 4.2 Model Contract Schema (model.yaml)

```yaml
# model.yaml - REQUIRED fields
model_id: "fall_detection"          # Unique identifier (alphanumeric + underscore)
version: "1.0.0"                    # Semantic version, must match directory name
display_name: "Fall Detection"      # Human-readable name

# Input specification
input:
  type: "frame"                     # frame | batch | temporal
  format: "jpeg"                    # jpeg | png | raw_rgb | raw_bgr
  min_width: 320                    # Minimum input width
  min_height: 240                   # Minimum input height
  max_width: 1920                   # Maximum input width (optional)
  max_height: 1080                  # Maximum input height (optional)
  channels: 3                       # RGB = 3

# Output specification
output:
  schema:
    event_type:
      type: "string"
      enum: ["fall_detected", "no_fall", "person_detected"]
    confidence:
      type: "float"
      min: 0.0
      max: 1.0
    bounding_boxes:
      type: "array"
      items:
        type: "object"
        properties:
          x: { type: "integer" }
          y: { type: "integer" }
          width: { type: "integer" }
          height: { type: "integer" }
          label: { type: "string" }
          confidence: { type: "float" }

# Hardware compatibility
hardware:
  supports_cpu: true
  supports_gpu: true
  supports_jetson: true
  min_gpu_memory_mb: 2048           # Optional

# Performance hints
performance:
  recommended_batch_size: 4
  recommended_fps: 30
  inference_time_hint_ms: 50        # Expected inference time

# Entry points (defaults if not specified)
entry_points:
  inference: "inference.py"         # Default
  preprocess: "preprocessing.py"    # Optional
  postprocess: "postprocessing.py"  # Optional
```

### 4.3 Runtime Core Ownership vs. Model Ownership

| Aspect | Runtime Core Owns | Model Plugin Owns |
|--------|-------------------|-------------------|
| Model discovery | ✓ | |
| Contract validation | ✓ | |
| Memory allocation | ✓ | |
| Model weights | | ✓ |
| Preprocessing logic | | ✓ |
| Inference logic | | ✓ |
| Postprocessing logic | | ✓ |
| Input/output schema | ✓ (validates) | ✓ (declares) |
| Error handling | ✓ (catches, isolates) | ✓ (throws) |
| Health reporting | ✓ (aggregates) | ✓ (per-model) |
| Timeout enforcement | ✓ | |
| Request routing | ✓ | |
| Capability advertisement | ✓ (aggregates) | ✓ (declares) |

### 4.4 Preventing Shared State Access

**Isolation Mechanisms:**

1. **No Global State:** Model plugins MUST NOT access global runtime state
2. **No Inter-Model Communication:** Models cannot call other models directly
3. **Read-Only Configuration:** Models receive configuration at load time, cannot modify
4. **Isolated Logging:** Each model logs with model_id prefix, no shared log buffers
5. **No Filesystem Writes Outside Model Directory:** Models cannot write outside their directory (enforced by executor sandbox)

**Enforcement via Model Executor:**

The Model Executor provides a restricted execution context:

```
┌─────────────────────────────────────────────────────────────┐
│                     MODEL EXECUTOR                          │
│                                                             │
│  Provides to Model:                                         │
│  ├── Input frame data (read-only)                           │
│  ├── Model configuration (read-only)                        │
│  ├── Logger (scoped to model_id)                            │
│  └── Metrics collector (scoped to model_id)                 │
│                                                             │
│  Does NOT Provide:                                          │
│  ├── Access to other models                                 │
│  ├── Access to runtime core internals                       │
│  ├── Network access (beyond configured allowlist)           │
│  ├── Filesystem access outside model directory              │
│  └── Direct GPU memory management                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.5 Separation Summary

```
┌─────────────────────────────────────────────────────────────┐
│                     RUNTIME CORE                            │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │  "I know THAT models exist and HOW to run them,      │   │
│  │   but I don't know WHAT they do."                    │   │
│  │                                                      │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     MODEL PLUGIN                            │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │  "I know WHAT I detect and HOW I detect it,          │   │
│  │   but I don't know about other models or the         │   │
│  │   runtime that hosts me."                            │   │
│  │                                                      │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     BACKEND                                 │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │  "I know WHICH models are available and their        │   │
│  │   capabilities, but I don't know their internals     │   │
│  │   or how they execute."                              │   │
│  │                                                      │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Execution Isolation Model

### 5.1 Logical Isolation (Not OS-Level)

This design specifies **logical isolation**, not operating system process isolation. The isolation is enforced through:

1. **Separate Executor Instances:** Each model gets its own Model Executor object
2. **Independent Memory Pools:** Each model's weights are loaded separately (no sharing)
3. **Exception Boundaries:** Exceptions in one model's inference are caught at the executor level
4. **Timeout Enforcement:** Each inference call has a timeout; exceeding it marks only that model as unhealthy

**Why Not Process Isolation:**
- Process-per-model adds significant overhead (IPC, memory duplication)
- GPU context switching between processes is expensive
- Logical isolation with exception handling is sufficient for most failures
- Process isolation can be added later if required (design allows upgrade path)

### 5.2 Inference Execution Flow

```
┌─────────────────┐
│ Inference       │
│ Request         │
│ (frame_id,      │
│  camera_id,     │
│  model_id,      │
│  version,       │
│  frame_data)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Request Router  │───► Lookup model_id:version in Registry
│                 │
│ If not found:   │───► Return MODEL_NOT_FOUND error
│ If not READY:   │───► Return MODEL_NOT_READY error
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Model Executor  │◄── Timeout timer starts
│ (specific to    │
│  model+version) │
│                 │
│ 1. Preprocess   │───► Call model's preprocessing.py
│                 │
│ 2. Inference    │───► Call model's inference.py
│                 │
│ 3. Postprocess  │───► Call model's postprocessing.py
│                 │
│ 4. Validate     │───► Validate output against declared schema
│    Output       │
└────────┬────────┘
         │
         ▼ (Timeout timer stops)
┌─────────────────┐
│ Inference       │
│ Response        │
│ (event_type,    │
│  confidence,    │
│  bounding_boxes,│
│  inference_ms)  │
└─────────────────┘
```

### 5.3 Exception Handling

**Exception Hierarchy:**

| Exception Source | Caught At | Effect on Model | Effect on Runtime |
|------------------|-----------|-----------------|-------------------|
| Preprocessing error | Executor | Health degraded, error returned | None |
| Inference error | Executor | Health degraded, error returned | None |
| Postprocessing error | Executor | Health degraded, error returned | None |
| Schema validation error | Executor | Health degraded, error returned | None |
| Timeout exceeded | Executor | State → ERROR | None |
| Out of Memory | Executor | State → ERROR, may need restart | None (other models continue) |
| GPU error (CUDA) | Executor | State → ERROR | Check if GPU still functional |
| Executor crash | Runtime Core | State → ERROR, executor restarted | None (other models continue) |

### 5.4 Timeout Specification

**Timeout Configuration:**

| Timeout Type | Default | Configurable | Per-Model |
|--------------|---------|--------------|-----------|
| Inference timeout | 5000ms | Yes (env var) | Yes (model.yaml) |
| Preprocessing timeout | 1000ms | Yes | Yes |
| Postprocessing timeout | 1000ms | Yes | Yes |
| Total request timeout | 7000ms | Yes | No (derived) |

**Timeout Behavior:**

1. Timer starts when request enters Model Executor
2. If any phase exceeds its timeout, processing is interrupted
3. Model state transitions to ERROR (temporary)
4. Error response returned to caller
5. After N consecutive timeouts (configurable, default 3), model marked UNHEALTHY
6. Model remains loaded; health can recover if subsequent requests succeed

### 5.5 One Model's Failure Does NOT Affect Others

**Failure Isolation Guarantee:**

```
┌─────────────────────────────────────────────────────────────────────┐
│                         RUNTIME STATE                               │
│                                                                     │
│  Model A (fall_detection:1.0.0)    State: READY    Health: HEALTHY  │
│  Model B (helmet_detection:0.1.0)  State: ERROR    Health: UNHEALTHY│
│  Model C (fire_detection:2.1.0)    State: READY    Health: HEALTHY  │
│                                                                     │
│  ───────────────────────────────────────────────────────────────────│
│                                                                     │
│  Model B crashed (OOM during inference).                            │
│                                                                     │
│  ✓ Model A continues receiving and processing requests              │
│  ✓ Model C continues receiving and processing requests              │
│  ✓ Runtime Core continues operating normally                        │
│  ✓ Backend is notified of Model B's unhealthy status                │
│  ✓ Requests for Model B return error, but don't block               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 6. Failure Domains

### 6.1 Failure Domain Taxonomy

```
┌─────────────────────────────────────────────────────────────────────┐
│                      FAILURE DOMAIN MAP                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Level 1: PER-INFERENCE FAILURE                                     │
│  ─────────────────────────────                                      │
│  Scope: Single inference request                                    │
│  Recovery: Automatic (next request unaffected)                      │
│  Examples:                                                          │
│    - Malformed input frame                                          │
│    - Single inference timeout                                       │
│    - Transient GPU error                                            │
│                                                                     │
│  Level 2: PER-MODEL FAILURE                                         │
│  ───────────────────────────                                        │
│  Scope: All requests to one model                                   │
│  Recovery: Manual or automatic model reload                         │
│  Examples:                                                          │
│    - Model OOM                                                      │
│    - Corrupted model weights                                        │
│    - Repeated inference failures                                    │
│                                                                     │
│  Level 3: RUNTIME-WIDE FAILURE                                      │
│  ─────────────────────────────                                      │
│  Scope: All models, all requests                                    │
│  Recovery: Runtime restart required                                 │
│  Examples:                                                          │
│    - GPU hardware failure                                           │
│    - Runtime core panic (should be rare)                            │
│    - Total memory exhaustion                                        │
│                                                                     │
│  Level 4: FATAL FAILURE                                             │
│  ─────────────────────                                              │
│  Scope: Entire platform                                             │
│  Recovery: Container restart required                               │
│  Examples:                                                          │
│    - Process crash                                                  │
│    - Unrecoverable GPU state                                        │
│    - Kernel panic (outside runtime control)                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 Failure Classification

| Failure | Domain Level | Runtime Continues? | Other Models Affected? | Recovery Action |
|---------|--------------|-------------------|------------------------|-----------------|
| Bad input frame | 1 (Inference) | Yes | No | Return error, log, continue |
| Single timeout | 1 (Inference) | Yes | No | Return error, track for health |
| Inference exception | 1 (Inference) | Yes | No | Return error, track for health |
| Repeated model failure | 2 (Model) | Yes | No | Mark model unhealthy, continue |
| Model OOM | 2 (Model) | Yes | No | Unload model, attempt reload |
| Model weights corrupted | 2 (Model) | Yes | No | Mark invalid, cannot reload |
| GPU memory fragmentation | 3 (Runtime) | Maybe | Yes | May need runtime restart |
| All GPU memory exhausted | 3 (Runtime) | Maybe | Yes | Unload models until memory freed |
| GPU driver crash | 3 (Runtime) | No | Yes | Runtime restart needed |
| Process crash | 4 (Fatal) | No | Yes | Container restart |

### 6.3 Recovery Strategies

**Level 1 Recovery (Automatic):**
```
Inference fails
    │
    ▼
Log error with frame_id, model_id
    │
    ▼
Return error response to Backend
    │
    ▼
Increment error counter for model
    │
    ▼
If error_count < threshold: No state change
If error_count >= threshold: Transition to UNHEALTHY
```

**Level 2 Recovery (Model Reload):**
```
Model in ERROR state
    │
    ▼
After cooldown period (configurable, default 30s)
    │
    ▼
Attempt automatic reload
    │
    ▼
If reload succeeds: State → READY
If reload fails: Remain in ERROR, schedule next retry
    │
    ▼
After max_retries (default 3): Stop retrying, require manual intervention
```

**Level 3 Recovery (Runtime Intervention):**
```
Runtime-wide issue detected (e.g., GPU problem)
    │
    ▼
Report to Backend via health endpoint (degraded/unhealthy)
    │
    ▼
Attempt graceful recovery if possible
    │
    ▼
If recovery fails: Require external restart (container orchestrator)
```

### 6.4 What Failures Are Contained at Model Level

✓ **Contained at Model Level:**
- Exceptions during inference
- Timeout during inference
- Model-specific OOM
- Invalid model output
- Model code bugs
- Model weight loading failure

✗ **NOT Contained at Model Level (Affect Runtime):**
- GPU driver crash
- Total system memory exhaustion
- Unhandled panic in runtime core
- Network stack failure
- Container runtime failure

### 6.5 Runtime Continuation When Model is Unhealthy

**Invariant:** The runtime MUST continue operating when any subset of models is unhealthy.

**Behavior Matrix:**

| Total Models | Healthy | Unhealthy | Runtime Status | Backend Sees |
|--------------|---------|-----------|----------------|--------------|
| 3 | 3 | 0 | HEALTHY | All models available |
| 3 | 2 | 1 | DEGRADED | 2 models available, 1 unhealthy |
| 3 | 1 | 2 | DEGRADED | 1 model available, 2 unhealthy |
| 3 | 0 | 3 | UNHEALTHY | No models available |

**Runtime Status Calculation:**
- HEALTHY: All loaded models are healthy
- DEGRADED: At least one model healthy, at least one unhealthy
- UNHEALTHY: No healthy models (but runtime itself is still running)

---

## 7. Capability Registration Flow

### 7.1 Registration Protocol

**When Registration Occurs:**
1. Runtime startup (after all initial models loaded)
2. Model state change (loaded, unloaded, health change)
3. Periodic heartbeat (every 30 seconds)

**Registration Endpoint:**
Backend exposes: `POST /api/internal/runtime/register`

### 7.2 Capability Declaration Structure

```json
{
  "runtime_id": "ai-runtime-001",
  "version": "1.0.0",
  "timestamp": "2026-01-14T10:00:00.000Z",

  "hardware": {
    "type": "gpu",
    "supports_gpu": true,
    "gpu_name": "NVIDIA Tesla T4",
    "gpu_memory_total_mb": 16384,
    "gpu_memory_available_mb": 12000,
    "cuda_version": "12.1"
  },

  "capacity": {
    "max_fps_total": 100,
    "max_concurrent_streams": 10,
    "recommended_batch_size": 4,
    "current_utilization_percent": 45
  },

  "models": [
    {
      "model_id": "fall_detection",
      "version": "1.0.0",
      "state": "READY",
      "health": "HEALTHY",
      "input_type": "frame",
      "output_schema_version": "1.0",
      "performance": {
        "avg_inference_time_ms": 50,
        "p99_inference_time_ms": 85,
        "fps_capacity": 50
      }
    },
    {
      "model_id": "helmet_detection",
      "version": "0.1.0",
      "state": "READY",
      "health": "DEGRADED",
      "input_type": "frame",
      "output_schema_version": "1.0",
      "performance": {
        "avg_inference_time_ms": 80,
        "p99_inference_time_ms": 150,
        "fps_capacity": 30
      }
    }
  ],

  "health_summary": {
    "status": "degraded",
    "total_models": 2,
    "healthy_models": 1,
    "degraded_models": 1,
    "unhealthy_models": 0,
    "last_error": "helmet_detection: inference timeout at 10:02:15"
  }
}
```

### 7.3 Capability Derivation from Model Contracts

**Flow:**

```
Model Contract (model.yaml)
         │
         ▼
┌─────────────────────────────────────────┐
│        RUNTIME AGGREGATION              │
│                                         │
│  For each model:                        │
│    - Extract model_id, version          │
│    - Extract input_type                 │
│    - Extract output_schema              │
│    - Extract hardware requirements      │
│    - Collect runtime performance stats  │
│                                         │
│  Aggregate:                             │
│    - Sum FPS capacities → max_fps_total │
│    - Union hardware support             │
│    - Aggregate health status            │
│                                         │
└─────────────────────────────────────────┘
         │
         ▼
Capability Declaration (JSON)
         │
         ▼
POST /api/internal/runtime/register
         │
         ▼
Backend stores in Redis, adapts scheduling
```

### 7.4 Health Reporting Hierarchy

**Per-Model Health:**
- Each model tracks its own health independently
- Health is based on: inference success rate, latency, error count

**Health States:**
| Health | Criteria |
|--------|----------|
| HEALTHY | Error rate < 1%, latency within hints, no recent failures |
| DEGRADED | Error rate 1-10%, OR latency elevated, OR recovering from failure |
| UNHEALTHY | Error rate > 10%, OR model not responding, OR in ERROR state |

**Aggregated Runtime Health:**
- Reported to Backend
- Reflects worst health among all models (conservative)
- Includes summary counts

### 7.5 Alignment with Backend AI Runtime Client

**From API Contract Specification (Phase 2):**

```protobuf
// AI Runtime Service - processes video frames through AI models
service AIRuntime {
  rpc Infer(InferenceRequest) returns (InferenceResponse);
  rpc InferStream(stream InferenceRequest) returns (stream InferenceResponse);
  rpc HealthCheck(HealthCheckRequest) returns (HealthCheckResponse);
  rpc GetModelStatus(ModelStatusRequest) returns (ModelStatusResponse);
}
```

**Alignment Mapping:**

| Backend Expects | Runtime Provides |
|-----------------|------------------|
| `HealthCheck` RPC | Aggregated health from Capability Reporter |
| `GetModelStatus` RPC | Per-model status from Model Registry |
| `Infer` RPC | Routed through Request Router to Model Executor |
| Model capability info | Registered via `/api/internal/runtime/register` |

---

## 8. Interaction With Backend AI Runtime Client

### 8.1 Request/Response Flow (Conceptual)

```
┌──────────────┐                      ┌──────────────┐
│   BACKEND    │                      │  AI RUNTIME  │
│              │                      │              │
│ Frame        │                      │              │
│ Scheduler    │                      │ Request      │
│              │     gRPC Infer       │ Router       │
│              │─────────────────────>│              │
│              │                      │              │
│              │                      │    │         │
│              │                      │    ▼         │
│              │                      │ Model        │
│              │                      │ Executor     │
│              │                      │ (isolated)   │
│              │                      │              │
│              │  InferenceResponse   │              │
│              │<─────────────────────│              │
│              │                      │              │
│ Event        │                      │              │
│ Engine       │                      │              │
│              │                      │              │
└──────────────┘                      └──────────────┘
```

### 8.2 Who Initiates What

| Action | Initiator | Direction |
|--------|-----------|-----------|
| Inference request | Backend | Backend → Runtime |
| Inference response | Runtime | Runtime → Backend |
| Capability registration | Runtime | Runtime → Backend |
| Health poll | Backend | Backend → Runtime |
| Model status query | Backend | Backend → Runtime |

**Key Rule:** Backend NEVER directly controls model loading/unloading. Runtime manages its own model lifecycle.

### 8.3 What Backend Is Allowed to Know

**Backend MAY know:**
- Which models are available (model_id, version)
- Model input types (frame, batch, temporal)
- Model output schema structure
- Model health status
- Model performance characteristics (fps, latency)
- Runtime hardware type (cpu, gpu, jetson)

**Backend MUST NOT know:**
- How models work internally
- What detection logic models use
- Model weights or architecture
- How preprocessing/postprocessing works
- GPU memory allocation details
- Model-specific dependencies

### 8.4 How Abstraction Is Preserved

**Abstraction Mechanisms:**

1. **Opaque Identifiers:** Backend uses model_id + version, never model internals
2. **Schema-Only Output:** Backend receives structured output matching declared schema
3. **Black-Box Inference:** Backend sends frame, receives result, no intermediate visibility
4. **Capability-Based Scheduling:** Backend adapts to declared capabilities, never inspects runtime
5. **Health, Not Diagnostics:** Backend sees health status, not diagnostic details

**Violation Examples (What Runtime Must Prevent):**

| Violation | Why It's Wrong | Prevention |
|-----------|----------------|------------|
| Backend requests "activate fall pose detection" | Model-specific knowledge | Only allow model_id, not model internals |
| Backend adjusts GPU memory allocation | Hardware detail leak | Capability-only interface |
| Backend receives "person lying down" raw output | Model semantic leak | Schema-validated output only |
| Backend directly loads model file | Lifecycle encapsulation | No model management endpoints exposed |

---

## 9. Invariants & Design Constraints

### 9.1 Absolute Invariants (MUST NEVER BE VIOLATED)

| ID | Invariant | Rationale |
|----|-----------|-----------|
| I1 | A new model can be added without modifying runtime core code | Platform extensibility |
| I2 | A broken model cannot crash the runtime | System resilience |
| I3 | Backend code never contains model-specific logic | Separation of concerns |
| I4 | Fall detection can be removed without breaking the platform | No special-case models |
| I5 | Multiple model versions can coexist | Safe upgrades |
| I6 | Models cannot access each other's state | Isolation guarantee |
| I7 | Runtime core does not interpret model output semantics | Model-agnostic design |
| I8 | Configuration is declarative, not imperative | Predictable behavior |

### 9.2 Design Constraints

| Constraint | Description | Impact |
|------------|-------------|--------|
| No model-specific code paths in runtime | All models use same loading/execution path | Uniform treatment |
| No runtime rebuild for new models | Models loaded from filesystem at runtime | Dynamic extension |
| Model failures are isolated | Executor catches all exceptions | Continued operation |
| No GPU assumptions in contracts | Hardware declared, not assumed | Portability |
| Configuration must be declarative | model.yaml, not code | Transparency |
| Platform scales to unknown future models | No hardcoded model limits | Future-proof |

### 9.3 Backward Compatibility Rules

| Change Type | Allowed? | Requirement |
|-------------|----------|-------------|
| Add new optional field to model.yaml | Yes | Default value in runtime |
| Add new required field to model.yaml | Yes | Version bump, migration guide |
| Remove field from model.yaml | Yes | Deprecation period (6 months) |
| Change field type | No | New field with new name |
| Change model.yaml structure | No | New schema version |

---

## 10. Non-Goals

This design explicitly does NOT address:

| Non-Goal | Rationale |
|----------|-----------|
| Fall detection implementation | Fall detection is just a reference model |
| Specific ML framework requirements | Models can use any framework |
| GPU memory management algorithms | Implementation detail |
| Model training or fine-tuning | Runtime is for inference only |
| Model distribution or deployment | Deployment is Phase 3 scope |
| Real-time streaming optimization | Performance tuning is implementation |
| Multi-GPU scheduling | Single runtime = single GPU (scale via replicas) |
| Federated or distributed inference | Out of v1 scope |
| Model marketplace or discovery | Future enhancement |

---

## 11. Validation Criteria

### 11.1 Design Correctness Checks

| Check | How to Validate |
|-------|-----------------|
| New model addable without runtime changes | Create model directory, verify runtime discovers and loads it |
| Broken model cannot crash runtime | Inject failing model, verify other models continue |
| Backend remains abstracted | Audit Backend code for model-specific imports or logic |
| Fall detection removable | Delete fall_detection directory, verify runtime continues |
| Multiple versions coexist | Load same model with two versions, verify both serve requests |

### 11.2 Integration Verification

| Integration Point | Verification |
|-------------------|--------------|
| Runtime → Backend registration | Backend receives capability declaration |
| Backend → Runtime inference | Inference requests route correctly to models |
| Runtime → Backend health | Health endpoint reflects model states |
| Model → Executor isolation | Exception in one model doesn't affect others |

### 11.3 Failure Scenario Tests

| Scenario | Expected Outcome |
|----------|------------------|
| Model throws exception during inference | Error returned, model marked degraded |
| Model exceeds timeout | Request cancelled, timeout error returned |
| Model consumes all GPU memory | Model marked unhealthy, other models continue |
| Model directory deleted while running | Model transitions to UNLOADED gracefully |
| Invalid model.yaml added | Model marked INVALID, runtime continues |

---

## Appendix A: Model State Transition Reference

```
                                    ┌───────────────────────┐
                                    │      DISCOVERED       │
                                    │                       │
                                    │ Directory found,      │
                                    │ not yet validated     │
                                    └───────────┬───────────┘
                                                │
                                                │ validate()
                                                ▼
         ┌─────────────────────────┬───────────────────────┐
         │                         │                       │
         ▼                         ▼                       │
┌───────────────────┐   ┌───────────────────┐              │
│     INVALID       │   │    VALIDATING     │              │
│                   │   │                   │              │
│ Contract failed   │   │ Parsing model.yaml│              │
│ validation        │   │                   │              │
└───────────────────┘   └─────────┬─────────┘              │
                                  │                        │
                                  │ valid                  │
                                  ▼                        │
                        ┌───────────────────┐              │
                        │     LOADING       │              │
                        │                   │              │
                        │ Weights, code     │              │
                        │ being loaded      │              │
                        └─────────┬─────────┘              │
                                  │                        │
                     ┌────────────┼───────────┐            │
                     │            │           │            │
                     ▼            ▼           │            │
          ┌───────────────┐ ┌───────────┐     │            │
          │    FAILED     │ │   READY   │     │            │
          │               │ │           │     │            │
          │ Load error    │ │ Available │     │            │
          │ (OOM, deps)   │ │ for infer │     │            │
          └───────────────┘ └─────┬─────┘     │            │
                     │            │           │            │
                     │            │ error     │            │
                     │            ▼           │            │
                     │      ┌───────────┐     │            │
                     │      │   ERROR   │     │            │
                     │      │           │     │            │
                     │      │ Runtime   │     │            │
                     │      │ failure   │     │            │
                     │      └─────┬─────┘     │            │
                     │            │           │            │
                     └────────────┼───────────┘            │
                                  │                        │
                                  │ unload()               │
                                  ▼                        │
                        ┌───────────────────┐              │
                        │    UNLOADING      │              │
                        │                   │              │
                        │ Cleaning up       │              │
                        └─────────┬─────────┘              │
                                  │                        │
                                  ▼                        │
                        ┌───────────────────┐              │
                        │    UNLOADED       │──────────────┘
                        │                   │   rescan()
                        │ Removed from      │
                        │ memory            │
                        └───────────────────┘
```

---

## Appendix B: Capability Reporter Aggregation Logic

```
Input: List of Model states from Model Registry

For each model in READY state:
    - Add to available_models list
    - Sum fps_capacity → total_fps_capacity
    - Track health status

Health aggregation:
    if all models HEALTHY → runtime_health = HEALTHY
    if any model DEGRADED and none UNHEALTHY → runtime_health = DEGRADED
    if any model UNHEALTHY → runtime_health = DEGRADED
    if no models in READY state → runtime_health = UNHEALTHY

Capacity aggregation:
    max_fps_total = sum(model.fps_capacity for model in available_models)
    max_concurrent_streams = min(10, floor(max_fps_total / 10))  # Heuristic

Output: Capability declaration JSON
```

---

## Appendix C: Glossary

| Term | Definition |
|------|------------|
| **Model Plugin** | Self-contained directory with model.yaml, weights, and inference code |
| **Model Contract** | The model.yaml file declaring model capabilities and requirements |
| **Model Executor** | Isolated context that runs inference for a single model+version |
| **Runtime Core** | The model-agnostic orchestration layer |
| **Capability Reporter** | Component that aggregates and reports runtime capabilities |
| **Model Registry** | In-memory catalog of discovered and loaded models |
| **Request Router** | Component that directs inference requests to correct executor |
| **Failure Domain** | Scope of impact when a failure occurs |

---

**End of AI Runtime Internal Architecture Design Document**

*This specification was produced by the AI Platform Engineer Agent.*

*Document Version: 1.0*
*Last Updated: January 2026*