# Ruth AI Model Contract Specification

**Version:** 1.0
**Schema Version:** 1.0.0
**Author:** AI Platform Engineer Agent
**Date:** January 2026
**Status:** PHASE 5 – Task A2 Deliverable (DESIGN ONLY)

---

## Executive Summary

This document defines the **formal, versioned contract** that every AI model must implement to be loadable, executable, and operable within the Ruth AI Runtime platform. It serves as the **only supported interface** between:

- **AI Engineers** building models
- **AI Runtime** executing models
- **Backend** (indirectly, via capability registration)

**Contract Principles:**

1. **Explicit over Implicit** – Everything a model does is declared, never inferred
2. **Strict Validation** – Non-compliant models are rejected, not patched
3. **Backward Compatibility** – Schema evolution follows strict compatibility rules
4. **Model Agnosticism** – No assumption about what models detect or how they work
5. **Failure Safety** – Contracts define error boundaries clearly

This contract is the **bedrock of platform extensibility**. Once an AI engineer understands this document, they can build any model for Ruth AI without needing runtime internals knowledge.

---

## Table of Contents

1. [Contract Overview](#1-contract-overview)
2. [Model Directory Structure](#2-model-directory-structure)
3. [model.yaml Contract Schema](#3-modelyaml-contract-schema)
4. [Python Interface Contracts](#4-python-interface-contracts)
5. [Allowed Inputs & Outputs](#5-allowed-inputs--outputs)
6. [Error Semantics](#6-error-semantics)
7. [Versioning & Compatibility](#7-versioning--compatibility)
8. [Validation & Compliance](#8-validation--compliance)
9. [Migration Guidelines](#9-migration-guidelines)
10. [Non-Goals](#10-non-goals)

---

## 1. Contract Overview

### 1.1 What Is a Model Contract?

A Model Contract is a complete, machine-readable declaration of:

- **Identity**: What the model is called and its version
- **Inputs**: What data the model accepts
- **Outputs**: What data the model produces
- **Capabilities**: What hardware the model supports
- **Behavior**: How the model executes and handles errors
- **Limits**: Resource and timeout constraints

### 1.2 Contract Obligations

| Party | Obligation |
|-------|------------|
| **Model Author** | Provide complete, accurate model.yaml and implement required interfaces |
| **Runtime** | Validate contract, enforce limits, isolate failures, route requests |
| **Backend** | Use only declared capabilities, respect abstraction boundaries |

### 1.3 Contract Guarantees

**If a model satisfies this contract, the Runtime guarantees:**

1. The model will be discovered and loaded
2. Inference requests will be routed to the model
3. Model failures will be isolated
4. Model health will be reported
5. The model can be upgraded without runtime changes

**If a model violates this contract:**

1. The model will be marked INVALID at validation time
2. The model will not receive inference requests
3. The violation reason will be logged clearly

---

## 2. Model Directory Structure

### 2.1 Required Directory Layout

```
ai/models/
└── <model_id>/                      # Model identifier (lowercase, alphanumeric, underscore)
    └── <version>/                   # Semantic version (X.Y.Z)
        ├── model.yaml               # REQUIRED: Model contract
        ├── weights/                 # REQUIRED: Model weights directory
        │   └── <weight_files>       # Model-specific weight files
        ├── inference.py             # REQUIRED: Inference entry point
        ├── preprocessing.py         # OPTIONAL: Input preprocessing
        ├── postprocessing.py        # OPTIONAL: Output postprocessing
        ├── requirements.txt         # OPTIONAL: Model-specific dependencies
        ├── config.yaml              # OPTIONAL: Model-specific configuration
        └── README.md                # OPTIONAL: Model documentation
```

### 2.2 Naming Constraints

| Element | Pattern | Example | Invalid Example |
|---------|---------|---------|-----------------|
| `model_id` | `^[a-z][a-z0-9_]{2,63}$` | `fall_detection` | `Fall-Detection`, `1_model` |
| `version` | Semantic versioning | `1.0.0`, `0.1.0-beta` | `v1`, `1.0`, `latest` |
| Directory name | Must match model.yaml values | `fall_detection/1.0.0/` | Mismatch causes INVALID |

### 2.3 Required Files

| File | Required | Purpose | Validation |
|------|----------|---------|------------|
| `model.yaml` | **Yes** | Model contract declaration | Schema validation |
| `weights/` | **Yes** | Model weights directory | Must exist (contents model-specific) |
| `inference.py` | **Yes** | Inference entry point | Must define `infer()` function |
| `preprocessing.py` | No | Input transformation | If present, must define `preprocess()` |
| `postprocessing.py` | No | Output transformation | If present, must define `postprocess()` |

### 2.4 Multiple Versions

Multiple versions of the same model MUST coexist:

```
ai/models/
└── fall_detection/
    ├── 1.0.0/
    │   ├── model.yaml
    │   └── ...
    ├── 1.1.0/
    │   ├── model.yaml
    │   └── ...
    └── 2.0.0-beta/
        ├── model.yaml
        └── ...
```

**Coexistence Rules:**
- Each version is loaded independently
- No shared state between versions
- Requests MUST specify version
- All versions report capabilities separately

---

## 3. model.yaml Contract Schema

### 3.1 Schema Overview

The `model.yaml` file is the **primary contract artifact**. It declares everything the Runtime needs to know about the model.

**Schema Version:** `1.0.0`

### 3.2 Complete Schema Definition

```yaml
# ============================================================================
# RUTH AI MODEL CONTRACT - model.yaml
# Schema Version: 1.0.0
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION 1: MODEL IDENTITY (REQUIRED)
# ----------------------------------------------------------------------------

# Unique identifier for this model
# Pattern: ^[a-z][a-z0-9_]{2,63}$
# Must match the containing directory name
model_id: "fall_detection"

# Semantic version of this model
# Must match the containing directory name
# Format: X.Y.Z or X.Y.Z-prerelease
version: "1.0.0"

# Human-readable display name
# Max length: 100 characters
display_name: "Fall Detection Model"

# Model description
# Max length: 1000 characters
description: "Detects human falls in video frames using pose estimation."

# Model author/team
author: "AI Team"

# License (optional)
license: "Proprietary"

# Contract schema version this model.yaml conforms to
contract_schema_version: "1.0.0"


# ----------------------------------------------------------------------------
# SECTION 2: INPUT SPECIFICATION (REQUIRED)
# ----------------------------------------------------------------------------

input:
  # Input type determines how the runtime sends data to the model
  # REQUIRED
  # Values: frame | batch | temporal
  #   - frame: Single image per inference call
  #   - batch: Multiple images per inference call
  #   - temporal: Sequence of images (video clip)
  type: "frame"

  # Input format
  # REQUIRED
  # Values: jpeg | png | raw_rgb | raw_bgr | raw_grayscale
  format: "jpeg"

  # Minimum supported input dimensions
  # REQUIRED
  min_width: 320
  min_height: 240

  # Maximum supported input dimensions
  # OPTIONAL - if omitted, no upper limit enforced by runtime
  max_width: 1920
  max_height: 1080

  # Number of color channels
  # REQUIRED
  # Values: 1 (grayscale) | 3 (RGB/BGR) | 4 (RGBA)
  channels: 3

  # For batch type: batch size constraints
  # REQUIRED if type == "batch"
  batch:
    min_size: 1
    max_size: 16
    recommended_size: 4

  # For temporal type: sequence constraints
  # REQUIRED if type == "temporal"
  temporal:
    min_frames: 8
    max_frames: 64
    recommended_frames: 16
    fps_requirement: 10  # Expected input FPS


# ----------------------------------------------------------------------------
# SECTION 3: OUTPUT SPECIFICATION (REQUIRED)
# ----------------------------------------------------------------------------

output:
  # Output schema version (for schema evolution tracking)
  schema_version: "1.0"

  # Output schema definition
  # REQUIRED
  # Defines the structure of the JSON output from inference
  schema:
    # Primary event classification
    # REQUIRED field in all model outputs
    event_type:
      type: "string"
      required: true
      description: "Classification result of the inference"
      # Allowed values - model declares its output vocabulary
      enum:
        - "fall_detected"
        - "no_fall"
        - "person_detected"
        - "no_person"

    # Confidence score for the classification
    # REQUIRED field in all model outputs
    confidence:
      type: "float"
      required: true
      description: "Confidence score for the event_type classification"
      min: 0.0
      max: 1.0

    # Bounding boxes for detected objects
    # OPTIONAL - depends on model capability
    bounding_boxes:
      type: "array"
      required: false
      description: "Detected object locations"
      items:
        type: "object"
        properties:
          x:
            type: "integer"
            description: "Top-left X coordinate in pixels"
          y:
            type: "integer"
            description: "Top-left Y coordinate in pixels"
          width:
            type: "integer"
            description: "Box width in pixels"
          height:
            type: "integer"
            description: "Box height in pixels"
          label:
            type: "string"
            description: "Classification label for this detection"
          confidence:
            type: "float"
            description: "Confidence for this specific detection"
            min: 0.0
            max: 1.0

    # Additional model-specific metadata
    # OPTIONAL - model may declare additional output fields
    metadata:
      type: "object"
      required: false
      description: "Model-specific additional output data"
      # Model declares allowed keys
      allowed_keys:
        - "pose_keypoints"
        - "tracking_id"
        - "scene_context"


# ----------------------------------------------------------------------------
# SECTION 4: HARDWARE COMPATIBILITY (REQUIRED)
# ----------------------------------------------------------------------------

hardware:
  # CPU support
  # REQUIRED
  supports_cpu: true

  # GPU support (NVIDIA CUDA)
  # REQUIRED
  supports_gpu: true

  # NVIDIA Jetson support
  # REQUIRED
  supports_jetson: true

  # Minimum GPU memory required (MB)
  # OPTIONAL - runtime uses for scheduling decisions
  min_gpu_memory_mb: 2048

  # Minimum CPU cores recommended
  # OPTIONAL
  min_cpu_cores: 2

  # Minimum system RAM (MB)
  # OPTIONAL
  min_ram_mb: 4096


# ----------------------------------------------------------------------------
# SECTION 5: PERFORMANCE HINTS (REQUIRED)
# ----------------------------------------------------------------------------

performance:
  # Expected inference time in milliseconds
  # REQUIRED - runtime uses for timeout calculation
  inference_time_hint_ms: 50

  # Recommended FPS this model can sustain
  # REQUIRED
  recommended_fps: 30

  # Maximum FPS this model should receive
  # OPTIONAL - runtime may throttle above this
  max_fps: 60

  # Recommended batch size for batch-type models
  # REQUIRED if input.type == "batch"
  recommended_batch_size: 4

  # Warmup iterations needed before stable performance
  # OPTIONAL - default: 1
  warmup_iterations: 3


# ----------------------------------------------------------------------------
# SECTION 6: RESOURCE LIMITS (OPTIONAL)
# ----------------------------------------------------------------------------

limits:
  # Maximum memory this model may use (MB)
  # OPTIONAL - runtime enforces if specified
  max_memory_mb: 4096

  # Custom inference timeout (ms)
  # OPTIONAL - overrides global default
  inference_timeout_ms: 5000

  # Custom preprocessing timeout (ms)
  # OPTIONAL - overrides global default
  preprocessing_timeout_ms: 1000

  # Custom postprocessing timeout (ms)
  # OPTIONAL - overrides global default
  postprocessing_timeout_ms: 1000

  # Maximum concurrent inferences
  # OPTIONAL - default: 1
  max_concurrent_inferences: 1


# ----------------------------------------------------------------------------
# SECTION 7: ENTRY POINTS (OPTIONAL)
# ----------------------------------------------------------------------------

entry_points:
  # Inference entry point file
  # DEFAULT: "inference.py"
  inference: "inference.py"

  # Preprocessing entry point file
  # DEFAULT: "preprocessing.py" (if exists)
  preprocess: "preprocessing.py"

  # Postprocessing entry point file
  # DEFAULT: "postprocessing.py" (if exists)
  postprocess: "postprocessing.py"

  # Model loading function (if custom loading needed)
  # DEFAULT: None (runtime handles loading)
  loader: null


# ----------------------------------------------------------------------------
# SECTION 8: DEPENDENCIES (OPTIONAL)
# ----------------------------------------------------------------------------

dependencies:
  # Python version requirement
  # OPTIONAL
  python_version: ">=3.9,<3.12"

  # Runtime framework
  # OPTIONAL - informational only
  framework: "pytorch"
  framework_version: ">=2.0.0"

  # Whether model has custom requirements.txt
  # OPTIONAL - runtime will install if true
  has_requirements: true


# ----------------------------------------------------------------------------
# SECTION 9: CAPABILITIES (OPTIONAL)
# ----------------------------------------------------------------------------

capabilities:
  # Model supports batched inference
  supports_batching: true

  # Model supports async inference
  supports_async: false

  # Model provides tracking IDs across frames
  provides_tracking: false

  # Model provides confidence calibration
  confidence_calibrated: true

  # Model provides bounding boxes
  provides_bounding_boxes: true

  # Model provides keypoints (pose estimation)
  provides_keypoints: false


# ----------------------------------------------------------------------------
# SECTION 10: LABELS & TAGS (OPTIONAL)
# ----------------------------------------------------------------------------

labels:
  # Category for UI grouping
  category: "safety"

  # Tags for search/filtering
  tags:
    - "fall"
    - "safety"
    - "pose"
    - "person"

  # Priority hint for scheduling
  priority: "high"


# ----------------------------------------------------------------------------
# SECTION 11: VALIDATION (OPTIONAL)
# ----------------------------------------------------------------------------

validation:
  # Enable strict output schema validation
  # DEFAULT: true
  strict_output_validation: true

  # Enable input dimension validation
  # DEFAULT: true
  validate_input_dimensions: true

  # Sample input for warmup validation
  warmup_input:
    width: 640
    height: 480
    format: "jpeg"
```

### 3.3 Field Reference Table

#### Required Fields

| Field Path | Type | Description |
|------------|------|-------------|
| `model_id` | string | Unique model identifier |
| `version` | string | Semantic version |
| `display_name` | string | Human-readable name |
| `contract_schema_version` | string | Schema version this contract follows |
| `input.type` | enum | Input data type |
| `input.format` | enum | Input data format |
| `input.min_width` | integer | Minimum input width |
| `input.min_height` | integer | Minimum input height |
| `input.channels` | integer | Number of color channels |
| `output.schema_version` | string | Output schema version |
| `output.schema.event_type` | object | Event classification schema |
| `output.schema.confidence` | object | Confidence score schema |
| `hardware.supports_cpu` | boolean | CPU compatibility |
| `hardware.supports_gpu` | boolean | GPU compatibility |
| `hardware.supports_jetson` | boolean | Jetson compatibility |
| `performance.inference_time_hint_ms` | integer | Expected inference time |
| `performance.recommended_fps` | integer | Recommended processing FPS |

#### Optional Fields with Defaults

| Field Path | Type | Default | Description |
|------------|------|---------|-------------|
| `description` | string | `""` | Model description |
| `author` | string | `"unknown"` | Model author |
| `license` | string | `"Proprietary"` | License type |
| `input.max_width` | integer | `null` | Maximum input width |
| `input.max_height` | integer | `null` | Maximum input height |
| `limits.inference_timeout_ms` | integer | `5000` | Inference timeout |
| `limits.preprocessing_timeout_ms` | integer | `1000` | Preprocessing timeout |
| `limits.postprocessing_timeout_ms` | integer | `1000` | Postprocessing timeout |
| `limits.max_concurrent_inferences` | integer | `1` | Max concurrent executions |
| `entry_points.inference` | string | `"inference.py"` | Inference entry point |
| `validation.strict_output_validation` | boolean | `true` | Strict output checking |

### 3.4 Conditional Requirements

| Condition | Required Fields |
|-----------|-----------------|
| `input.type == "batch"` | `input.batch.min_size`, `input.batch.max_size` |
| `input.type == "temporal"` | `input.temporal.min_frames`, `input.temporal.max_frames` |
| `capabilities.provides_bounding_boxes == true` | `output.schema.bounding_boxes` |

---

## 4. Python Interface Contracts

### 4.1 Interface Philosophy

Model Python interfaces follow these principles:

1. **Minimal Surface Area** – Only required functions are defined
2. **Type Safety** – All inputs and outputs have defined types
3. **Error Boundaries** – Exceptions are caught and categorized
4. **Stateless Design** – Functions should not rely on global state

### 4.2 Preprocessing Interface

**File:** `preprocessing.py` (OPTIONAL)

**Purpose:** Transform raw input into model-ready format

#### Function Signature

```python
def preprocess(
    input_data: bytes,
    input_format: str,
    config: dict
) -> PreprocessResult:
    """
    Transform raw input data into model-ready format.

    Args:
        input_data: Raw input bytes (JPEG, PNG, or raw pixels)
        input_format: Format string from model.yaml ("jpeg", "png", "raw_rgb", etc.)
        config: Read-only configuration dict from model.yaml

    Returns:
        PreprocessResult containing transformed data

    Raises:
        PreprocessingError: For recoverable preprocessing failures
        ValueError: For invalid input that cannot be processed
    """
    ...
```

#### PreprocessResult Type

```python
@dataclass
class PreprocessResult:
    """Result of preprocessing operation."""

    # Transformed data ready for inference
    # Type depends on model requirements (numpy array, torch tensor, etc.)
    data: Any

    # Original input dimensions (for output coordinate mapping)
    original_width: int
    original_height: int

    # Transformed dimensions (may differ from original)
    transformed_width: int
    transformed_height: int

    # Preprocessing metadata (optional)
    metadata: dict = field(default_factory=dict)
```

#### Behavioral Contract

| Aspect | Requirement |
|--------|-------------|
| **Input** | Raw bytes in declared format |
| **Output** | `PreprocessResult` with valid data |
| **Idempotency** | Same input → same output |
| **Side Effects** | None allowed |
| **State** | Must not modify global state |
| **Timeout** | Must complete within `limits.preprocessing_timeout_ms` |

#### Error Handling

| Exception | When to Raise | Runtime Response |
|-----------|---------------|------------------|
| `PreprocessingError` | Recoverable failure (e.g., image decode error) | Log, return error, model health DEGRADED |
| `ValueError` | Invalid input (e.g., wrong format) | Log, return error, no health impact |
| Any other exception | Unexpected failure | Log, return error, model health DEGRADED |

### 4.3 Inference Interface

**File:** `inference.py` (REQUIRED)

**Purpose:** Execute model inference on preprocessed data

#### Function Signature

```python
def infer(
    preprocessed_data: Any,
    config: dict,
    context: InferenceContext
) -> InferenceResult:
    """
    Execute model inference on preprocessed data.

    Args:
        preprocessed_data: Output from preprocess() or raw data if no preprocessing
        config: Read-only configuration dict from model.yaml
        context: Execution context with frame_id, camera_id, etc.

    Returns:
        InferenceResult containing model output

    Raises:
        InferenceError: For model execution failures
        TimeoutError: If inference exceeds timeout (runtime may inject)
    """
    ...
```

#### InferenceContext Type

```python
@dataclass
class InferenceContext:
    """Context provided by runtime to inference function."""

    # Unique identifier for this frame
    frame_id: str

    # Camera/device that produced this frame
    camera_id: str

    # Stream identifier
    stream_id: str

    # Frame timestamp (ISO 8601)
    timestamp: str

    # Model identifier (for multi-model scenarios)
    model_id: str

    # Model version
    version: str

    # Logger instance (scoped to model)
    logger: Logger

    # Metrics collector (scoped to model)
    metrics: MetricsCollector
```

#### InferenceResult Type

```python
@dataclass
class InferenceResult:
    """Result of inference operation."""

    # Primary event classification
    # REQUIRED - must match one of output.schema.event_type.enum values
    event_type: str

    # Confidence score (0.0 to 1.0)
    # REQUIRED
    confidence: float

    # Bounding boxes (optional, based on model capability)
    bounding_boxes: List[BoundingBox] = field(default_factory=list)

    # Additional metadata (optional, based on model capability)
    metadata: dict = field(default_factory=dict)

    # Inference timing (populated by model)
    inference_time_ms: int = 0
```

#### BoundingBox Type

```python
@dataclass
class BoundingBox:
    """Bounding box for a detected object."""

    x: int          # Top-left X coordinate
    y: int          # Top-left Y coordinate
    width: int      # Box width
    height: int     # Box height
    label: str      # Classification label
    confidence: float  # Detection confidence (0.0 to 1.0)
```

#### Behavioral Contract

| Aspect | Requirement |
|--------|-------------|
| **Input** | Preprocessed data or raw input if no preprocessing |
| **Output** | `InferenceResult` matching declared schema |
| **Determinism** | Encouraged but not required |
| **Side Effects** | Logging and metrics only |
| **State** | Model weights are read-only after loading |
| **Timeout** | Must complete within `limits.inference_timeout_ms` |

#### Error Handling

| Exception | When to Raise | Runtime Response |
|-----------|---------------|------------------|
| `InferenceError` | Model execution failure | Log, return error, model health DEGRADED |
| `OutOfMemoryError` | GPU/CPU memory exhaustion | Log, return error, model state → ERROR |
| `TimeoutError` | Inference exceeds timeout | Caught by runtime, model health DEGRADED |
| Any other exception | Unexpected failure | Log, return error, model health DEGRADED |

### 4.4 Postprocessing Interface

**File:** `postprocessing.py` (OPTIONAL)

**Purpose:** Transform inference output into final response format

#### Function Signature

```python
def postprocess(
    inference_result: InferenceResult,
    preprocess_result: PreprocessResult,
    config: dict
) -> PostprocessResult:
    """
    Transform inference output into final response format.

    Args:
        inference_result: Raw output from infer()
        preprocess_result: Output from preprocess() (for coordinate mapping)
        config: Read-only configuration dict from model.yaml

    Returns:
        PostprocessResult with transformed output

    Raises:
        PostprocessingError: For postprocessing failures
    """
    ...
```

#### PostprocessResult Type

```python
@dataclass
class PostprocessResult:
    """Result of postprocessing operation."""

    # Final event classification
    event_type: str

    # Final confidence score
    confidence: float

    # Transformed bounding boxes (mapped to original coordinates)
    bounding_boxes: List[BoundingBox] = field(default_factory=list)

    # Final metadata
    metadata: dict = field(default_factory=dict)
```

#### Behavioral Contract

| Aspect | Requirement |
|--------|-------------|
| **Input** | `InferenceResult` and `PreprocessResult` |
| **Output** | `PostprocessResult` matching declared schema |
| **Coordinate Mapping** | Must map bounding boxes to original image dimensions |
| **Filtering** | May filter low-confidence detections |
| **Timeout** | Must complete within `limits.postprocessing_timeout_ms` |

### 4.5 Model Loader Interface (Optional)

**Purpose:** Custom model weight loading logic

**File:** Specified in `entry_points.loader`

```python
def load_model(
    weights_path: str,
    config: dict,
    device: str  # "cpu", "cuda", "cuda:0", etc.
) -> Any:
    """
    Load model weights into memory.

    Args:
        weights_path: Absolute path to weights/ directory
        config: Read-only configuration from model.yaml
        device: Target device for model execution

    Returns:
        Loaded model object (type is model-specific)

    Raises:
        ModelLoadError: If loading fails
    """
    ...
```

**When to Implement:**
- Model requires custom deserialization
- Model uses non-standard weight format
- Model requires multi-file loading

**When NOT to Implement:**
- Standard PyTorch (.pt, .pth) or ONNX (.onnx) formats
- Runtime's default loader is sufficient

---

## 5. Allowed Inputs & Outputs

### 5.1 Input Type Definitions

#### Frame Input (`input.type: "frame"`)

Single image per inference call.

**Data Flow:**
```
Single Frame → Preprocess → Infer → Postprocess → Single Result
```

**Input Structure:**
```python
@dataclass
class FrameInput:
    frame_id: str      # Unique frame identifier
    camera_id: str     # Source camera
    stream_id: str     # Source stream
    timestamp: str     # ISO 8601 timestamp
    data: bytes        # Frame data in declared format
    width: int         # Frame width
    height: int        # Frame height
```

#### Batch Input (`input.type: "batch"`)

Multiple frames per inference call.

**Data Flow:**
```
[Frame1, Frame2, ...] → Preprocess → Infer → Postprocess → [Result1, Result2, ...]
```

**Input Structure:**
```python
@dataclass
class BatchInput:
    batch_id: str                  # Unique batch identifier
    frames: List[FrameInput]       # List of frames
    batch_size: int                # Number of frames
```

**Constraints:**
- `input.batch.min_size <= batch_size <= input.batch.max_size`
- All frames must have same dimensions
- Results must be in same order as inputs

#### Temporal Input (`input.type: "temporal"`)

Sequence of frames (video clip) per inference call.

**Data Flow:**
```
[Frame_t0, Frame_t1, ..., Frame_tn] → Preprocess → Infer → Postprocess → Single Result
```

**Input Structure:**
```python
@dataclass
class TemporalInput:
    sequence_id: str               # Unique sequence identifier
    camera_id: str                 # Source camera
    frames: List[FrameInput]       # Ordered sequence of frames
    fps: float                     # Frames per second
    duration_ms: int               # Total sequence duration
```

**Constraints:**
- `input.temporal.min_frames <= len(frames) <= input.temporal.max_frames`
- Frames must be temporally ordered
- FPS should match `input.temporal.fps_requirement`

### 5.2 Input Format Definitions

| Format | Type | Encoding | Channels | Description |
|--------|------|----------|----------|-------------|
| `jpeg` | Compressed | JPEG | 3 (RGB) | Standard JPEG-encoded image |
| `png` | Compressed | PNG | 3 or 4 | PNG-encoded image |
| `raw_rgb` | Raw | None | 3 | Raw RGB pixel array (HxWx3) |
| `raw_bgr` | Raw | None | 3 | Raw BGR pixel array (HxWx3) |
| `raw_grayscale` | Raw | None | 1 | Raw grayscale array (HxW) |

**Format Requirements:**

| Format | Input Data Type | Preprocessing Expectation |
|--------|-----------------|---------------------------|
| `jpeg` | `bytes` | Decode JPEG to array |
| `png` | `bytes` | Decode PNG to array |
| `raw_rgb` | `numpy.ndarray` | Direct use |
| `raw_bgr` | `numpy.ndarray` | Direct use or convert |
| `raw_grayscale` | `numpy.ndarray` | Direct use |

### 5.3 Output Structure

#### Required Output Fields

Every inference result MUST include:

```python
{
    "event_type": str,    # Classification from declared enum
    "confidence": float   # Value in [0.0, 1.0]
}
```

#### Optional Output Fields

Based on `capabilities` declaration:

```python
{
    # If capabilities.provides_bounding_boxes == true
    "bounding_boxes": [
        {
            "x": int,
            "y": int,
            "width": int,
            "height": int,
            "label": str,
            "confidence": float
        }
    ],

    # If declared in output.schema.metadata.allowed_keys
    "metadata": {
        "pose_keypoints": [...],
        "tracking_id": int,
        "scene_context": str
    }
}
```

### 5.4 Output Schema Validation

**Strict Validation Mode** (default, `validation.strict_output_validation: true`):

| Check | Failure Behavior |
|-------|------------------|
| `event_type` missing | Error, result rejected |
| `event_type` not in declared enum | Error, result rejected |
| `confidence` missing | Error, result rejected |
| `confidence` outside [0.0, 1.0] | Error, result rejected |
| Unknown field in output | Error, result rejected |
| `bounding_boxes` present but not declared | Error, result rejected |
| `metadata` key not in `allowed_keys` | Error, result rejected |

**Permissive Validation Mode** (`validation.strict_output_validation: false`):

| Check | Failure Behavior |
|-------|------------------|
| `event_type` missing | Error, result rejected |
| `event_type` not in declared enum | Warning, result accepted |
| `confidence` missing | Error, result rejected |
| `confidence` outside [0.0, 1.0] | Warning, clamped to range |
| Unknown field in output | Warning, field stripped |

### 5.5 Handling Partial Outputs

If a model returns incomplete output:

| Scenario | Response |
|----------|----------|
| `event_type` missing | Inference marked as ERROR, return error to caller |
| `confidence` missing | Inference marked as ERROR, return error to caller |
| `bounding_boxes` empty when expected | Valid (empty detections are acceptable) |
| `metadata` empty when declared | Valid (metadata is always optional) |

### 5.6 Unknown/Extra Fields

| Mode | Unknown Fields |
|------|----------------|
| Strict | Rejected with error |
| Permissive | Stripped from output, warning logged |

**Rationale:** Unknown fields indicate contract drift. Strict mode catches this early.

---

## 6. Error Semantics

### 6.1 Error Classification Taxonomy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ERROR TAXONOMY                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  CATEGORY 1: MODEL ERRORS                                                    │
│  ─────────────────────────                                                   │
│  Scope: Contained within model execution                                     │
│  Owner: Model code                                                           │
│  Examples:                                                                   │
│    - PreprocessingError                                                      │
│    - InferenceError                                                          │
│    - PostprocessingError                                                     │
│    - SchemaValidationError                                                   │
│                                                                              │
│  CATEGORY 2: RUNTIME ERRORS                                                  │
│  ──────────────────────────                                                  │
│  Scope: Runtime-level issues                                                 │
│  Owner: Runtime code                                                         │
│  Examples:                                                                   │
│    - ModelNotFoundError                                                      │
│    - ModelNotReadyError                                                      │
│    - VersionNotFoundError                                                    │
│    - TimeoutError (enforced by runtime)                                      │
│    - ResourceExhaustedError                                                  │
│                                                                              │
│  CATEGORY 3: CONTRACT ERRORS                                                 │
│  ──────────────────────────                                                  │
│  Scope: Contract validation failures                                         │
│  Owner: Validation layer                                                     │
│  Examples:                                                                   │
│    - ContractValidationError                                                 │
│    - SchemaMismatchError                                                     │
│    - MissingRequiredFieldError                                               │
│    - InvalidEntryPointError                                                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Model Error Definitions

#### PreprocessingError

```python
class PreprocessingError(Exception):
    """Raised when preprocessing fails."""

    def __init__(
        self,
        message: str,
        error_code: str,
        recoverable: bool = True,
        details: dict = None
    ):
        self.message = message
        self.error_code = error_code
        self.recoverable = recoverable
        self.details = details or {}
```

**Allowed Error Codes:**

| Code | Description | Recoverable |
|------|-------------|-------------|
| `DECODE_FAILED` | Image decode failure | Yes |
| `INVALID_FORMAT` | Unexpected input format | Yes |
| `INVALID_DIMENSIONS` | Image dimensions out of range | Yes |
| `MEMORY_ERROR` | Preprocessing OOM | No |

#### InferenceError

```python
class InferenceError(Exception):
    """Raised when inference fails."""

    def __init__(
        self,
        message: str,
        error_code: str,
        recoverable: bool = True,
        details: dict = None
    ):
        self.message = message
        self.error_code = error_code
        self.recoverable = recoverable
        self.details = details or {}
```

**Allowed Error Codes:**

| Code | Description | Recoverable |
|------|-------------|-------------|
| `MODEL_EXECUTION_FAILED` | Forward pass failure | Yes |
| `INVALID_INPUT_SHAPE` | Input shape mismatch | Yes |
| `GPU_ERROR` | CUDA/GPU failure | Maybe |
| `OUT_OF_MEMORY` | GPU/CPU OOM | No |
| `MODEL_CORRUPTED` | Weight corruption detected | No |

#### PostprocessingError

```python
class PostprocessingError(Exception):
    """Raised when postprocessing fails."""

    def __init__(
        self,
        message: str,
        error_code: str,
        recoverable: bool = True,
        details: dict = None
    ):
        self.message = message
        self.error_code = error_code
        self.recoverable = recoverable
        self.details = details or {}
```

**Allowed Error Codes:**

| Code | Description | Recoverable |
|------|-------------|-------------|
| `OUTPUT_VALIDATION_FAILED` | Output doesn't match schema | Yes |
| `COORDINATE_MAPPING_FAILED` | Bounding box transformation error | Yes |
| `CONFIDENCE_INVALID` | Confidence value out of range | Yes |

### 6.3 Error Surfacing Protocol

**Model → Runtime Communication:**

```python
# Model raises typed exception
raise InferenceError(
    message="CUDA out of memory during forward pass",
    error_code="OUT_OF_MEMORY",
    recoverable=False,
    details={
        "gpu_memory_used_mb": 15800,
        "gpu_memory_total_mb": 16384,
        "batch_size": 8
    }
)
```

**Runtime → Backend Communication:**

```python
# Runtime translates to standardized error response
{
    "error": True,
    "error_code": "INFERENCE_FAILED",
    "error_source": "model",
    "error_details": {
        "model_error_code": "OUT_OF_MEMORY",
        "model_id": "fall_detection",
        "version": "1.0.0",
        "message": "CUDA out of memory during forward pass",
        "recoverable": False
    },
    "frame_id": "abc123",
    "camera_id": "camera_001"
}
```

### 6.4 Retryable vs Terminal Errors

| Error Code | Retryable | Action |
|------------|-----------|--------|
| `DECODE_FAILED` | Yes | Retry with next frame |
| `INVALID_FORMAT` | No | Log, skip frame |
| `MODEL_EXECUTION_FAILED` | Yes | Retry once |
| `GPU_ERROR` | Maybe | Check GPU health, may retry |
| `OUT_OF_MEMORY` | No | Mark model ERROR, notify |
| `MODEL_CORRUPTED` | No | Mark model INVALID, notify |
| `TIMEOUT` | Yes | Retry once with backoff |

### 6.5 Error Message Structure

**Required Error Message Fields:**

```json
{
    "error_code": "INFERENCE_FAILED",
    "error_source": "model",
    "message": "Human-readable error description",
    "timestamp": "2026-01-14T10:30:00.000Z",
    "model_id": "fall_detection",
    "version": "1.0.0",
    "frame_id": "abc123",
    "recoverable": false,
    "details": {}
}
```

**Prohibited in Error Messages:**

- Stack traces (log separately, don't return to caller)
- Internal memory addresses
- File paths from host system
- Model weight details

---

## 7. Versioning & Compatibility

### 7.1 Schema Version Strategy

**Schema Version Format:** `MAJOR.MINOR.PATCH`

| Component | When to Increment | Compatibility |
|-----------|-------------------|---------------|
| MAJOR | Breaking changes | Not backward compatible |
| MINOR | Additive changes | Backward compatible |
| PATCH | Bug fixes, clarifications | Fully compatible |

**Current Schema Version:** `1.0.0`

### 7.2 Backward Compatible Changes

Changes that **DO NOT** require schema version bump:

| Change | Example | Runtime Handling |
|--------|---------|------------------|
| Add optional field | Add `labels.priority` | Default value used if missing |
| Add new enum value | Add `"warning"` to event_type | Runtime accepts new values |
| Expand numeric range | `max_fps: 100` → `max_fps: 200` | No impact |
| Add new capability flag | Add `provides_segmentation` | Default to `false` |
| Documentation clarification | Improve field description | No runtime impact |

### 7.3 Breaking Changes

Changes that **REQUIRE** MAJOR schema version bump:

| Change | Example | Migration Required |
|--------|---------|-------------------|
| Remove required field | Remove `model_id` | Models must update |
| Rename field | `model_id` → `id` | Models must update |
| Change field type | `version: string` → `version: object` | Models must update |
| Remove enum value | Remove `"no_fall"` from event_type | Models must update |
| Change validation rules | Make optional field required | Models must update |

### 7.4 Runtime Validation of Older Models

**Scenario:** Runtime supports schema version `1.1.0`, model declares `1.0.0`

**Validation Rules:**

1. **Check schema compatibility:** `model.contract_schema_version` vs runtime supported versions
2. **If compatible:** Apply default values for new fields
3. **If incompatible:** Reject with clear error message

**Compatibility Matrix:**

| Model Schema | Runtime Schema | Compatible | Notes |
|--------------|----------------|------------|-------|
| 1.0.0 | 1.0.0 | Yes | Exact match |
| 1.0.0 | 1.1.0 | Yes | Runtime applies defaults |
| 1.0.0 | 1.2.0 | Yes | Runtime applies defaults |
| 1.0.0 | 2.0.0 | No | Major version mismatch |
| 1.1.0 | 1.0.0 | No | Model newer than runtime |

### 7.5 Deprecation Rules

**Deprecation Timeline:**

```
Announcement ──────────────────────────────────────────> Removal
     │                                                      │
     │   6 months minimum                                   │
     │   ─────────────────────────────────────────────────  │
     │                                                      │
     ├── Deprecated field still works                       │
     ├── Runtime logs deprecation warning                   │
     ├── Documentation marked deprecated                    │
     └── Migration guide available                          │
```

**Deprecation Announcement Format:**

```yaml
# In model.yaml documentation or changelog
deprecated:
  fields:
    - path: "hardware.min_gpu_memory_mb"
      deprecated_in: "1.2.0"
      removed_in: "2.0.0"
      replacement: "limits.min_gpu_memory_mb"
      migration: "Move value to limits.min_gpu_memory_mb"
```

### 7.6 Model Version Evolution

**Model authors** manage their own versioning:

| Model Version Change | When |
|---------------------|------|
| PATCH (1.0.0 → 1.0.1) | Bug fixes, no output changes |
| MINOR (1.0.0 → 1.1.0) | New capabilities, backward compatible output |
| MAJOR (1.0.0 → 2.0.0) | Output schema changes, breaking changes |

**Coexistence Requirement:**
- Multiple model versions MUST coexist
- Runtime loads all valid versions
- Backend requests specify exact version

---

## 8. Validation & Compliance

### 8.1 Contract Validation Stages

```
┌─────────────────────────────────────────────────────────────────────┐
│                    VALIDATION PIPELINE                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  STAGE 1: STRUCTURE VALIDATION                                       │
│  ─────────────────────────────                                       │
│  ✓ model.yaml exists                                                 │
│  ✓ model.yaml is valid YAML                                          │
│  ✓ Required directories exist (weights/)                             │
│  ✓ Required files exist (inference.py)                               │
│                                                                      │
│  STAGE 2: SCHEMA VALIDATION                                          │
│  ──────────────────────────                                          │
│  ✓ All required fields present                                       │
│  ✓ Field types are correct                                           │
│  ✓ Field values within constraints                                   │
│  ✓ Conditional requirements satisfied                                │
│                                                                      │
│  STAGE 3: CONSISTENCY VALIDATION                                     │
│  ───────────────────────────────                                     │
│  ✓ model_id matches directory name                                   │
│  ✓ version matches directory name                                    │
│  ✓ Entry point files exist                                           │
│  ✓ Output schema is self-consistent                                  │
│                                                                      │
│  STAGE 4: CAPABILITY VALIDATION                                      │
│  ───────────────────────────────                                     │
│  ✓ Declared hardware matches runtime                                 │
│  ✓ Resource requirements are satisfiable                             │
│  ✓ Dependencies are available (if declared)                          │
│                                                                      │
│  STAGE 5: RUNTIME VALIDATION                                         │
│  ──────────────────────────                                          │
│  ✓ Model loads without error                                         │
│  ✓ Warmup inference succeeds                                         │
│  ✓ Output matches declared schema                                    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 8.2 Validation Error Messages

**Structure Errors:**

```
CONTRACT_VALIDATION_FAILED: model.yaml not found
  Location: ai/models/fall_detection/1.0.0/
  Expected: model.yaml
  Action: Create model.yaml with required fields
```

**Schema Errors:**

```
CONTRACT_VALIDATION_FAILED: Required field missing
  Field: input.type
  Location: model.yaml line 15
  Action: Add 'type' field under 'input' section
  Valid values: frame, batch, temporal
```

**Consistency Errors:**

```
CONTRACT_VALIDATION_FAILED: Version mismatch
  Declared: 1.0.0
  Directory: 1.1.0
  Action: Ensure version in model.yaml matches directory name
```

### 8.3 Compliance Checklist

**For Model Authors:**

- [ ] `model.yaml` exists and is valid YAML
- [ ] All required fields are present
- [ ] `model_id` matches directory name
- [ ] `version` matches directory name
- [ ] `weights/` directory exists with model weights
- [ ] `inference.py` exists and defines `infer()` function
- [ ] If `preprocessing.py` exists, it defines `preprocess()` function
- [ ] If `postprocessing.py` exists, it defines `postprocess()` function
- [ ] Output schema matches actual inference output
- [ ] Hardware compatibility flags are accurate
- [ ] Performance hints reflect actual performance

---

## 9. Migration Guidelines

### 9.1 Migrating from Schema 1.0.0 to Future Versions

**When schema version 1.1.0 is released:**

1. **Check Release Notes:** Review what fields were added/changed
2. **Update model.yaml:** Add new optional fields if needed
3. **Update contract_schema_version:** Declare new version
4. **Test:** Validate model with new runtime

### 9.2 Adding a New Model

**Step-by-Step:**

1. **Create Directory Structure:**
   ```
   ai/models/<model_id>/<version>/
   ```

2. **Create model.yaml:**
   - Copy template from this document
   - Fill in all required fields
   - Declare accurate capabilities

3. **Implement inference.py:**
   - Define `infer()` function with correct signature
   - Return `InferenceResult` matching declared schema

4. **Optionally Implement preprocessing.py:**
   - If model needs custom input transformation

5. **Optionally Implement postprocessing.py:**
   - If model needs custom output transformation

6. **Add weights/ Directory:**
   - Place model weights in standardized format

7. **Test Locally:**
   - Validate model.yaml with schema validator
   - Run test inference

8. **Deploy:**
   - Copy model directory to runtime's model path
   - Restart runtime or trigger rescan

### 9.3 Upgrading an Existing Model

**Step-by-Step:**

1. **Create New Version Directory:**
   ```
   ai/models/fall_detection/1.1.0/   # New version
   ai/models/fall_detection/1.0.0/   # Old version remains
   ```

2. **Update model.yaml:**
   - Increment version number
   - Update any changed capabilities

3. **Deploy New Version:**
   - Both versions coexist
   - Backend can request either version

4. **Deprecate Old Version:**
   - After validation, stop sending requests to old version
   - Eventually remove old version directory

### 9.4 Common Migration Mistakes

| Mistake | Problem | Solution |
|---------|---------|----------|
| Deleting old version before new is validated | Downtime | Keep old version until new is proven |
| Changing output schema without version bump | Contract violation | Always bump version for schema changes |
| Forgetting to update `contract_schema_version` | Validation may fail | Always declare schema version |
| Reusing model_id with different semantics | Confusion | Use different model_id for different purposes |

---

## 10. Non-Goals

This contract specification explicitly does NOT address:

| Non-Goal | Rationale |
|----------|-----------|
| Model training procedures | Training is outside runtime scope |
| Model architecture requirements | Models can use any architecture |
| Specific ML framework APIs | Framework-agnostic design |
| Model optimization techniques | Implementation detail |
| Model testing frameworks | Testing is model author's responsibility |
| Model distribution/packaging | Deployment is Phase 3 scope |
| Model signing/verification | Security is separate concern |
| Model performance benchmarking | Implementation detail |
| Fall detection specifics | Fall detection is just one model |

---

## Appendix A: JSON Schema for model.yaml

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://ruth-ai.com/schemas/model-contract/1.0.0",
  "title": "Ruth AI Model Contract",
  "description": "Schema for model.yaml contract file",
  "type": "object",
  "required": [
    "model_id",
    "version",
    "display_name",
    "contract_schema_version",
    "input",
    "output",
    "hardware",
    "performance"
  ],
  "properties": {
    "model_id": {
      "type": "string",
      "pattern": "^[a-z][a-z0-9_]{2,63}$",
      "description": "Unique model identifier"
    },
    "version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+(-[a-zA-Z0-9]+)?$",
      "description": "Semantic version"
    },
    "display_name": {
      "type": "string",
      "maxLength": 100,
      "description": "Human-readable name"
    },
    "description": {
      "type": "string",
      "maxLength": 1000,
      "description": "Model description"
    },
    "author": {
      "type": "string",
      "description": "Model author"
    },
    "license": {
      "type": "string",
      "description": "License type"
    },
    "contract_schema_version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+$",
      "description": "Contract schema version"
    },
    "input": {
      "type": "object",
      "required": ["type", "format", "min_width", "min_height", "channels"],
      "properties": {
        "type": {
          "type": "string",
          "enum": ["frame", "batch", "temporal"]
        },
        "format": {
          "type": "string",
          "enum": ["jpeg", "png", "raw_rgb", "raw_bgr", "raw_grayscale"]
        },
        "min_width": {
          "type": "integer",
          "minimum": 1
        },
        "min_height": {
          "type": "integer",
          "minimum": 1
        },
        "max_width": {
          "type": "integer",
          "minimum": 1
        },
        "max_height": {
          "type": "integer",
          "minimum": 1
        },
        "channels": {
          "type": "integer",
          "enum": [1, 3, 4]
        },
        "batch": {
          "type": "object",
          "properties": {
            "min_size": { "type": "integer", "minimum": 1 },
            "max_size": { "type": "integer", "minimum": 1 },
            "recommended_size": { "type": "integer", "minimum": 1 }
          }
        },
        "temporal": {
          "type": "object",
          "properties": {
            "min_frames": { "type": "integer", "minimum": 1 },
            "max_frames": { "type": "integer", "minimum": 1 },
            "recommended_frames": { "type": "integer", "minimum": 1 },
            "fps_requirement": { "type": "number", "minimum": 0 }
          }
        }
      }
    },
    "output": {
      "type": "object",
      "required": ["schema_version", "schema"],
      "properties": {
        "schema_version": {
          "type": "string"
        },
        "schema": {
          "type": "object",
          "required": ["event_type", "confidence"],
          "properties": {
            "event_type": {
              "type": "object",
              "required": ["type", "required", "enum"],
              "properties": {
                "type": { "const": "string" },
                "required": { "const": true },
                "description": { "type": "string" },
                "enum": {
                  "type": "array",
                  "items": { "type": "string" },
                  "minItems": 1
                }
              }
            },
            "confidence": {
              "type": "object",
              "required": ["type", "required", "min", "max"],
              "properties": {
                "type": { "const": "float" },
                "required": { "const": true },
                "min": { "const": 0.0 },
                "max": { "const": 1.0 }
              }
            },
            "bounding_boxes": {
              "type": "object",
              "properties": {
                "type": { "const": "array" },
                "required": { "type": "boolean" },
                "items": { "type": "object" }
              }
            },
            "metadata": {
              "type": "object",
              "properties": {
                "type": { "const": "object" },
                "required": { "type": "boolean" },
                "allowed_keys": {
                  "type": "array",
                  "items": { "type": "string" }
                }
              }
            }
          }
        }
      }
    },
    "hardware": {
      "type": "object",
      "required": ["supports_cpu", "supports_gpu", "supports_jetson"],
      "properties": {
        "supports_cpu": { "type": "boolean" },
        "supports_gpu": { "type": "boolean" },
        "supports_jetson": { "type": "boolean" },
        "min_gpu_memory_mb": { "type": "integer", "minimum": 0 },
        "min_cpu_cores": { "type": "integer", "minimum": 1 },
        "min_ram_mb": { "type": "integer", "minimum": 0 }
      }
    },
    "performance": {
      "type": "object",
      "required": ["inference_time_hint_ms", "recommended_fps"],
      "properties": {
        "inference_time_hint_ms": { "type": "integer", "minimum": 1 },
        "recommended_fps": { "type": "integer", "minimum": 1 },
        "max_fps": { "type": "integer", "minimum": 1 },
        "recommended_batch_size": { "type": "integer", "minimum": 1 },
        "warmup_iterations": { "type": "integer", "minimum": 0 }
      }
    },
    "limits": {
      "type": "object",
      "properties": {
        "max_memory_mb": { "type": "integer", "minimum": 0 },
        "inference_timeout_ms": { "type": "integer", "minimum": 100 },
        "preprocessing_timeout_ms": { "type": "integer", "minimum": 100 },
        "postprocessing_timeout_ms": { "type": "integer", "minimum": 100 },
        "max_concurrent_inferences": { "type": "integer", "minimum": 1 }
      }
    },
    "entry_points": {
      "type": "object",
      "properties": {
        "inference": { "type": "string" },
        "preprocess": { "type": "string" },
        "postprocess": { "type": "string" },
        "loader": { "type": ["string", "null"] }
      }
    },
    "dependencies": {
      "type": "object",
      "properties": {
        "python_version": { "type": "string" },
        "framework": { "type": "string" },
        "framework_version": { "type": "string" },
        "has_requirements": { "type": "boolean" }
      }
    },
    "capabilities": {
      "type": "object",
      "properties": {
        "supports_batching": { "type": "boolean" },
        "supports_async": { "type": "boolean" },
        "provides_tracking": { "type": "boolean" },
        "confidence_calibrated": { "type": "boolean" },
        "provides_bounding_boxes": { "type": "boolean" },
        "provides_keypoints": { "type": "boolean" }
      }
    },
    "labels": {
      "type": "object",
      "properties": {
        "category": { "type": "string" },
        "tags": {
          "type": "array",
          "items": { "type": "string" }
        },
        "priority": {
          "type": "string",
          "enum": ["low", "normal", "high", "critical"]
        }
      }
    },
    "validation": {
      "type": "object",
      "properties": {
        "strict_output_validation": { "type": "boolean" },
        "validate_input_dimensions": { "type": "boolean" },
        "warmup_input": {
          "type": "object",
          "properties": {
            "width": { "type": "integer" },
            "height": { "type": "integer" },
            "format": { "type": "string" }
          }
        }
      }
    }
  },
  "allOf": [
    {
      "if": {
        "properties": {
          "input": {
            "properties": {
              "type": { "const": "batch" }
            }
          }
        }
      },
      "then": {
        "properties": {
          "input": {
            "required": ["batch"]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "input": {
            "properties": {
              "type": { "const": "temporal" }
            }
          }
        }
      },
      "then": {
        "properties": {
          "input": {
            "required": ["temporal"]
          }
        }
      }
    }
  ]
}
```

---

## Appendix B: Example model.yaml Files

### B.1 Minimal Valid model.yaml

```yaml
model_id: "simple_detector"
version: "1.0.0"
display_name: "Simple Detector"
contract_schema_version: "1.0.0"

input:
  type: "frame"
  format: "jpeg"
  min_width: 320
  min_height: 240
  channels: 3

output:
  schema_version: "1.0"
  schema:
    event_type:
      type: "string"
      required: true
      enum: ["detected", "not_detected"]
    confidence:
      type: "float"
      required: true
      min: 0.0
      max: 1.0

hardware:
  supports_cpu: true
  supports_gpu: true
  supports_jetson: true

performance:
  inference_time_hint_ms: 100
  recommended_fps: 10
```

### B.2 Full-Featured model.yaml

See Section 3.2 for complete example with all fields.

---

## Appendix C: Glossary

| Term | Definition |
|------|------------|
| **Model Contract** | The complete declaration in model.yaml |
| **Contract Schema** | The formal structure definition for model.yaml |
| **Schema Version** | Version of the contract schema specification |
| **Model Version** | Version of a specific model implementation |
| **Entry Point** | Python file/function that runtime calls |
| **Capability** | Declared feature or property of a model |
| **Validation** | Process of checking contract compliance |
| **Strict Mode** | Validation mode that rejects unknown fields |
| **Permissive Mode** | Validation mode that warns but allows unknown fields |

---

**End of AI Model Contract Specification**

*This specification was produced by the AI Platform Engineer Agent.*

*Document Version: 1.0*
*Schema Version: 1.0.0*
*Last Updated: January 2026*