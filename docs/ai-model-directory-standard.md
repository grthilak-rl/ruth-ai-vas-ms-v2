# Ruth AI Model Directory Standard

**Version:** 1.0
**Author:** AI Platform Engineer Agent
**Date:** January 2026
**Status:** PHASE 5 – Task A3 Deliverable (DESIGN ONLY)

---

## Executive Summary

This document defines the **canonical, enforceable directory standard** for AI models in the Ruth AI platform. It establishes filesystem contracts that enable:

- **Predictable Integration** – Any AI engineer can add a model by following this standard
- **Automated Validation** – Invalid structures are detected without loading models
- **Zero-Disruption Addition** – Adding a model never affects existing models
- **Safe Removal** – Deleting a model directory is the only step required to remove it
- **Parallel Development** – Multiple teams can develop models independently

**This standard is a filesystem contract, not runtime behavior.**

The runtime discovers and validates models based solely on directory structure and `model.yaml` content. No code changes are ever required to add, upgrade, or remove models.

---

## Table of Contents

1. [Design Principles](#1-design-principles)
2. [Canonical Directory Tree](#2-canonical-directory-tree)
3. [Naming Rules](#3-naming-rules)
4. [Required, Optional, and Forbidden Content](#4-required-optional-and-forbidden-content)
5. [Version Coexistence Rules](#5-version-coexistence-rules)
6. [Model Lifecycle Rules](#6-model-lifecycle-rules)
7. [Validation Rules](#7-validation-rules)
8. [Common Violations](#8-common-violations)
9. [Examples](#9-examples)
10. [Rationale Summary](#10-rationale-summary)

---

## 1. Design Principles

### 1.1 Guiding Principles

| Principle | Description | Enforcement |
|-----------|-------------|-------------|
| **Explicit Structure** | Directory layout determines model identity | Structural validation at discovery |
| **Self-Contained Models** | Each model version is fully isolated | No cross-version dependencies allowed |
| **Convention over Configuration** | Standard locations for standard files | Runtime expects files in defined locations |
| **Fail-Fast Validation** | Invalid structures rejected immediately | Pre-load validation rejects bad models |
| **Zero Coupling** | Models cannot reference other models | No inter-model imports or paths |

### 1.2 What This Standard Guarantees

If a model directory follows this standard:

1. ✅ The runtime will discover the model
2. ✅ The runtime will attempt to validate and load it
3. ✅ The model can be added without affecting other models
4. ✅ The model can be removed by deleting its directory
5. ✅ Multiple versions can coexist

If a model directory violates this standard:

1. ❌ The model will be marked INVALID
2. ❌ The model will not receive inference requests
3. ❌ The violation will be logged with specific reason
4. ✅ Other valid models continue operating normally

### 1.3 Scope Boundaries

**This Standard Covers:**
- Directory structure
- File naming
- File presence requirements
- Version directory rules
- Forbidden content

**This Standard Does NOT Cover:**
- File contents (see [ai-model-contract.md](ai-model-contract.md))
- Runtime loading behavior (see [ai-runtime-architecture.md](ai-runtime-architecture.md))
- Model implementation
- Training pipelines

---

## 2. Canonical Directory Tree

### 2.1 Root Structure

```
ai/
└── models/                              # MODEL ROOT - runtime scans this directory
    ├── <model_id>/                      # MODEL DIRECTORY - one per model
    │   ├── <version>/                   # VERSION DIRECTORY - one per version
    │   │   └── <model files>            # Model implementation files
    │   ├── <version>/
    │   │   └── ...
    │   └── .metadata/                   # OPTIONAL: Model-level metadata
    │       └── ...
    ├── <model_id>/
    │   └── ...
    └── .registry/                       # OPTIONAL: Platform-level metadata
        └── ...
```

### 2.2 Model Version Directory Structure (Authoritative)

```
ai/models/<model_id>/<version>/
│
├── model.yaml                           # REQUIRED: Model contract
│
├── weights/                             # REQUIRED: Weights directory
│   ├── model.onnx                       #   Weight files (format varies)
│   ├── model.pt                         #   May contain multiple files
│   └── ...                              #   Subdirectories allowed
│
├── inference.py                         # REQUIRED: Inference entry point
│
├── preprocessing.py                     # OPTIONAL: Preprocessing module
│
├── postprocessing.py                    # OPTIONAL: Postprocessing module
│
├── requirements.txt                     # OPTIONAL: Model-specific dependencies
│
├── config.yaml                          # OPTIONAL: Model-specific configuration
│
├── README.md                            # OPTIONAL: Model documentation
│
├── tests/                               # OPTIONAL: Model test suite
│   ├── test_inference.py
│   └── test_data/
│       └── ...
│
├── assets/                              # OPTIONAL: Additional assets
│   ├── labels.txt                       #   Label files, configs, etc.
│   └── ...
│
└── .meta/                               # OPTIONAL: Version-level metadata
    └── ...
```

### 2.3 Directory Hierarchy Rules

| Level | Directory | Cardinality | Purpose |
|-------|-----------|-------------|---------|
| 0 | `ai/` | Exactly 1 | AI subsystem root |
| 1 | `ai/models/` | Exactly 1 | Model root (runtime scans here) |
| 2 | `ai/models/<model_id>/` | 0 to N | One directory per model |
| 3 | `ai/models/<model_id>/<version>/` | 1 to N per model | One directory per version |
| 4 | Files and subdirectories | Per standard | Model implementation |

### 2.4 Path Resolution

**Canonical Path Format:**
```
ai/models/{model_id}/{version}/{file_or_directory}
```

**Examples:**
```
ai/models/fall_detection/1.0.0/model.yaml
ai/models/fall_detection/1.0.0/weights/model.onnx
ai/models/helmet_detection/0.1.0/inference.py
```

**Path Constraints:**
- All paths are relative to repository/deployment root
- No absolute paths in model files
- No symlinks pointing outside model directory (see §4.4)
- No path traversal (`../`) references

---

## 3. Naming Rules

### 3.1 Model ID Naming

**Pattern:** `^[a-z][a-z0-9_]{2,63}$`

**Rules:**
| Rule | Requirement | Rationale |
|------|-------------|-----------|
| Start with letter | Must begin with `[a-z]` | Ensures valid identifier in all contexts |
| Allowed characters | `[a-z0-9_]` only | Filesystem-safe, URL-safe, code-safe |
| Minimum length | 3 characters | Prevents ambiguous short names |
| Maximum length | 64 characters | Filesystem compatibility |
| Case | Lowercase only | Case-insensitive filesystem safety |
| No hyphens | Use underscore instead | Consistent separator |

**Valid Examples:**
```
fall_detection
helmet_detection
fire_smoke_v2
person_tracking
ppe_compliance_check
model_abc_123
```

**Invalid Examples:**
| Example | Violation |
|---------|-----------|
| `Fall_Detection` | Uppercase letters |
| `fall-detection` | Hyphen not allowed |
| `1_model` | Starts with number |
| `fd` | Too short (< 3 chars) |
| `a_very_long_model_name_that_exceeds_sixty_four_characters_limit_here` | Too long (> 64 chars) |
| `fall detection` | Space not allowed |
| `fall.detection` | Period not allowed |

### 3.2 Version Naming

**Pattern:** `^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[a-zA-Z0-9]+(\.[a-zA-Z0-9]+)*)?$`

**Format:** Semantic Versioning (SemVer 2.0)

**Structure:**
```
MAJOR.MINOR.PATCH[-PRERELEASE]

MAJOR   = Breaking changes (output schema changes)
MINOR   = New features, backward compatible
PATCH   = Bug fixes, no API changes
PRERELEASE = Optional pre-release identifier
```

**Rules:**
| Rule | Requirement | Rationale |
|------|-------------|-----------|
| Three components | `X.Y.Z` required | Full semantic version |
| No leading zeros | `1.0.0` not `01.00.00` | SemVer compliance |
| Pre-release suffix | Optional, after hyphen | Development versions |
| No `v` prefix | `1.0.0` not `v1.0.0` | Consistency |
| No `latest` alias | Version must be explicit | Deterministic behavior |

**Valid Examples:**
```
1.0.0
0.1.0
2.3.15
1.0.0-alpha
1.0.0-beta.1
2.0.0-rc.2
0.0.1-dev
```

**Invalid Examples:**
| Example | Violation |
|---------|-----------|
| `v1.0.0` | `v` prefix not allowed |
| `1.0` | Missing patch component |
| `1` | Missing minor and patch |
| `01.00.00` | Leading zeros |
| `latest` | Not a version |
| `1.0.0.0` | Too many components |
| `1.0.0_beta` | Underscore not allowed in prerelease |

### 3.3 File Naming

**Required Files:**

| File | Exact Name | Case Sensitive |
|------|------------|----------------|
| Contract | `model.yaml` | Yes |
| Inference | `inference.py` | Yes |
| Weights directory | `weights/` | Yes |

**Optional Files (Standard Names):**

| File | Standard Name | Alternatives Allowed |
|------|---------------|---------------------|
| Preprocessing | `preprocessing.py` | No |
| Postprocessing | `postprocessing.py` | No |
| Dependencies | `requirements.txt` | No |
| Configuration | `config.yaml` | `config.yml` |
| Documentation | `README.md` | `readme.md` |

**Custom Files:**

| Location | Naming Rules |
|----------|--------------|
| `weights/` | Any names allowed |
| `assets/` | Any names allowed |
| `tests/` | Any names allowed |
| `.meta/` | Any names allowed |

### 3.4 Directory-to-Contract Consistency

**Critical Rule:** Directory names MUST match `model.yaml` declarations.

```
Directory: ai/models/fall_detection/1.0.0/
                     └─────┬─────┘ └──┬──┘
                           │         │
model.yaml:        model_id: "fall_detection"
                   version: "1.0.0"
                                     │
                           Must match exactly
```

**Validation:**
- Runtime compares directory `<model_id>` with `model.yaml:model_id`
- Runtime compares directory `<version>` with `model.yaml:version`
- Mismatch → Model marked INVALID

---

## 4. Required, Optional, and Forbidden Content

### 4.1 Required Content

| Item | Path | Validation |
|------|------|------------|
| Model contract | `model.yaml` | Must exist, must be valid YAML, must pass schema validation |
| Weights directory | `weights/` | Must exist as directory (may be empty for test models) |
| Inference module | `inference.py` | Must exist, must define `infer()` function |

**Validation Behavior:**
- Missing required item → Model state: `INVALID`
- Invalid content in required item → Model state: `INVALID`
- All required items present and valid → Proceed to loading

### 4.2 Optional Content

| Item | Path | Behavior if Missing |
|------|------|---------------------|
| Preprocessing module | `preprocessing.py` | Runtime uses identity preprocessing |
| Postprocessing module | `postprocessing.py` | Runtime uses identity postprocessing |
| Dependencies file | `requirements.txt` | No model-specific dependencies installed |
| Configuration file | `config.yaml` | Empty configuration provided to model |
| Documentation | `README.md` | No documentation (not recommended) |
| Test suite | `tests/` | No tests (not recommended) |
| Assets directory | `assets/` | No additional assets |
| Metadata directory | `.meta/` | No version metadata |

**Validation Behavior:**
- Missing optional item → Continue (no error)
- Invalid content in optional item → Warning logged, item ignored
- Malformed `preprocessing.py` → Model state: `INVALID` (if declared in entry_points)

### 4.3 Forbidden Content

| Item | Reason | Consequence |
|------|--------|-------------|
| Symlinks to outside model directory | Security, isolation | INVALID |
| Executable binaries (non-Python) | Security risk | INVALID |
| Files larger than 10GB individual | Resource limits | Warning (configurable) |
| Hidden files starting with `.` at version root | Ambiguity | Ignored (except `.meta/`) |
| `__pycache__/` directories | Build artifacts | Ignored |
| `.git/` directories | Source control artifacts | Ignored |
| Files with shell script extensions | Security risk | Warning |

**Forbidden File Patterns:**
```
*.sh         # Shell scripts
*.bash       # Bash scripts
*.exe        # Windows executables
*.dll        # Windows libraries
*.so         # Shared objects (except in weights/)
*.dylib      # macOS libraries
```

**Exception:** `.so` files inside `weights/` are allowed for compiled model components.

### 4.4 Symlink Rules

| Symlink Target | Allowed | Rationale |
|----------------|---------|-----------|
| Within same version directory | Yes | Convenience |
| To sibling version directory | **No** | Version isolation |
| To other model directory | **No** | Model isolation |
| To outside `ai/models/` | **No** | Security |
| Absolute paths | **No** | Portability |

**Example:**
```
ai/models/fall_detection/1.0.0/
├── weights/
│   ├── model.onnx                    # Real file
│   └── model_quantized.onnx -> model.onnx   # ✅ OK (same directory)
├── config.yaml
└── alt_config.yaml -> config.yaml    # ✅ OK (same version)

ai/models/fall_detection/
├── 1.0.0/
│   └── weights/ -> ../1.1.0/weights/ # ❌ FORBIDDEN (cross-version)
└── 1.1.0/
    └── weights/
```

### 4.5 Content Summary Table

| Category | Items | Validation |
|----------|-------|------------|
| **REQUIRED** | `model.yaml`, `weights/`, `inference.py` | Must exist and be valid |
| **OPTIONAL** | `preprocessing.py`, `postprocessing.py`, `requirements.txt`, `config.yaml`, `README.md`, `tests/`, `assets/`, `.meta/` | If present, must be valid |
| **IGNORED** | `__pycache__/`, `.git/`, `.gitignore`, `.DS_Store`, `*.pyc` | Silently skipped |
| **FORBIDDEN** | External symlinks, executables, shell scripts | Causes INVALID state |

---

## 5. Version Coexistence Rules

### 5.1 Multiple Versions Coexistence

**Fundamental Rule:** Multiple versions of the same model MUST coexist without conflict.

```
ai/models/fall_detection/
├── 1.0.0/                    # Production stable
│   ├── model.yaml
│   └── ...
├── 1.1.0/                    # Production with new features
│   ├── model.yaml
│   └── ...
├── 2.0.0-beta/               # Beta testing
│   ├── model.yaml
│   └── ...
└── 2.0.0-rc.1/               # Release candidate
    ├── model.yaml
    └── ...
```

### 5.2 Version Independence Invariants

| Invariant | Enforcement |
|-----------|-------------|
| No shared files | Each version has its own complete file set |
| No shared state | Runtime loads each version independently |
| No implicit dependencies | Version A cannot reference Version B |
| Independent loading | Version A failing does not affect Version B |
| Independent health | Each version has its own health status |

### 5.3 Version Ordering

**Discovery Order:** Versions are discovered alphabetically by directory name.

**Load Priority:** When resources are constrained:
1. Explicitly configured versions (via runtime config)
2. Higher semantic versions (2.0.0 > 1.9.0 > 1.0.0)
3. Stable versions before pre-release (1.0.0 > 1.0.0-beta)

**Request Resolution:**
- Backend MUST specify `model_id` AND `version`
- No "latest" resolution
- No default version fallback
- Missing version → Error `VERSION_NOT_FOUND`

### 5.4 Partial Deployments

**Scenario:** Not all versions are deployed to all environments.

```
Production Environment:
ai/models/fall_detection/
├── 1.0.0/     # Deployed
└── 1.1.0/     # Deployed

Staging Environment:
ai/models/fall_detection/
├── 1.0.0/     # Deployed
├── 1.1.0/     # Deployed
└── 2.0.0-beta/ # Deployed (not in prod)
```

**Rules:**
- Each environment discovers only what's present
- Missing version in environment → Not available (not error)
- Backend must handle `MODEL_NOT_FOUND` responses

### 5.5 Version Removal

**Safe Removal Process:**
1. Stop sending requests to version
2. Wait for in-flight requests to complete
3. Delete version directory
4. Runtime detects removal, unloads model

**Rules:**
- Removing a version does NOT affect other versions
- Removing the only version removes the model entirely
- Empty model directory (no versions) is ignored

---

## 6. Model Lifecycle Rules

### 6.1 Adding a New Model

**Process:**
1. Create model directory: `ai/models/<model_id>/`
2. Create version directory: `ai/models/<model_id>/<version>/`
3. Add required files: `model.yaml`, `weights/`, `inference.py`
4. Runtime discovers on next scan (startup or SIGHUP)

**Zero-Disruption Guarantee:**
- No existing model directories are modified
- No runtime configuration changes required
- No backend changes required
- Other models continue operating normally

### 6.2 Adding a New Version

**Process:**
1. Create version directory: `ai/models/<model_id>/<new_version>/`
2. Add required files (independent of other versions)
3. Runtime discovers on next scan

**Coexistence Guarantee:**
- Existing versions remain unchanged
- Both versions become available
- Backend chooses which version to use

### 6.3 Upgrading a Version

**Recommended Process:**
1. Add new version directory (e.g., `1.1.0/`)
2. Validate new version works correctly
3. Update backend to request new version
4. Monitor for issues
5. Remove old version when confident

**Anti-Pattern (FORBIDDEN):**
```
# ❌ NEVER modify an existing version in place
ai/models/fall_detection/1.0.0/
├── model.yaml            # Modified in place - WRONG
└── weights/              # Updated - WRONG
```

**Correct Pattern:**
```
# ✅ ALWAYS add a new version
ai/models/fall_detection/
├── 1.0.0/                # Unchanged
│   └── ...
└── 1.0.1/                # New version with fix
    └── ...
```

### 6.4 Rolling Back

**Process:**
1. Update backend to request previous version
2. Previous version must still exist
3. Optionally remove failed version

**Rollback Guarantee:**
- Old versions remain functional if not deleted
- No runtime changes needed
- Backend controls version selection

### 6.5 Removing a Model

**Process:**
1. Stop all cameras using the model
2. Delete entire model directory: `rm -rf ai/models/<model_id>/`
3. Runtime detects removal, cleans up

**Removal Guarantee:**
- Other models unaffected
- No runtime configuration cleanup needed
- No database cleanup needed (Backend handles)

### 6.6 Experimental Models

**Convention:** Use pre-release version suffix.

```
ai/models/experimental_detector/
├── 0.0.1-dev/            # Development
├── 0.1.0-alpha/          # Alpha testing
├── 0.1.0-beta.1/         # Beta testing
└── 0.1.0-rc.1/           # Release candidate
```

**Rules:**
- Experimental versions follow same structure
- No special handling by runtime
- Backend decides whether to use experimental versions

### 6.7 Disabling a Model (Without Removal)

**Option 1: Rename directory**
```
ai/models/fall_detection/           # Active
ai/models/.disabled.fall_detection/ # Disabled (hidden)
```

**Option 2: Remove from model root**
```
ai/
├── models/                         # Active models
│   └── helmet_detection/
└── disabled_models/                # Disabled (not scanned)
    └── fall_detection/
```

**Option 3: Runtime configuration**
- Configure runtime to skip specific model_ids
- Directory remains, but not loaded

---

## 7. Validation Rules

### 7.1 Validation Stages

```
┌─────────────────────────────────────────────────────────────────────┐
│                    DIRECTORY VALIDATION PIPELINE                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  STAGE 1: DISCOVERY                                                  │
│  ─────────────────                                                   │
│  ✓ Scan ai/models/ for subdirectories                               │
│  ✓ Each subdirectory is a potential model_id                        │
│  ✓ Skip hidden directories (starting with .)                        │
│  ✓ Skip non-directories                                              │
│                                                                      │
│  STAGE 2: MODEL DIRECTORY VALIDATION                                 │
│  ───────────────────────────────────                                 │
│  ✓ Validate model_id matches naming pattern                         │
│  ✓ Scan for version subdirectories                                  │
│  ✓ At least one version required                                     │
│  ✓ Skip invalid version names                                        │
│                                                                      │
│  STAGE 3: VERSION DIRECTORY VALIDATION                               │
│  ─────────────────────────────────────                               │
│  ✓ Validate version matches SemVer pattern                          │
│  ✓ Check required files exist                                        │
│  ✓ Check forbidden content absent                                    │
│  ✓ Validate symlinks (if any)                                        │
│                                                                      │
│  STAGE 4: CONTRACT VALIDATION                                        │
│  ────────────────────────────                                        │
│  ✓ Parse model.yaml                                                  │
│  ✓ Validate against schema                                           │
│  ✓ Verify directory name matches model_id                           │
│  ✓ Verify directory name matches version                             │
│                                                                      │
│  STAGE 5: ENTRY POINT VALIDATION                                     │
│  ───────────────────────────────                                     │
│  ✓ Check inference.py defines infer() function                      │
│  ✓ Check optional modules define required functions                  │
│  ✓ No syntax errors in Python files                                  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 7.2 Validation Outcomes

| Stage | Failure | Model State | Other Models |
|-------|---------|-------------|--------------|
| Discovery | Invalid model_id pattern | Skipped (logged) | Unaffected |
| Model Directory | No valid versions | Skipped (logged) | Unaffected |
| Version Directory | Missing required files | INVALID | Unaffected |
| Contract | Invalid model.yaml | INVALID | Unaffected |
| Entry Point | Missing infer() | INVALID | Unaffected |
| All stages pass | - | DISCOVERED | Unaffected |

### 7.3 Validation Error Messages

**Format:**
```
VALIDATION_ERROR: <code>
  Model: <model_id>
  Version: <version>
  Path: <path>
  Details: <specific issue>
  Action: <recommended fix>
```

**Example Messages:**

```
VALIDATION_ERROR: MISSING_REQUIRED_FILE
  Model: fall_detection
  Version: 1.0.0
  Path: ai/models/fall_detection/1.0.0/model.yaml
  Details: Required file 'model.yaml' not found
  Action: Create model.yaml with required fields

VALIDATION_ERROR: NAME_MISMATCH
  Model: fall_detection
  Version: 1.0.0
  Path: ai/models/fall_detection/1.0.0/model.yaml
  Details: Directory name 'fall_detection' does not match model_id 'fall-detection' in model.yaml
  Action: Ensure directory name matches model_id in model.yaml

VALIDATION_ERROR: INVALID_VERSION_FORMAT
  Model: fall_detection
  Version: v1.0
  Path: ai/models/fall_detection/v1.0/
  Details: Version 'v1.0' does not match SemVer pattern
  Action: Rename directory to valid SemVer (e.g., '1.0.0')

VALIDATION_ERROR: FORBIDDEN_SYMLINK
  Model: fall_detection
  Version: 1.0.0
  Path: ai/models/fall_detection/1.0.0/weights
  Details: Symlink points outside model directory
  Action: Remove symlink or copy files into model directory
```

### 7.4 Validation Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `max_file_size_mb` | 10240 (10GB) | Warning for large files |
| `max_total_size_mb` | 51200 (50GB) | Warning for large models |
| `allow_empty_weights` | false | Allow empty weights/ for testing |
| `strict_symlinks` | true | Reject external symlinks |
| `validate_python_syntax` | true | Check Python files for syntax errors |

---

## 8. Common Violations

### 8.1 Violation Catalog

| ID | Violation | Severity | Detection |
|----|-----------|----------|-----------|
| V001 | Missing model.yaml | INVALID | Stage 3 |
| V002 | Missing weights/ directory | INVALID | Stage 3 |
| V003 | Missing inference.py | INVALID | Stage 3 |
| V004 | model_id mismatch | INVALID | Stage 4 |
| V005 | version mismatch | INVALID | Stage 4 |
| V006 | Invalid model_id pattern | SKIP | Stage 2 |
| V007 | Invalid version pattern | SKIP | Stage 2 |
| V008 | External symlink | INVALID | Stage 3 |
| V009 | Forbidden executable | INVALID | Stage 3 |
| V010 | Missing infer() function | INVALID | Stage 5 |
| V011 | Python syntax error | INVALID | Stage 5 |
| V012 | Invalid YAML syntax | INVALID | Stage 4 |
| V013 | Schema validation failure | INVALID | Stage 4 |
| V014 | Empty model directory | SKIP | Stage 2 |
| V015 | Oversized file | WARNING | Stage 3 |

### 8.2 Detailed Violation Descriptions

#### V001: Missing model.yaml

**Problem:**
```
ai/models/fall_detection/1.0.0/
├── weights/
└── inference.py
# model.yaml is missing!
```

**Consequence:** Model cannot be identified or configured.

**Fix:** Create `model.yaml` with all required fields.

---

#### V004: model_id Mismatch

**Problem:**
```
ai/models/fall_detection/1.0.0/model.yaml:
  model_id: "fall-detection"   # WRONG: hyphen, doesn't match directory
```

**Consequence:** Runtime cannot verify model identity.

**Fix:** Ensure `model_id` in model.yaml exactly matches directory name.

---

#### V006: Invalid model_id Pattern

**Problem:**
```
ai/models/
├── Fall_Detection/           # WRONG: uppercase
├── 123_model/                # WRONG: starts with number
└── fall-detection/           # WRONG: hyphen
```

**Consequence:** Directories are skipped entirely.

**Fix:** Use lowercase letters, numbers, and underscores only. Start with letter.

---

#### V008: External Symlink

**Problem:**
```
ai/models/fall_detection/1.0.0/
└── weights -> /shared/models/fall_detection/weights  # WRONG: external
```

**Consequence:** Security risk, portability issue.

**Fix:** Copy files into model directory or use relative symlinks within version.

---

#### V010: Missing infer() Function

**Problem:**
```python
# ai/models/fall_detection/1.0.0/inference.py
def run_inference(data):  # WRONG: function name
    ...
```

**Consequence:** Runtime cannot execute inference.

**Fix:** Define function named exactly `infer` with correct signature.

---

### 8.3 Self-Check Checklist

Before deploying a model, verify:

- [ ] Directory name matches `model_id` in model.yaml
- [ ] Directory name matches `version` in model.yaml
- [ ] `model.yaml` exists and is valid YAML
- [ ] `model.yaml` passes schema validation
- [ ] `weights/` directory exists
- [ ] `inference.py` exists
- [ ] `inference.py` defines `infer()` function
- [ ] No symlinks pointing outside version directory
- [ ] No forbidden file types
- [ ] model_id follows naming pattern (`^[a-z][a-z0-9_]{2,63}$`)
- [ ] version follows SemVer pattern

---

## 9. Examples

### 9.1 Minimal Valid Model Directory

```
ai/models/simple_detector/1.0.0/
├── model.yaml
├── weights/
│   └── model.onnx
└── inference.py
```

**model.yaml:**
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

**inference.py:**
```python
def infer(preprocessed_data, config, context):
    # Minimal implementation
    return InferenceResult(
        event_type="not_detected",
        confidence=0.0
    )
```

---

### 9.2 Full-Featured Model Directory

```
ai/models/fall_detection/1.0.0/
├── model.yaml                        # Model contract
├── weights/                          # Model weights
│   ├── backbone.onnx                 # Feature extractor
│   ├── pose_estimator.onnx          # Pose model
│   └── classifier.onnx              # Fall classifier
├── inference.py                      # Main inference
├── preprocessing.py                  # Input transforms
├── postprocessing.py                 # Output processing
├── requirements.txt                  # Dependencies
├── config.yaml                       # Configuration
├── README.md                         # Documentation
├── tests/                            # Test suite
│   ├── test_inference.py
│   ├── test_preprocessing.py
│   └── test_data/
│       ├── fall_sample.jpg
│       └── no_fall_sample.jpg
├── assets/                           # Additional files
│   ├── pose_labels.txt
│   └── fall_thresholds.yaml
└── .meta/                            # Metadata
    ├── training_info.yaml
    └── evaluation_results.json
```

---

### 9.3 Multi-Version Model

```
ai/models/helmet_detection/
├── 0.9.0/                            # Legacy version
│   ├── model.yaml
│   ├── weights/
│   │   └── model_v0.onnx
│   └── inference.py
├── 1.0.0/                            # Stable production
│   ├── model.yaml
│   ├── weights/
│   │   └── model_v1.onnx
│   └── inference.py
├── 1.1.0/                            # New features
│   ├── model.yaml
│   ├── weights/
│   │   └── model_v1.1.onnx
│   ├── inference.py
│   └── preprocessing.py
└── 2.0.0-beta/                       # Beta testing
    ├── model.yaml
    ├── weights/
    │   └── model_v2.onnx
    └── inference.py
```

---

### 9.4 Invalid Directory Examples

#### Example A: Invalid model_id

```
ai/models/Fall_Detection/1.0.0/       # ❌ Uppercase letters
         └────┬────────┘
              └── SKIPPED: Invalid model_id pattern
```

#### Example B: Invalid version

```
ai/models/fall_detection/v1.0/        # ❌ 'v' prefix, missing patch
                         └─┬─┘
                           └── SKIPPED: Invalid version pattern
```

#### Example C: Missing required file

```
ai/models/fall_detection/1.0.0/
├── model.yaml
└── weights/
    └── model.onnx
# ❌ Missing inference.py → INVALID
```

#### Example D: Name mismatch

```
ai/models/fall_detection/1.0.0/
└── model.yaml:
      model_id: "fall_detector"       # ❌ Doesn't match "fall_detection"
      version: "1.0.0"
# → INVALID: model_id mismatch
```

#### Example E: External symlink

```
ai/models/fall_detection/1.0.0/
└── weights -> /mnt/shared/weights    # ❌ External symlink
# → INVALID: Forbidden symlink
```

#### Example F: Forbidden content

```
ai/models/fall_detection/1.0.0/
├── model.yaml
├── weights/
├── inference.py
└── setup.sh                          # ❌ Shell script
# → INVALID: Forbidden file type
```

---

### 9.5 Complete Multi-Model Deployment

```
ai/
└── models/
    ├── fall_detection/
    │   ├── 1.0.0/
    │   │   ├── model.yaml
    │   │   ├── weights/
    │   │   │   └── model.onnx
    │   │   ├── inference.py
    │   │   ├── preprocessing.py
    │   │   └── postprocessing.py
    │   └── 1.1.0/
    │       ├── model.yaml
    │       ├── weights/
    │       │   └── model.onnx
    │       └── inference.py
    │
    ├── helmet_detection/
    │   └── 0.1.0/
    │       ├── model.yaml
    │       ├── weights/
    │       │   └── yolov8_helmet.pt
    │       └── inference.py
    │
    ├── fire_detection/
    │   ├── 1.0.0/
    │   │   └── ...
    │   └── 2.0.0-beta/
    │       └── ...
    │
    └── ppe_compliance/
        └── 1.0.0/
            └── ...
```

---

## 10. Rationale Summary

### 10.1 Why These Rules Exist

| Rule | Rationale |
|------|-----------|
| Lowercase model_id | Filesystem case-insensitivity on some systems; URL safety |
| No hyphens in model_id | Underscore is valid Python identifier; hyphen is not |
| Strict SemVer | Deterministic version comparison and ordering |
| Directory-contract match | Prevents silent configuration drift |
| No external symlinks | Security; deployment portability |
| Forbidden executables | Security; prevent arbitrary code |
| Required weights/ | Ensures models are self-contained |
| Required inference.py | Single entry point for execution |
| Independent versions | Safe upgrades; zero-disruption rollback |
| No shared files | Isolation; independent testing |

### 10.2 Design Trade-offs

| Decision | Alternative | Why Chosen |
|----------|-------------|------------|
| Strict naming patterns | Flexible naming | Automated validation; consistency |
| model.yaml required | Infer from code | Explicit contracts; no magic |
| No "latest" alias | Support "latest" | Deterministic behavior; reproducibility |
| Separate version directories | In-place updates | Safe rollback; no conflicts |
| Copy vs symlink | Allow symlinks | Portability; isolation |

### 10.3 Future Extensibility

This standard supports future enhancements without breaking changes:

| Future Feature | How Supported |
|----------------|---------------|
| New optional files | Add to optional list; existing models unchanged |
| New model capabilities | Add to model.yaml schema; backward compatible |
| Model signing | Add `.signature` file; existing models unsigned but valid |
| Model compression | Add compressed format support; existing formats unchanged |
| Model federation | Add `.registry/` directory; existing models unchanged |

---

## Appendix A: Quick Reference Card

### Directory Structure

```
ai/models/<model_id>/<version>/
├── model.yaml          # REQUIRED
├── weights/            # REQUIRED
├── inference.py        # REQUIRED
├── preprocessing.py    # optional
├── postprocessing.py   # optional
├── requirements.txt    # optional
├── config.yaml         # optional
└── README.md           # optional
```

### Naming Patterns

| Element | Pattern |
|---------|---------|
| model_id | `^[a-z][a-z0-9_]{2,63}$` |
| version | `^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$` |

### Validation Checklist

1. ✅ model_id matches directory name
2. ✅ version matches directory name
3. ✅ model.yaml exists and is valid
4. ✅ weights/ directory exists
5. ✅ inference.py exists with infer()
6. ✅ No external symlinks
7. ✅ No forbidden files

---

## Appendix B: Glossary

| Term | Definition |
|------|------------|
| **Model Root** | `ai/models/` - directory scanned for models |
| **Model Directory** | `ai/models/<model_id>/` - contains all versions of a model |
| **Version Directory** | `ai/models/<model_id>/<version>/` - one version's files |
| **Model Contract** | `model.yaml` file declaring model properties |
| **SemVer** | Semantic Versioning (MAJOR.MINOR.PATCH) |
| **Pre-release** | Version suffix indicating non-stable release (e.g., `-beta`) |

---

**End of AI Model Directory Standard**

*This specification was produced by the AI Platform Engineer Agent.*

*Document Version: 1.0*
*Last Updated: January 2026*