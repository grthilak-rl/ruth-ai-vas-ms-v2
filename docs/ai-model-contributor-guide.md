# AI Model Contributor Guide

**Version:** 1.0.0
**Last Updated:** 2026-01-14
**Audience:** AI/ML Engineers adding models to Ruth AI

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Mental Model](#2-mental-model)
3. [Prerequisites](#3-prerequisites)
4. [Step-by-Step: Adding a New Model](#4-step-by-step-adding-a-new-model)
5. [Step-by-Step: Adding a New Version](#5-step-by-step-adding-a-new-version)
6. [Validation Checklist](#6-validation-checklist)
7. [Common Mistakes](#7-common-mistakes)
8. [Debugging Guide](#8-debugging-guide)
9. [Validation Scenarios](#9-validation-scenarios)
10. [Best Practices](#10-best-practices)
11. [What You Should NEVER Do](#11-what-you-should-never-do)
12. [FAQ](#12-faq)

---

## 1. Introduction

### What is Ruth AI?

Ruth AI is an intelligent video analytics platform that processes camera feeds to detect safety-related events. From your perspective as a model contributor, Ruth AI is a **multi-model runtime** that:

- Loads AI models as plugins
- Routes video frames to the appropriate models
- Collects inference results
- Reports model health to the backend

### What the Platform Does vs. What You Do

| Platform Responsibility | Your Responsibility |
|------------------------|---------------------|
| Discovers models automatically | Create model directory |
| Validates model contracts | Write valid `model.yaml` |
| Loads and executes models | Implement `inference.py` |
| Manages concurrency | Declare resource limits |
| Handles failures gracefully | Return valid output format |
| Reports health status | Handle errors without crashing |

### Model Lifecycle

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  DISCOVERED │────▶│  VALIDATED  │────▶│   LOADING   │────▶│    READY    │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │                   │
       ▼                   ▼                   ▼                   ▼
   [Scanned]          [Contract OK]      [Code Loaded]      [Serving]
                                                                   │
                                                                   ▼
                                                            ┌─────────────┐
                                                            │  UNHEALTHY  │
                                                            └─────────────┘
                                                                   │
                                                                   ▼
                                                            ┌─────────────┐
                                                            │  DISABLED   │
                                                            └─────────────┘
```

1. **DISCOVERED** - Runtime found your model directory
2. **VALIDATED** - `model.yaml` passed contract validation
3. **LOADING** - Importing Python code and loading weights
4. **READY** - Model is serving inference requests
5. **UNHEALTHY** - Model is failing repeatedly (automatic)
6. **DISABLED** - Model has been disabled by circuit breaker

---

## 2. Mental Model

Understanding these principles will prevent 90% of integration errors.

### Models Are Plugins, Not Services

Your model is a **plugin** that the runtime loads. You do not:
- Start a server
- Listen on a port
- Manage your own lifecycle
- Handle HTTP requests

You simply provide:
- A contract (`model.yaml`)
- An inference function (`inference.py`)
- Optional pre/post processing

The runtime handles everything else.

### `model.yaml` Is the Contract

The `model.yaml` file is **the source of truth**. The runtime:
- Reads your contract to understand capabilities
- Validates your code against the contract
- Uses contract values for resource allocation
- Never infers behavior from code

**If it's not in `model.yaml`, the platform doesn't know about it.**

### Directory Structure = Identity

Your model's identity comes from its directory path:

```
ai/models/{model_id}/{version}/
```

- `model_id` must match directory name
- `version` must match directory name
- Moving or renaming directories changes identity

### Runtime Is Model-Agnostic

The runtime treats all models identically. There is no special code for:
- Fall detection
- Helmet detection
- Any other specific model

If your model follows the contract, it will work. If it doesn't, it won't.

### Versions Are Immutable

Once a version is deployed:
- **Never modify it in place**
- Create a new version instead
- Old versions can be rolled back to automatically

---

## 3. Prerequisites

### Required Skills

| Skill | Level | Notes |
|-------|-------|-------|
| Python 3.9+ | Intermediate | Core implementation language |
| YAML | Basic | For `model.yaml` |
| NumPy | Basic | Frame handling |
| Your ML framework | Proficient | PyTorch, TensorFlow, etc. |

### Required Local Tools

```bash
# Minimum requirements
python3 --version  # 3.9 or higher
pip --version

# Recommended
docker --version   # For container testing
```

### Runtime Environment Assumptions

Your model runs inside the **AI Runtime container**, which provides:

| Dependency | Guaranteed |
|------------|------------|
| Python 3.9+ | Yes |
| NumPy | Yes |
| OpenCV | Yes |
| PyTorch | Yes (GPU images) |
| TensorFlow | Contact platform team |
| CUDA | GPU images only |

**Do not assume GPU availability.** Your model must declare CPU support if it works without GPU.

---

## 4. Step-by-Step: Adding a New Model

### 4.1 Choose `model_id` and Version

**Naming Rules:**

| Rule | Valid | Invalid |
|------|-------|---------|
| Lowercase only | `helmet_detection` | `Helmet_Detection` |
| Underscores allowed | `fall_detection` | `fall-detection` |
| No hyphens | `ppe_detector` | `ppe-detector` |
| No spaces | `smoke_detection` | `smoke detection` |
| Alphanumeric + underscore | `model_v2` | `model@v2` |

**Version Format:**

Use semantic versioning: `MAJOR.MINOR.PATCH`

| Version | When to Use |
|---------|-------------|
| `1.0.0` | First production release |
| `1.0.1` | Bug fixes only |
| `1.1.0` | New features, backward compatible |
| `2.0.0` | Breaking changes |

### 4.2 Create Directory Structure

```bash
# From repository root
mkdir -p ai/models/your_model/1.0.0
cd ai/models/your_model/1.0.0

# Create required files
touch model.yaml
touch inference.py

# Create optional directories
mkdir -p weights
```

**Final structure:**

```
ai/models/your_model/
└── 1.0.0/
    ├── model.yaml          # REQUIRED - Contract
    ├── inference.py        # REQUIRED - Main entry point
    ├── preprocess.py       # Optional - Input processing
    ├── postprocess.py      # Optional - Output processing
    ├── loader.py           # Optional - Custom weight loading
    ├── weights/            # Optional - Model weights
    │   └── model.pt
    └── requirements.txt    # Optional - Extra dependencies
```

### 4.3 Write `model.yaml`

This is the most important file. Copy this template and modify:

```yaml
# Contract schema version (required - do not change)
contract_schema_version: "1.0.0"

# Model identity (required - must match directory)
model_id: "your_model"
version: "1.0.0"
display_name: "Your Model Display Name"
description: "What this model detects"
author: "Your Team"

# Input specification (required)
input:
  type: "frame"              # Options: frame, batch, temporal
  format: "raw_bgr"          # OpenCV default format
  min_width: 320
  min_height: 240
  max_width: 4096
  max_height: 4096
  channels: 3

# Output specification (required)
output:
  schema_version: "1.0"
  schema:
    event_type:
      type: "string"
      enum:
        - "detected"
        - "not_detected"
    confidence:
      type: "number"
      min: 0.0
      max: 1.0
    # Add your output fields here

# Hardware compatibility (required)
hardware:
  supports_cpu: true         # Can it run without GPU?
  supports_gpu: true         # Does it benefit from GPU?
  supports_jetson: false     # Jetson Nano/Xavier support?
  min_ram_mb: 2048
  min_gpu_memory_mb: 512     # Only if supports_gpu: true

# Performance hints (required)
performance:
  inference_time_hint_ms: 100  # Expected inference time
  recommended_fps: 10          # Recommended frame rate
  max_fps: 30                  # Maximum sustainable FPS
  recommended_batch_size: 1
  warmup_iterations: 2         # Warmup runs before ready

# Resource limits (recommended)
limits:
  max_memory_mb: 4096
  inference_timeout_ms: 5000   # Kill inference after this
  preprocessing_timeout_ms: 1000
  postprocessing_timeout_ms: 1000
  max_concurrent_inferences: 2

# Capabilities (optional)
capabilities:
  supports_batching: false
  supports_async: false
  provides_bounding_boxes: true
  provides_keypoints: false

# Entry points (optional - defaults shown)
entry_points:
  inference: "inference.py"
  preprocess: "preprocess.py"    # Only if file exists
  postprocess: "postprocess.py"  # Only if file exists
  loader: "loader.py"            # Only if file exists
```

**Key Fields Explained:**

| Field | Purpose | Impact if Wrong |
|-------|---------|-----------------|
| `model_id` | Identity | Model not discovered |
| `version` | Version identity | Model not discovered |
| `input.type` | Frame handling | Incorrect input format |
| `hardware.supports_cpu` | Deployment options | Won't run on CPU-only hosts |
| `limits.inference_timeout_ms` | Timeout protection | Model killed mid-inference |
| `limits.max_concurrent_inferences` | Concurrency | Requests rejected |

### 4.4 Implement `inference.py` (Required)

Your inference module must expose an `infer()` function:

```python
"""
Your Model Inference

Brief description of what this model detects.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def infer(frame: Any, model: Any = None, **kwargs: Any) -> Dict[str, Any]:
    """
    Run inference on a single frame.

    Args:
        frame: Input frame as numpy array (H, W, C) in BGR format
        model: Loaded model instance (if using loader.py)
        **kwargs: Additional runtime arguments

    Returns:
        Dictionary matching output schema in model.yaml
    """
    try:
        # Your inference logic here
        # ...

        return {
            "event_type": "detected",  # or "not_detected"
            "confidence": 0.95,
            # Include all fields declared in model.yaml output schema
        }

    except Exception as e:
        logger.error(f"Inference failed: {e}")
        # Return safe default on error
        return {
            "event_type": "not_detected",
            "confidence": 0.0,
            "error": str(e),
        }
```

**Critical Rules:**

1. Function must be named `infer`
2. Must accept `frame` as first positional argument
3. Must accept `**kwargs` for forward compatibility
4. Must return a `dict`
5. Return dict must match `output.schema` in `model.yaml`
6. Never raise unhandled exceptions - catch and return error

### 4.5 Optional: `preprocess.py`

If your model needs input preprocessing:

```python
"""Preprocessing for Your Model"""

import numpy as np
from typing import Any


def preprocess(raw_input: Any, **kwargs: Any) -> Any:
    """
    Preprocess raw frame before inference.

    Args:
        raw_input: Raw frame from runtime
        **kwargs: Additional arguments

    Returns:
        Processed input for infer()
    """
    # Example: resize and normalize
    import cv2

    frame = cv2.resize(raw_input, (640, 480))
    frame = frame.astype(np.float32) / 255.0

    return frame
```

### 4.6 Optional: `postprocess.py`

If you need to transform inference output:

```python
"""Postprocessing for Your Model"""

from typing import Any, Dict


def postprocess(raw_output: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """
    Postprocess inference output.

    Args:
        raw_output: Raw output from infer()
        **kwargs: Additional arguments

    Returns:
        Final output dict
    """
    # Example: filter low confidence detections
    if raw_output.get("confidence", 0) < 0.5:
        raw_output["event_type"] = "not_detected"

    return raw_output
```

### 4.7 Optional: `loader.py`

For models with weights that need custom loading:

```python
"""Custom Loader for Your Model"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load(weights_path: Path) -> Any:
    """
    Load model weights.

    Args:
        weights_path: Path to weights/ directory

    Returns:
        Loaded model instance (passed to infer() as 'model' arg)
    """
    import torch

    weights_file = weights_path / "model.pt"

    if not weights_file.exists():
        raise FileNotFoundError(f"Weights not found: {weights_file}")

    logger.info(f"Loading weights from {weights_file}")

    model = torch.load(weights_file, map_location="cpu")
    model.eval()

    return model
```

### 4.8 Add Weights

Place your model weights in the `weights/` directory:

```
ai/models/your_model/1.0.0/weights/
├── model.pt           # PyTorch weights
├── config.json        # Model config (if needed)
└── vocab.txt          # Tokenizer vocab (if needed)
```

**Do not commit large weights to git.** Use:
- Git LFS
- Cloud storage with download script
- Container build-time download

### 4.9 Trigger Discovery

After adding your model:

```bash
# Option 1: Restart the AI Runtime container
docker restart ruth-ai-runtime

# Option 2: If runtime supports hot reload (future)
# curl -X POST http://localhost:8080/admin/rescan
```

The runtime will:
1. Scan `ai/models/` directory
2. Find your new model
3. Validate `model.yaml`
4. Load and warmup the model
5. Mark it READY (or INVALID/FAILED)

---

## 5. Step-by-Step: Adding a New Version

### Why Versions Must Never Be Modified

| If You... | What Happens |
|-----------|--------------|
| Edit an existing version | Running cameras may get inconsistent results |
| Delete an existing version | Cameras pinned to that version will fail |
| Rename a version | Same as delete + add, breaks references |

**Rule: Treat deployed versions as read-only.**

### Creating a New Version

```bash
# Copy the previous version as a starting point
cp -r ai/models/your_model/1.0.0 ai/models/your_model/1.1.0

# Update version in model.yaml
cd ai/models/your_model/1.1.0
# Edit model.yaml: version: "1.1.0"

# Make your changes
# - Update inference logic
# - Update weights
# - Update contract if needed
```

**Checklist for new version:**

- [ ] Created new directory `{model_id}/{new_version}/`
- [ ] Updated `version` in `model.yaml`
- [ ] Did NOT modify the old version
- [ ] Updated weights if applicable
- [ ] Tested locally

### How Rollback Works

The platform automatically handles version resolution:

1. If a camera requests `model_id` without version → gets **latest healthy version**
2. If the latest version becomes UNHEALTHY → automatically falls back to previous healthy version
3. If a camera requests specific version → always gets that version (or error if unavailable)

**You don't need to do anything for rollback to work.** Just ensure old versions remain intact.

### Version Coexistence

Multiple versions run simultaneously:

```
ai/models/fall_detection/
├── 1.0.0/    # Still running for cameras pinned to 1.0.0
├── 1.1.0/    # Running for cameras pinned to 1.1.0
└── 1.2.0/    # Latest - used for new cameras
```

Each version has:
- Independent memory space
- Independent health status
- Independent concurrency limits

---

## 6. Validation Checklist

**Run through this checklist before submitting a model.**

### Directory Structure

- [ ] Path is `ai/models/{model_id}/{version}/`
- [ ] `model_id` uses only lowercase, numbers, underscores
- [ ] `version` follows semver format (e.g., `1.0.0`)
- [ ] `model.yaml` exists in version directory
- [ ] `inference.py` exists in version directory

### Contract Validation

- [ ] `contract_schema_version` is `"1.0.0"`
- [ ] `model_id` in YAML matches directory name
- [ ] `version` in YAML matches directory name
- [ ] All required sections present (`input`, `output`, `hardware`, `performance`)
- [ ] `output.schema` declares all fields returned by `infer()`
- [ ] `hardware.supports_cpu` is `true` if model works without GPU

### Entry Points

- [ ] `inference.py` contains `def infer(frame, **kwargs) -> dict`
- [ ] `infer()` returns a dictionary
- [ ] Return dict matches declared `output.schema`
- [ ] All exceptions are caught (no unhandled errors)
- [ ] If `loader.py` exists, it contains `def load(weights_path) -> Any`
- [ ] If `preprocess.py` exists, it contains `def preprocess(raw_input, **kwargs) -> Any`
- [ ] If `postprocess.py` exists, it contains `def postprocess(raw_output, **kwargs) -> dict`

### Dependencies

- [ ] All imports are available in runtime container
- [ ] If extra deps needed, `requirements.txt` exists
- [ ] No absolute paths in code
- [ ] No hardcoded file paths outside model directory

### Weights

- [ ] If model needs weights, `weights/` directory exists
- [ ] Weight files are present (or download script provided)
- [ ] `loader.py` correctly references weights path
- [ ] Weights load on CPU (not just GPU)

### Output Compliance

- [ ] Every field in output is declared in `output.schema`
- [ ] `event_type` values match declared `enum`
- [ ] `confidence` is between 0.0 and 1.0
- [ ] No raw frame data in output
- [ ] No absolute paths in output

---

## 7. Common Mistakes

### Mistake: `model_id` Mismatch

```yaml
# model.yaml in ai/models/fall_detection/1.0.0/
model_id: "fall-detection"  # WRONG - has hyphen
```

**Consequence:** Model not discovered or validation fails.

**Fix:** Match directory name exactly:
```yaml
model_id: "fall_detection"  # Matches directory
```

### Mistake: Missing `inference.py`

```
ai/models/my_model/1.0.0/
├── model.yaml
└── detector.py    # WRONG - not the default entry point
```

**Consequence:** Model loads but inference fails.

**Fix:** Either rename to `inference.py` or declare in `model.yaml`:
```yaml
entry_points:
  inference: "detector.py"
```

### Mistake: Using Hyphens in `model_id`

```yaml
model_id: "helmet-detection"  # INVALID
```

**Consequence:** Validation rejects the model.

**Fix:** Use underscores:
```yaml
model_id: "helmet_detection"  # Valid
```

### Mistake: Modifying an Existing Version

```bash
# DON'T DO THIS
cd ai/models/fall_detection/1.0.0
git pull  # Updates code in-place
```

**Consequence:** Running inferences may get inconsistent results, cached models may misbehave.

**Fix:** Create a new version:
```bash
cp -r ai/models/fall_detection/1.0.0 ai/models/fall_detection/1.0.1
# Edit the new version
```

### Mistake: Forgetting `weights/`

```python
# loader.py
def load(weights_path):
    model = torch.load("weights/model.pt")  # WRONG - relative path
```

**Consequence:** Works locally, fails in container.

**Fix:** Use provided `weights_path`:
```python
def load(weights_path):
    model = torch.load(weights_path / "model.pt")  # Correct
```

### Mistake: Returning Undeclared Fields

```yaml
# model.yaml
output:
  schema:
    event_type: { type: "string" }
    confidence: { type: "number" }
```

```python
# inference.py
def infer(frame, **kwargs):
    return {
        "event_type": "detected",
        "confidence": 0.9,
        "bounding_boxes": [...]  # NOT DECLARED in schema
    }
```

**Consequence:** May work, but violates contract. Future validation may reject.

**Fix:** Declare all output fields in `model.yaml`.

### Mistake: Assuming GPU Availability

```python
def load(weights_path):
    model = torch.load(weights_path / "model.pt")
    model.cuda()  # WRONG - assumes GPU
    return model
```

**Consequence:** Crashes on CPU-only or Jetson deployments.

**Fix:** Check availability:
```python
def load(weights_path):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = torch.load(weights_path / "model.pt", map_location=device)
    model.to(device)
    return model
```

---

## 8. Debugging Guide

### Model Not Discovered

**Symptoms:** Model doesn't appear in registry.

**Check:**
1. Directory path is `ai/models/{model_id}/{version}/`
2. `model.yaml` exists
3. No hidden characters in directory name
4. Directory isn't a symlink (unless explicitly allowed)

**Debug command:**
```bash
ls -la ai/models/
ls -la ai/models/your_model/
```

### Model Marked INVALID

**Symptoms:** Model discovered but state is `INVALID`.

**Check:**
1. `model_id` in YAML matches directory
2. `version` in YAML matches directory
3. All required YAML sections present
4. YAML syntax is valid

**Debug:**
```python
# Run contract validation manually
from ai.runtime.validator import ContractValidator
from pathlib import Path

validator = ContractValidator()
result = validator.validate(
    version_path=Path("ai/models/your_model/1.0.0"),
    expected_model_id="your_model",
    expected_version="1.0.0",
)

print(f"Valid: {result.is_valid}")
for error in result.errors:
    print(f"  Error: {error.message}")
```

### Model Fails to Load

**Symptoms:** Model validated but state is `FAILED`.

**Common causes:**
1. Import error in `inference.py`
2. Missing dependency
3. `infer` function not found
4. Syntax error in Python code

**Debug:**
```python
# Try importing manually
import sys
sys.path.insert(0, "ai/models/your_model/1.0.0")
import inference  # Will show import error
```

### Dependency Missing

**Symptoms:** `ModuleNotFoundError: No module named 'xxx'`

**Cause:** Your model imports a package not in the runtime container.

**Fix:**
1. Check if it's a standard package (should be included)
2. Add to `requirements.txt` in your model directory
3. Contact platform team if core dependency missing

**Example:**
```
# ai/models/your_model/1.0.0/requirements.txt
transformers>=4.0.0
scipy>=1.7.0
```

### Understanding Health States

| State | Meaning | Action |
|-------|---------|--------|
| HEALTHY | Model working normally | None |
| DEGRADED | Some failures, still serving | Monitor closely |
| UNHEALTHY | Many failures, circuit open | Check logs, may need fix |
| DISABLED | Manually or automatically disabled | Investigate and fix |

**Health transitions:**
- 3 consecutive failures → DEGRADED
- 5 consecutive failures → UNHEALTHY
- 5 consecutive successes → recovers to HEALTHY

### Reading Validation Errors

Error codes follow a pattern:

| Prefix | Category |
|--------|----------|
| `VAL_*` | Contract validation |
| `LOAD_*` | Model loading |
| `EXEC_*` | Inference execution |
| `DISC_*` | Discovery scanning |

**Example errors:**

```
VAL_MODEL_ID_MISMATCH: model_id 'foo' doesn't match directory 'bar'
LOAD_MISSING_DEPENDENCY: No module named 'torch'
EXEC_INFERENCE_TIMEOUT: Inference exceeded 5000ms limit
```

---

## 9. Validation Scenarios

The platform includes automated validation scenarios (A12) that test:

### Scenario 1: Multi-Model Load

**What it tests:** Multiple models coexisting without interference.

**What you should know:** Your model will run alongside others. It must not:
- Use global variables unsafely
- Modify shared state
- Assume exclusive resources

### Scenario 2: Broken Model Simulation

**What it tests:** A failing model doesn't crash others.

**What you should know:** If your model fails, only YOUR model is affected. The circuit breaker will disable it after repeated failures.

### Scenario 3: Version Upgrade

**What it tests:** Side-by-side versions and automatic rollback.

**What you should know:** When you deploy a new version, old versions keep running. If the new version fails, traffic rolls back automatically.

### Scenario 4: Concurrent Stress

**What it tests:** High concurrency without resource leaks.

**What you should know:** Set appropriate `max_concurrent_inferences` in your contract. If you claim to support 4 concurrent requests, the platform will send 4.

### Scenario 5: Backend Contract Stability

**What it tests:** Backend sees capability reports, not raw data.

**What you should know:** Your model's output goes to the backend as structured data. Never include raw frames or internal paths.

### Container vs. Development Shell

**Important:** Validation scenarios may show different results depending on environment:

| Environment | PyTorch | Full Models |
|-------------|---------|-------------|
| Dev shell | Maybe not | May fail to load |
| AI Runtime container | Yes | Should work |

If you see `ModuleNotFoundError: No module named 'torch'` during local testing, this is expected. The model will work inside the container.

---

## 10. Best Practices

### Keep Models Stateless

```python
# GOOD - No state between calls
def infer(frame, model=None, **kwargs):
    result = model.predict(frame)
    return {"event_type": "detected", "confidence": result.score}

# BAD - State leaks between calls
frame_count = 0
def infer(frame, **kwargs):
    global frame_count
    frame_count += 1  # Leaks state
```

### Declare Everything Explicitly

```yaml
# GOOD - Explicit about all capabilities
hardware:
  supports_cpu: true
  supports_gpu: true
  supports_jetson: false  # Explicit "no"
  min_ram_mb: 2048

# BAD - Missing required info
hardware:
  supports_gpu: true
  # Missing supports_cpu - will default, but unclear
```

### Use Conservative Resource Limits

```yaml
# GOOD - Conservative limits
limits:
  max_memory_mb: 4096
  inference_timeout_ms: 5000
  max_concurrent_inferences: 2  # Start low

# BAD - Aggressive limits
limits:
  max_memory_mb: 16384  # Excessive
  inference_timeout_ms: 30000  # Too long
  max_concurrent_inferences: 10  # Probably can't sustain
```

### Prefer New Versions Over Edits

```bash
# GOOD - New version for changes
cp -r ai/models/my_model/1.0.0 ai/models/my_model/1.0.1
# Edit 1.0.1

# BAD - Edit in place
cd ai/models/my_model/1.0.0
vim inference.py  # Don't do this
```

### Test with Dummy Models First

Before integrating your real model:

1. Copy the `dummy_detector` template
2. Replace inference logic with yours
3. Verify it loads and runs
4. Then add your weights

```bash
cp -r ai/models/dummy_detector/1.0.0 ai/models/your_model/1.0.0
# Edit model.yaml with your model_id
# Edit inference.py with your logic
```

### Handle Errors Gracefully

```python
def infer(frame, model=None, **kwargs):
    try:
        result = model.predict(frame)
        return {
            "event_type": "detected",
            "confidence": result.score,
        }
    except Exception as e:
        # Log but don't crash
        logger.error(f"Inference failed: {e}")
        return {
            "event_type": "not_detected",
            "confidence": 0.0,
            "error": str(e),  # Include for debugging
        }
```

---

## 11. What You Should NEVER Do

### Never Modify Runtime Code

```bash
# NEVER DO THIS
vim ai/runtime/loader.py
vim ai/runtime/pipeline.py
```

If you need runtime changes, contact the platform team. Model integration must work without runtime modifications.

### Never Modify Backend APIs

```bash
# NEVER DO THIS
vim backend/api/endpoints.py
vim backend/schemas/events.py
```

Your model produces output that the backend consumes. You don't change the backend to fit your model.

### Never Share Files Across Versions

```
ai/models/my_model/
├── shared_weights/     # NEVER DO THIS
├── 1.0.0/
│   └── (references shared_weights)
└── 1.1.0/
    └── (references shared_weights)
```

Each version must be self-contained. Shared files break version isolation.

### Never Hardcode Paths

```python
# NEVER DO THIS
model = torch.load("/app/ai/models/my_model/1.0.0/weights/model.pt")

# DO THIS
def load(weights_path):
    model = torch.load(weights_path / "model.pt")
```

### Never Add Model-Specific Assumptions

```python
# NEVER DO THIS in runtime code
if model_id == "fall_detection":
    # Special handling for fall detection
```

All models are equal. No special cases.

### Never Return Raw Frames

```python
# NEVER DO THIS
def infer(frame, **kwargs):
    return {
        "event_type": "detected",
        "frame": frame,  # NEVER include raw frame
    }
```

Output goes to backend. Backend must not receive raw video data.

---

## 12. FAQ

### "Why can't I use `latest` as a version?"

`latest` is resolved dynamically by the platform. You cannot create a directory called `latest`. Instead:

- Create versioned directories: `1.0.0`, `1.1.0`, etc.
- The platform automatically selects the highest healthy version as "latest"
- Cameras can request `model_id` without version to get latest

### "Why does my model load but not execute?"

Common causes:

1. `infer()` function missing or wrong signature
2. `infer()` raises exception (check logs)
3. Output doesn't match declared schema
4. Timeout exceeded

Check the runtime logs for specific error messages.

### "How do I disable a broken model?"

**Automatic:** The circuit breaker disables models after repeated failures.

**Manual:** Contact platform operations to manually disable:
```bash
# Platform admin command
curl -X POST http://runtime:8080/admin/models/your_model/1.0.0/disable
```

### "How do I test without GPU?"

Ensure your `model.yaml` declares CPU support:
```yaml
hardware:
  supports_cpu: true
```

And your code handles it:
```python
device = "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)
```

### "Can I use TensorFlow instead of PyTorch?"

Contact the platform team. The base container includes PyTorch. TensorFlow requires a different container image or custom build.

### "How do I know my model is healthy?"

Check the health endpoint:
```bash
curl http://runtime:8080/health/models/your_model/1.0.0
```

Or view the dashboard (if available).

### "My model needs 30 seconds to load. Is that okay?"

Yes, but declare it appropriately:
```yaml
performance:
  warmup_iterations: 1  # Reduce warmup if load is slow
```

The platform waits for models to load. Slow loading doesn't affect runtime operation, only startup time.

### "Can I have dependencies on other models?"

No. Models must be independent. If you need to chain models:
- Create a composite model that internally calls both
- Or request this as a platform feature

### "How do I roll back after a bad deployment?"

You don't need to do anything. If your new version becomes UNHEALTHY:
1. Circuit breaker disables it
2. Version resolver falls back to previous healthy version
3. Traffic automatically routes to old version

To explicitly rollback:
1. Remove or rename the bad version directory
2. Restart runtime (or trigger rescan)

---

## Summary

Adding a model to Ruth AI is straightforward if you follow the rules:

1. **Create directory:** `ai/models/{model_id}/{version}/`
2. **Write contract:** `model.yaml` with all required sections
3. **Implement inference:** `inference.py` with `infer()` function
4. **Add weights:** Place in `weights/` directory
5. **Restart runtime:** Model is automatically discovered

If something goes wrong:
- Check the validation checklist
- Read the debugging guide
- Look at common mistakes

The platform handles discovery, loading, health, concurrency, and failure isolation. You just provide the model.

---

**Questions?** Contact the Platform Team.

**Found an issue with this guide?** Submit a PR to update it.
