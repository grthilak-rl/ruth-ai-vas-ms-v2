# fall_detection → fall_pose (model store): test summary and deploy runbook

**Status:** signed off and **deployed 2026-11-19** (see "Deploy record" at
the end).

This is a migration, not a recalibration. `fall_pose` runs the built-in fall
heuristic unchanged, with its thresholds kept in the old 640×640 coordinate
space. The only intended change is the model: YOLOv7-w6-pose →
Ultralytics yolo11l-pose. Recalibration is BL-1.

## What changed

| Area | Change |
|---|---|
| Store plugin `ai/store_plugin/inference.py` | `task: "pose"`: keypoints on each object, the `pose_fall` rule type, person floor and NMS IoU from the manifest. Detect models are untouched (golden test, plus real-weights check below). |
| Installer `ai/store_plugin/install_enabled.py` | Accepts `task: "pose"`, validates the `pose` / `pose_fall` blocks and pose rules, and requires the weights' own task to match the manifest's. |
| Manifest `ai/store_plugin/manifests/fall_pose.json` | New. `fall_detected` is critical and `possible_fall` high, both gated at `min_confidence 0.7`. Person floor 0.25, IoU 0.65 (the old NMS settings). Weights `yolo11l-pose.pt`. |
| Backend | Default model `fall_detection` → `fall_pose` (start-inference request, `StreamService.start_stream`, inference response schema). `POST /api/v1/ai/inference` routes store models to the store runtime. |
| Frontend | Bookmark monitoring runs and draws `fall_pose`, skeleton included, by mapping its frame-pixel `objects` to the old 640 space. The grid flag recognises `fall_pose`. Live tiles use the generic store overlay (boxes only; the skeleton is BL-29). |
| Built-in `fall_detection` | Not changed. To be moved to `ai/models/.disabled/` at deploy (discovery skips dot-directories, so the files are kept). Removal is BL-30. |
| Backlog | BL-1 and BL-3 updated; BL-29 (skeleton overlay), BL-30 (remove the built-in), BL-31 (additive installer) and BL-32 (AGPL licensing) added. |

**No data migration.** No camera intent and no live session uses
`fall_detection` (checked 2026-11-19: 16 intents, all store PPE models).
Past rows are unaffected:
- Violation type stays `fall_detected` (with `possible_fall` as the detail).
- Labels stay "Fall Detected" / "Possible fall".
- Past rows with NULL severity still resolve to critical / high.

The backend tests pin all of this.

**Behaviour differences you should know about:**
- A `fall_pose` violation stores only the person(s) the rule fired on. The
  built-in stored every detected person.
- Stored boxes are in frame pixels, which is correct. Built-in boxes were in
  640 space (BL-3).
- `possible_fall` is recorded as **high**; the built-in reported critical
  (decided).

## Test summary

| Suite | Result | New / changed |
|---|---|---|
| Store plugin + installer (`ai/store_plugin/tests`) | **102 passed** | `test_pose_fall.py` (33 new); `fall_pose` added to 3 shipped-manifest checks in `test_store_plugin.py` |
| Backend unit + multi_model + model_store + schema + projects + stream_sessions | **809 passed, 0 failed, 152 skipped** | `test_fall_pose_manifest.py` (6), `test_ai_inference_routing.py` (5), plus 3 updated tests (below) |
| Frontend vitest | **325 passed** (317 before) | `services/__tests__/fallDetection.test.ts` (8) |
| Frontend `tsc -b`, eslint (changed files) | clean | |

Backend notes:
- The 152 skips are the DB-backed suites. They also skip on the baseline;
  this machine has no test database.
- `test_health_service::test_check_all_runs_concurrently` is timing-based
  (elapsed < 0.3 s). It failed in 2 of 5 runs, both before any backend
  change, and passed in the rest.
- The backend runs were in a throwaway container from the backend image,
  with the repo mounted read-only and `PYTHONPATH` pinned to the repo.
- Updated tests:
  - `test_stream_service`: the default model is now `fall_pose`.
  - `test_violation_threshold`: `fall_pose` added; it keeps the 0.7 gate.
  - `test_violation_incidents`: the migration-vs-manifests check now
    accepts new manifest types, provided types that moved from a built-in
    keep the built-in's severity. Before, it required the manifests to equal
    the 2026-10-19 migration's frozen table, so any new type failed it.

Key tests:
- **Rule parity:** the store rule against the built-in
  `_analyze_pose_for_fall`, imported from the built-in model's own file.
  - 50,000 random keypoint sets, plus constructed sets that sit exactly on
    every threshold (strict `<` / `>`, visibility 0.3, missing-keypoint
    fallbacks).
  - Frame-level parity, including the backend's 0.7 gate, on 4 frame sizes.
  - Result: 0 mismatches.
- **Detect path unchanged:** the existing byte-identical golden test passes.
- **Installer:** reads real weights safely and accepts both yolo11 pose
  checkpoints (`task: pose`, classes `{0: person}`); rejects a mismatch
  between the weights' task and the manifest's.

## Parity replay on real frames (2026-11-19)

Both models were run on the same frames in a throwaway container: the
runtime image, no network, read-only mounts. Nothing live was touched.
Harness: `ai/store_plugin/tools/fall_parity_replay.py`.

**Sample: 500 frames.**
- **85**: every fall snapshot that still has a file. VAS keeps snapshots
  only back to 2026-10-04; fall violations ran 2026-07-29 → 10-04.
- **415**: random store-era evidence frames from 13 plant cameras, all with
  people in them.

### 1. Rule parity: store rule on the old model's own keypoints

**0 mismatches out of 500** (61 recorded fires: 37 `fall_detected` critical,
24 `possible_fall` high).

### 2. Model change alone: old model vs fall_pose, same rule, same frames

Decision compared: the recorded type (none / possible_fall / fall_detected)
after the 0.7 gate.

| | yolo11l-pose (chosen) | yolo11x-pose |
|---|---|---|
| Same decision | **439 / 500 (87.8 %)** | 438 / 500 (87.6 %) |
| Same fire / no-fire | 444 / 500 (88.8 %) | 445 / 500 (89.0 %) |
| Recorded fires (old: 61) | 77 | 80 |
| Persons found (old: 711) | 977 | 978 |
| Median / p95 latency, RTX 3090 (old: 26.4 / 41.6 ms) | 24.9 / 35.8 ms | 27.5 / 40.6 ms |
| Peak GPU memory reserved (old: 928 MB) | 436 MB | 562 MB |

yolo11l-pose, old (rows) vs new (columns), all 500 frames:

| old \ new | none | possible_fall | fall_detected |
|---|---|---|---|
| none | 403 | 22 | 14 |
| possible_fall | 9 | 12 | 3 |
| fall_detected | 11 | 2 | 24 |

**What drives the shift:**
- The new model finds **37 % more people**. In 33 of the 36 frames where
  only the new model fired, it had found extra people.
- The firing persons are small: median height 0.25 of the frame, against
  0.48 for all persons.
- The inherited size-dependent rule flags small people (BL-1). A spot check
  found a new-only "fall" on two mounted CCTV cameras detected as people.
- So the extra fires are the known false-positive mode with more inputs,
  not a change in the rule.

**Caveats:**
- Only 9 of the 85 fall snapshots re-fire on the old model itself. Those
  snapshots were requested from VAS after the fact, so they are not the
  frames that were scored.
- The history contains essentially no real falls, so this measures parity
  and false positives, **not recall**. Recall, with staged falls, is part
  of BL-1.

### 3. Detect models under the new plugin

`hard_hat`, with its real weights, run with the plugin before and after
this change on the 415 frames: **415/415 byte-identical results** (45 frames
with objects, 14 violations).

On install, every store model gets the new plugin copy, so this is the
check that matters for them.

## Deploy runbook (after sign-off)

From `/home/project/vas-ruthai-deploy` unless noted; repo = `$R`
(`/home/project/ruth-ai-vas-ms-v2`).

### 1. Store draft and weights (normal store upload)

The upload flow verifies the sha256 on completion and records it with the
file. On 2026-11-19 the weights were stored at
`/mnt/storage/ruth-models/drafts/e3d7b84d-bba0-49b6-97a9-01ad1e6363f2/weights/yolo11l-pose.pt`.

```bash
# Weights (Ultralytics v8.3.0 release asset); verify before uploading.
curl -fL -o yolo11l-pose.pt https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11l-pose.pt
sha256sum yolo11l-pose.pt   # 61921abe1f2ed930bf28328a16b3162278cdb239a1e8280b6ac827119f13cee0
```

- Create the draft with **model_id `fall_pose`** and display name "Fall
  Detection". `POST /api/v1/admin/model-store/models` with
  `{"display_name": "Fall Detection", "model_id": "fall_pose"}` (admin auth).
- Do not let it auto-generate an ID: "Fall Detection" would generate
  `fall_detection_2`, because `fall_detection` is reserved. If you create
  it in the UI, change the ID before the first Apply (`PATCH`, `model_id`).
- Upload `yolo11l-pose.pt` to that draft through the normal upload flow.

### 2. Install: validate first, then the full set

The installer rebuilds the **whole** `enabled/` tree from the manifests it
is given, so pass every installed model plus `fall_pose`:

```bash
M=$R/ai/store_plugin/manifests
SET="$M/gloves.json $M/gloves_2.json $M/goggles.json $M/goggles_2.json $M/goggles_3.json \
     $M/hard_hat.json $M/harness.json $M/harness_2.json $M/no_goggles.json $M/safety_vest.json \
     $M/fall_pose.json"
sudo python3 $R/ai/store_plugin/install_enabled.py --store-root /mnt/storage/ruth-models --check $SET
sudo python3 $R/ai/store_plugin/install_enabled.py --store-root /mnt/storage/ruth-models $SET
docker compose restart model-store-runtime
```

Before running it, check that the installed set still matches this list:
`ls /mnt/storage/ruth-models/enabled` (10 models on 2026-11-19).

### 3. Disable the built-in (files kept)

```bash
mkdir -p $R/ai/models/.disabled && mv $R/ai/models/fall_detection $R/ai/models/.disabled/
docker compose restart unified-ai-runtime
```

Verified on a scratch copy with the runtime's own discovery: every model is
found except `fall_detection` (the control run finds it).

### 4. Backend and frontend

```bash
docker compose build ruth-ai-backend ruth-ai-frontend
docker compose up -d ruth-ai-backend ruth-ai-frontend
```

### 5. Verify

- Store runtime `/capabilities`: `fall_pose` ready, plus the 10 PPE models ready.
- Unified runtime `/capabilities`: no `fall_detection`; the other 4 models
  ready.
- Backend `/api/v1/models/status`: `fall_pose` with `source: "store"`,
  healthy.
- `POST /api/v1/ai/inference` with `model_id: fall_pose` and a JPEG
  returns `metadata.source == "store"` and `metadata.task == "pose"`.
- PPE violations keep arriving on the active cameras, at the usual rate.
- GPU: the unified runtime frees the fall model, about 0.6–0.9 GB
  (peak 928 MB reserved offline); the store runtime adds about 0.4 GB.

### Rollback

- **Store:** move the previous tree back into place and restart
  `model-store-runtime`. The installer prints its path:
  `/mnt/storage/ruth-models/state/enabled-previous-<ts>`.
- **Built-in:** `mv $R/ai/models/.disabled/fall_detection $R/ai/models/`
  and restart `unified-ai-runtime`.
- **Backend / frontend:** rebuild from the previous code, or keep the
  previous images tagged before step 4.

The bookmark-monitoring fall path keeps working against the built-in: it
accepts either fall model ID.

## Deploy record (2026-11-19, 12:28–12:41 IST)

All times IST. Checks were run from the host against the live services.

| Step | Result |
|---|---|
| Backups | Ruth DB: `/mnt/storage/ruth-backups/ruth_ai-pre-fall-pose-20261119-122812.dump` (TOC checked, 22 tables). Store `enabled/` tree, built-in `fall_detection` and compose file: `/mnt/storage/ruth-backups/pre-fall-pose-20261119-122812/`. Images tagged `vas-ruthai-deploy-ruth-ai-{backend,frontend}:pre-fall-pose-20261119-122812`. |
| Pre-checks | Installed set = the 10 repo manifests, each `store_manifest.json` identical to the repo copy. Installed plugin = the pre-change plugin (md5 identical on all 10). |
| 1. Store draft + weights | Draft `fall_pose` ("Fall Detection") created with an explicit ID. `yolo11l-pose.pt` uploaded through the chunked store upload with sha256 `61921abe…cee0`, verified by the store on completion and again on disk. |
| 2. Install | `--check` ok for all 11. Installed 11; previous tree at `/mnt/storage/ruth-models/state/enabled-previous-20261119T123008`. Store runtime: **11/11 ready, all loaded on `cuda:0`**. |
| PPE unchanged | Same 38 frames sent to the 10 PPE models before and after: **380/380 responses identical** (timing fields excluded; 38 of them violations). |
| fall_pose live | Same 38 frames: decisions match the offline replay **38/38**. A firing frame returns `fall_detected`, critical, 0.8, `task: pose`, 17 keypoints. |
| 3. Disable built-in | Moved to `ai/models/.disabled/fall_detection`. Unified runtime: **4/4 ready on `cuda:0`** (chane_tank_monitor, geo_fencing, ppe_detection, tank_overflow_monitoring), each answering an inference without error. `fall_detection` returns 404 "not found or not ready". No errors in the logs. |
| 4. Backend + frontend | Rebuilt and recreated, both healthy. `/api/v1/models/status`: `fall_pose`, `source: store`, healthy. `POST /api/v1/ai/inference` with `fall_pose` → `source: store`, `task: pose`. Live PPE inference resumed (3 live sessions). |
| Demo camera | `fall_pose` added to DEMO-CAMERA (with gloves_2) through `POST /devices/{id}/models` for 4.5 min, then removed with `DELETE`. 377 live inferences, 0 errors, 0 violations (the scene was mostly empty). In-runtime latency was median 62 ms and p95 84 ms, alongside gloves_2 on a shared GPU; the offline replay measured 25 ms. The intent is back to `gloves_2` only. |

Not measured cleanly: the GPU memory freed. The total went 6989 → 6941
MiB across both restarts, but both runtimes' allocator caches were reset
at the same time.

Backlog renumbered: BL-27/BL-28 were already taken in the shared sequence,
so this work uses BL-29 to BL-32.

### Post-deploy test summary (`make test`, 2026-11-19)

`make test` runs the DB suites against a throwaway Postgres, so the 152
DB-backed tests that skipped earlier ran this time.

| Suite | Result |
|---|---|
| backend unit | 810 passed |
| backend multi_model | 18 passed |
| backend stream_sessions | 5 passed |
| backend schema | 10 passed |
| backend projects | 83 passed |
| backend model_store | 35 passed |
| frontend vitest | 325 passed |
| frontend lint | 0 errors, 3 warnings |
| backend integration | not run: legacy suite, hard-coded localhost DB (BL-18) |
| store plugin + installer (`pytest ai/store_plugin/tests`, not in `make test`) | 102 passed, 0 skipped: the parity tests ran against the built-in in `.disabled/` |

The first `make test` run failed one test:
`multi_model::test_g10_fastest_first_by_measured_latency_not_entry_order`,
a wall-clock assertion that took 30.6 ms against a 30 ms budget. It ran
while the demo camera load was on. A full re-run was all green. The test
uses fake runtimes and does not touch the fall model.
