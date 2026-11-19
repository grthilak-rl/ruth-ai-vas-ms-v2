# geo_fencing → geofence (model store), and retiring the built-ins

**Status:** signed off and **deployed 2026-11-19, 18:04–18:10 IST** (see
"Deploy record" at the end).

This is a migration, not a calibration. `geofence` runs the built-in
geo_fencing behaviour on the **same weights** (the stock Ultralytics
`yolov8n.pt`, the built-in's own file), so the replay is expected to match
exactly, end to end, and it does.

The same deploy retires every remaining built-in model, so that all
inference runs in the model store runtime.

## Decisions (2026-11-19)

- Plugin settings `zone_anchor`, `zone_test`, `zone_point_test`, and
  `predict.iou` / `predict.classes`: all optional and off by default.
- Model ID `geofence`, weights `yolov8n.pt`, severity: intrusion high, exit
  medium.
- Zones are saved **normalised** (0–1 of the image width and height,
  `coords: "normalized"`). The plugin scales them to each frame, so snapshot
  and inference resolutions cannot misplace a zone. No existing polygons
  needed converting: none exist.
- Zone setup in the frontend is keyed on "the model has zone rules", not on
  the model ID. The BL-6 editor fixes are folded in.
- Retire `ppe_detection`, `geo_fencing`, `tank_overflow_monitoring` and
  `chane_tank_monitor`: move them to `ai/models/.disabled/` and keep the
  files. Move the `chane_tank_overflow` script to `archive/`. Remove the
  unified runtime container after one release (BL-36).

## Usage before the switch (checked 2026-11-19)

| Built-in | Violations | Sessions | Intents |
|---|---|---|---|
| geo_fencing | 0 | 0 | 0 (and no saved polygons anywhere) |
| ppe_detection | 54,462, last 2026-10-04 (IOCL era) | 54, last 2026-10-04 | 0 |
| tank_overflow_monitoring | 0 | 0 | 0 |
| chane_tank_monitor | 0 | 0 | 0 |

Nothing needs switching. Past rows keep their model IDs, which stay
reserved.

## What changed

| Area | Change |
|---|---|
| Store plugin `ai/store_plugin/inference.py` | Zone rules can test the box **centre** (`zone_anchor`), fire when **outside** a zone (`zone_test: "outside"`, for "allowed" zones), and use the built-in's exact polygon test (`zone_point_test: "legacy_ray_cast"`). Zones may be normalised (`coords: "normalized"`). Detect models can set NMS IoU and a class filter (`predict`). All off by default: existing models are byte-identical (below). |
| Installer | Validates the new rule settings (only with `requires_zone`) and `predict` (detect models only; classes must exist and must include every class a rule needs). |
| Manifest `manifests/geofence.json` | New. Persons only, IoU 0.5, imgsz 640. `intrusion`: `restricted` zones, centre inside, `zone_intrusion`, high. `exit`: `allowed` zones, centre outside, `zone_exit`, medium. Both use the legacy polygon test and `min_confidence` 0.7 (the gate the built-in was recorded at). |
| Backend | `/models/status` reports each store model's `zone_types`. New flag **`UNIFIED_RUNTIME_IN_USE`** (default true): set to false in compose when the built-ins are retired, and System Health shows the unified runtime as **disabled** (left out of overall health). With the flag on, a runtime with no models is still unhealthy; it is never inferred. It is deliberately not named like the existing `UNIFIED_RUNTIME_ENABLE`, a routing switch that would send built-in models to legacy containers. `POST /api/v1/ai/inference` already routes every installed store model to the store runtime, with its config (zones); now tested for PPE models and geofence. |
| Frontend: bookmark monitoring | Runs any store model (PPE models, geofence with its zones), drawn with the live store overlay plus the zones. Before, it could run fall, the built-in PPE and the two tank models, and offered geo_fencing without running it. After retirement it keeps PPE (through the store PPE models) and gains geofence. |
| Frontend | The picker gives any model with zone types a setup button, and enabling it opens the zone editor first. The editor offers the model's zone types and saves normalised zones for store models (pixels for the built-in, so a rollback still works). Live tiles draw the zones of every running model. BL-6: a complete zone is drawn as its polygon; a drag ends when it leaves the image; a saved zone reopens in the matching mode; a mode switch keeps a complete zone; the saved config is read once per opening. |

**Behaviour differences from the built-in:**
- **Severity** is the rule's (intrusion high, exit medium) instead of being
  computed per frame from person count and confidence. Past rows keep what
  they recorded.
- **Live overlay:** shows people at 0.7 or above (was 0.3 or above).
  Violations are unchanged.
- **Not read:** the per-camera `conf_threshold` override and the old
  `tank_corners` / `geofence_points` keys. None are in use.
- **Mixed zone types:** with both restricted and allowed zones on one camera,
  the built-in gives each person one zone across both types; the store
  model fires one rule per type. The editor saves a single zone, so the UI
  can't reach this.

## Test summary

| Suite | Result | New |
|---|---|---|
| Store plugin and installer | **169 passed** | `test_geofence.py` (27); geofence added to the shipped-manifest checks |
| Backend unit | **853 passed** | `test_geofence_store_model.py` (zone types, labels, the `UNIFIED_RUNTIME_IN_USE` flag both ways); `test_ai_inference_routing.py` (hard_hat, gloves_2, geofence with zones); geofence added to the 0.7-gate check |
| Frontend vitest | **344 passed** | `zoneGeometry.test.ts` (12); `storeDetection.test.ts` (6); `pickerState` zone-model case |
| Frontend `tsc -b`, eslint (changed files) | clean | |

The full `make test` summary is in the final report.

## Parity

**Rule, the same detections** (`test_geofence.py`, against the built-in's own
file):
- **Polygon test:** the store's `legacy_ray_cast` against the built-in's
  `_point_in_polygon` on 100,000 points, many exactly on vertices and edges:
  0 mismatches.
- **Frame decision:** with the backend's 0.7 gate, 4 layouts × 5,000 random
  frames (one/two restricted, one/two allowed zones), persons either side of
  0.7, many on boundaries: 0 mismatches.
- **Zone IDs:** the zone_id of each in-zone person (what the backend's
  new-zone alert keys on) is identical.
- **Normalised zones:** they decide as their pixel equivalents on 3 frame
  sizes.
- **The test can fail:** it does when the anchor or the polygon test is
  changed (534 and 391 of 3,000 differ).

**Replay on real frames** (`tools/geofence_parity_replay.py`):
- 519 evidence frames: 119 demo cameras, 400 HPCL across 13 cameras; 280
  with people at 0.7 or above.
- 4 zone layouts each: restricted lower half, restricted concave L,
  allowed centre, two restricted.
- The built-in got pixel zones; the store plugin got the same zones
  normalised.

| | Result |
|---|---|
| Recorded decision identical | **2,076 / 2,076** (530 fires each, 0 type flips) |
| Zone IDs identical | 2,076 / 2,076 |
| Person boxes at 0.7 or above identical | 2,076 / 2,076 (at the plugin's 0.1 px / 4-decimal precision) |
| Shift from the model change | **0** (same weights) |
| Store plugin latency, RTX 3090 | median 10.0 ms, p95 15.4 ms |

One rounding edge: the plugin rounds confidence to 4 decimals before the
0.7 test, as for every store model, so a raw 0.69995–0.69999 detection
passes where the built-in's would not. No frame hit it.

**Existing models under the new plugin:** all 11 installed models, the
live plugin against the new one, on the same 519 frames: **5,709 / 5,709
byte-identical** (640 violations).

## Deploy runbook (after sign-off)

From `/home/project/vas-ruthai-deploy`; repo = `$R`
(`/home/project/ruth-ai-vas-ms-v2`).

### 0. Backups

- Ruth DB dump.
- `tar` of `/mnt/storage/ruth-models/enabled` and of `$R/ai/models`.
- Tag the backend and frontend images `pre-geofence-<ts>`.
- Copy the compose file.

### 1. Backend and frontend first

```bash
docker compose build ruth-ai-backend ruth-ai-frontend
docker compose up -d ruth-ai-backend ruth-ai-frontend
```

Nothing changes visibly yet: no installed store model has zone types, and
the new health flag defaults to "in use".

### 2. Store draft and weights (normal store upload)

- Create the draft with model ID **`geofence`**, display name "Geo-Fencing".
- Upload `$R/ai/models/geo_fencing/1.0.0/weights/yolov8n.pt`. It is the
  built-in's own file, so no download is needed; its sha256 is
  `f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36`. The
  store checks it on completion.

### 3. Install the full set (BL-31: the installer still replaces the set)

```bash
M=$R/ai/store_plugin/manifests
SET="$M/gloves.json $M/gloves_2.json $M/goggles.json $M/goggles_2.json $M/goggles_3.json \
     $M/hard_hat.json $M/harness.json $M/harness_2.json $M/no_goggles.json $M/safety_vest.json \
     $M/fall_pose.json $M/geofence.json"
python3 $R/ai/store_plugin/install_enabled.py --store-root /mnt/storage/ruth-models --check $SET
python3 $R/ai/store_plugin/install_enabled.py --store-root /mnt/storage/ruth-models $SET
docker compose restart model-store-runtime
```

Verify:
- 12/12 models ready on `cuda:0`.
- The PPE 38-frame probe is identical before and after.
- fall_pose on 2026-11-19's 10 violation frames: 3 fire, 7 don't.
- geofence on a frame with a drawn zone fires.

### 4. Retire the built-ins

```bash
cd $R
mv ai/models/geo_fencing ai/models/ppe_detection ai/models/tank_overflow_monitoring \
   ai/models/chane_tank_monitor ai/models/.disabled/
mkdir -p archive/ai-models && mv ai/models/chane_tank_overflow archive/ai-models/
cd /home/project/vas-ruthai-deploy && docker compose restart unified-ai-runtime
# compose: ruth-ai-backend environment gets   UNIFIED_RUNTIME_IN_USE: "false"
docker compose up -d ruth-ai-backend      # recreate to pick up the flag
```

Verify:
- Unified runtime `/capabilities`: 0 models, container healthy.
- Backend System Health: AI runtime **disabled**, overall healthy, model
  store runtime healthy.
- Live PPE cameras keep inferring.
- The picker shows "Geo-Fencing" (store) with a setup button and no
  built-ins.

### Rollback

- **Built-ins:** move the directories back from `ai/models/.disabled/` (and
  `archive/ai-models/chane_tank_overflow` back to `ai/models/`), restart
  `unified-ai-runtime`, remove `UNIFIED_RUNTIME_IN_USE: "false"` from compose
  and `up -d ruth-ai-backend`.
- **Store:** put `state/enabled-previous-<ts>` back as `enabled/` and
  restart `model-store-runtime`.
- **Backend / frontend:** re-tag the `pre-geofence-<ts>` images and run
  `up -d`.

## Deploy record (2026-11-19)

| Step | Result |
|---|---|
| Backups | DB `/mnt/storage/ruth-backups/ruth_ai-pre-geofence-20261119-180436.dump` (22 tables). Store tree, `ai/models` and the compose file in `/mnt/storage/ruth-backups/pre-geofence-20261119-180436/`. Images tagged `pre-geofence-20261119-180436`. |
| 1. Backend + frontend | Rebuilt, healthy. System Health unchanged (flag at its default). |
| 2. Store upload | Draft `geofence` ("Geo-Fencing"); `yolov8n.pt` uploaded, sha256 `f59b3d83…3b36` checked by the store and again on disk. |
| 3. Install | Installed manifests matched the repo; `--check` ok for 12; installed 12 (previous tree `state/enabled-previous-20261119T180658`). **12/12 ready on `cuda:0`**, 0 errors. |
| Verify | PPE 38-frame probe: **380/380 identical**. fall_pose on 2026-11-19's 10 frames: **3 fire / 7 don't**, matching the hand labels. geofence with a restricted lower-half zone: fires `zone_intrusion` (high) on 9 of 38 frames; without zones: 0. Bookmark path (`POST /api/v1/ai/inference`): gloves_2 and hard_hat return store results with violations; geofence with zones fires, without zones doesn't. |
| 4. Retire built-ins | No intents or live sessions used them. Moved to `ai/models/.disabled/`; `chane_tank_overflow` to `archive/ai-models/`; compose sets `UNIFIED_RUNTIME_IN_USE: "false"` on the backend. Unified runtime: 0 models, container healthy. |
| System Health | **Overall healthy.** AI runtime **disabled** ("not in use"), model store runtime healthy. `/models/status`: the 12 store models only. 3 live sessions inferring. |

Tests after the deploy: store plugin 169 passed; `make test` all green
(backend unit 853, multi_model 18, stream_sessions 5, schema 10, projects
83, model_store 35, frontend vitest 344, lint 0 errors).
`multi_model::test_g8_publish_before_counter_and_one_counter_write_per_tick`
is intermittently flaky. It predates this release: 3 failures in 12 runs on
the pre-change code, 1 in 12 on the new code (BL-37).
