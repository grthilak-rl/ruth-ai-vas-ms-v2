# Model Store — Step 5 proposal

Step 5 in the landing order: **auto-integration** — store runtime, generic
plugin, Apply, enable/disable, live load status, routing, and store models in
the camera picker.

**Goal of this step:** on the demo camera, tick **Hard Hat**, **Safety Vest**
and **Gloves** next to **Fall Detection** in the camera picker; all four run
in the camera's one session and store models raise PPE violations.

Status: proposal (2026-10-04). Nothing here is implemented.

**Change of plan (agreed 2026-10-04).** Store design §10 kept uploaded models
out of `/api/v1/models/status`, deploying them only from the Model Management
page (Step 6), with "store models in the existing picker" left for later.
Now enabled store models appear in the camera picker like built-in models.
Consequences for this step: store entries are appended to `/models/status`
with built-in entries unchanged (2.7); the routing wrapper moves from Step 6
into Step 5 (2.6); zone-required rules stay blocked in the picker and the API
until zones exist (2.3, 2.7); store models draw no live overlay until Step 6
(3).

---

## 1. Starting point (verified 2026-10-04)

**Uploaded models (Step 2 store, all `state = draft`):**

| model_id | File | Size | Ultralytics | Task | Base | Train imgsz | Classes |
|---|---|---|---|---|---|---|---|
| `hard_hat` | `besthardhat.pt` | 6.3 MB | 8.3.231 | detect | yolov8n | 1280 | `0: hardhat`, `1: no-hardhat` |
| `safety_vest` | `bestvest.pt` | 52 MB | 8.3.196 | detect | yolov8m | 1280 | `0: no-vest`, `1: vest` |
| `gloves` | `bestgloves.pt` | 52 MB | 8.3.196 | detect | yolov8m | 1280 | `0: gloves`, `1: no-gloves` |

- Read with a restricted unpickler that imports and executes nothing from the
  files. All three are `ultralytics.nn.tasks.DetectionModel`.
- Note the vest model's reversed class order (0 = `no-vest`).
- None matches any built-in `ppe_detection` weight by sha256; they are new
  models, not copies.
- The runtime image ships ultralytics 8.4.115; 8.3.x checkpoints load in it.
- The ids are valid for the runtime (`^[a-z][a-z0-9_]{2,63}$`) and don't
  collide with built-ins (`RESERVED_MODEL_IDS`).

**Facts that shape the design:**
- The backend assumes **one runtime URL** for all inference
  (`integrations/unified_runtime/config.py:16`, `core/lifespan.py:268-275`,
  `router.py:71/200/272`). A store id sent today goes to the built-in runtime
  and gets a 404.
- `POST /devices/{id}/models` validates nothing about the model id, so store
  ids are already accepted; only routing is missing.
- The multi-model loop fetches **one frame per tick** and passes it to each
  model (`submit_inference_with_frame`); the frame is runtime-agnostic.
- Pacing (`InferenceBudget`, keyed by model id, EWMA latency) and
  `recommended_fps` (runtime registration push) are runtime-agnostic.
- Violation writing has no per-model branches: any model's result follows the
  generic rules (`violation_detected`, `confidence ≥ threshold`, enter/leave
  dedup).
- `missing_hardhat` and `missing_vest` are in `VIOLATION_TYPE_MAP`;
  `missing_gloves` is not (it would land as `ppe_violation` with
  `type_detail='missing_gloves'` and a warning per violation).
- The runtime serves one inference at a time per process (BL-5). A second
  runtime is a second process: store models **don't queue behind** built-in
  PPE, but they do queue behind each other.
- Store files are owned by uid 1000 with modes 750/640; the runtime image runs
  as `ruth` (uid 999) and **could not read them**.

---

## 2. Design

### 2.1 Store runtime container: `model-store-runtime`

Same image as `unified-ai-runtime` (`ruth-ai-unified-runtime:2026.10-pinned`),
no code changes to the runtime. New compose service in
`vas-ruthai-deploy/docker-compose.yml`:

```yaml
model-store-runtime:
  image: ruth-ai-unified-runtime:2026.10-pinned      # same pinned image, no build
  container_name: ruth-ai-model-store-runtime
  restart: unless-stopped
  user: "1000:1000"                                  # store files are uid 1000, 750/640
  # no host port: reached only by the backend on ruth-ai-internal
  volumes:
    - /mnt/storage/ruth-models/enabled:/store-models:ro
  environment:
    - ENVIRONMENT=production
    - LOG_LEVEL=info
    - MODELS_ROOT=/store-models
    - RUNTIME_ID=model-store-runtime                 # fixed: no stale random ids
    - SERVER_HOST=0.0.0.0
    - SERVER_PORT=8000
    - BACKEND_URL=http://ruth-ai-vas-backend:8080
    - BACKEND_INTEGRATION_ENABLED=true
    - BACKEND_HEALTH_PUSH_INTERVAL_SECONDS=30
    - YOLO_AUTOINSTALL=False
    - YOLO_CONFIG_DIR=/tmp/ultralytics               # uid 1000 has no home in the image
  healthcheck:                                       # /health is 200 even with 0 models
    test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 90s
  networks: [ruth-ai-internal]
  deploy:
    resources:
      limits: {memory: 4G}
      reservations:
        memory: 1G
        devices: [{driver: nvidia, device_ids: ["0"], capabilities: [gpu]}]
```

- An Apply restart affects only cameras running store models.
- A crashing or malicious `.pt` takes down only this container.
- GPU memory booking is per process (each instance books against the whole
  card); with ~22 GB free on GPU 0 today and three detectors (~1–2 GB with
  the CUDA context), this is comfortable. Manifests set
  `limits.max_memory_mb` honestly so the runtime's own booking is meaningful.
- **Residual risk (unchanged from the design):** loading an uploaded `.pt`
  unpickles it inside this container, which has GPU and backend-network
  access. Acceptable only behind the admin gate (Step 1, done).

### 2.2 Enabled layout, generated by Apply

```
/mnt/storage/ruth-models/enabled/
  hard_hat/1.0.0/
    model.yaml              # generated from the manifest (runtime contract)
    store_manifest.json     # the manifest the plugin reads
    inference.py            # copy of the generic plugin
    weights/besthardhat.pt  # hardlink to drafts/<pk>/weights/ (same filesystem)
  safety_vest/1.0.0/...
  gloves/1.0.0/...
```

- **Real files only.** The runtime skips symlinked dirs and rejects files
  that symlink outside the version dir; weights are hardlinked (no copy), the
  plugin is copied.
- Built atomically: Apply writes `staging/apply-<ts>/`, then renames over
  `enabled/` (keeping the previous tree as `state/previous/` for rollback).
- Version is `1.0.0` for every store model in Step 5 (the store has no
  versions; a manifest edit + Apply replaces it).

### 2.3 Generic plugin: `ai/store_plugin/inference.py` (new)

One self-contained file, copied into every enabled model dir. No helper
modules: the runtime imports each model's `inference.py` under a unique
module name, but helper imports would share `sys.modules` across models.

```
infer(frame: np.ndarray (BGR), config: dict | None = None, **_) -> dict
```

- On first call (the runtime's warmup triggers it): read
  `store_manifest.json` next to `__file__`, load `YOLO(weights)` and move it to
  CUDA. Weights always resolved from `Path(__file__).parent`.
- Run `model(frame, imgsz=manifest.imgsz, conf=<lowest rule confidence>,
  verbose=False)`. Ultralytics returns boxes in **original frame pixels**, so
  stored boxes are correct against `frame_width/height` (unlike fall, BL-3).
- Detections: `{class_id, class_name, label, confidence, bbox: [x1,y1,x2,y2]}`
  for every class in the manifest.
- Rules (from the manifest), each:
  `{id, classes, min_confidence, violation_type, severity, requires_zone?}`.
  A rule fires when any detection of its classes reaches `min_confidence`.
  A `requires_zone` rule is evaluated only for detections whose anchor point
  (bottom centre) lies inside a zone of that type in `config.zones`; with no
  such zone it is inactive (fails closed).
- Result (same shape the backend already consumes):
  `{violation_detected, violation_type, severity, confidence, detections,
  metadata: {model_id, version, plugin_version, rules_active, rules_inactive}}`.
  `confidence` is the highest confidence among the firing detections, so the
  session threshold (0.7) applies to it. When several rules fire, the
  highest-severity one names `violation_type`.
- Any exception returns a non-violation result with the error in `metadata`
  (the runtime would otherwise report `status: failed`).

### 2.4 Hand-written manifests for the three uploads

Stored per model (see 2.5); `model.yaml` is generated from them.

```json
{
  "manifest_version": 1,
  "model_id": "hard_hat",
  "display_name": "Hard Hat",
  "weights": "besthardhat.pt",
  "task": "detect",
  "imgsz": 1280,
  "classes": {"0": "hardhat", "1": "no-hardhat"},
  "rules": [
    {"id": "missing_hardhat", "classes": ["no-hardhat"], "min_confidence": 0.5,
     "violation_type": "missing_hardhat", "severity": "critical"}
  ],
  "performance": {"inference_time_hint_ms": 25, "recommended_fps": 2},
  "limits": {"max_memory_mb": 1024, "inference_timeout_ms": 5000}
}
```

```json
{
  "manifest_version": 1,
  "model_id": "safety_vest",
  "display_name": "Safety Vest",
  "weights": "bestvest.pt",
  "task": "detect",
  "imgsz": 1280,
  "classes": {"0": "no-vest", "1": "vest"},
  "rules": [
    {"id": "missing_vest", "classes": ["no-vest"], "min_confidence": 0.5,
     "violation_type": "missing_vest", "severity": "critical"}
  ],
  "performance": {"inference_time_hint_ms": 40, "recommended_fps": 2},
  "limits": {"max_memory_mb": 1536, "inference_timeout_ms": 5000}
}
```

```json
{
  "manifest_version": 1,
  "model_id": "gloves",
  "display_name": "Gloves",
  "weights": "bestgloves.pt",
  "task": "detect",
  "imgsz": 1280,
  "classes": {"0": "gloves", "1": "no-gloves"},
  "rules": [
    {"id": "missing_gloves", "classes": ["no-gloves"], "min_confidence": 0.5,
     "violation_type": "missing_gloves", "severity": "high"}
  ],
  "performance": {"inference_time_hint_ms": 40, "recommended_fps": 2},
  "limits": {"max_memory_mb": 1536, "inference_timeout_ms": 5000}
}
```

- **Validation on save:** `classes` must equal the class names read from the
  `.pt` (the introspector above), every rule class must exist, `weights` must
  be one of the model's uploaded files, `performance` values must be
  integers (the backend's registration schema rejects floats with a 422),
  `imgsz` a multiple of 32.
- **Thresholds:** `min_confidence` 0.5 is the plugin's floor; the session's
  `confidence_threshold` (0.7, set by `POST /devices/{id}/models`) then
  applies to the result. Effective threshold for violations is 0.7, same as
  built-in models.
- The latency hints are estimates (yolov8n/m at 1280 on the RTX 3090);
  pacing corrects them from measured latency within a few ticks.

### 2.5 Store backend: manifest, enable/disable, Apply, load status

All under the existing admin gate (`/api/v1/admin/model-store`), store-only
code (`app/services/model_store/`, `app/api/v1/admin/model_store.py`):

- **Migration (store tables only):** `model_store_models.manifest JSONB NULL`,
  `state` gains `enabled` / `disabled`, plus `applied_revision`,
  `applied_at`.
- `PUT /models/{id}/manifest`: validate as in 2.4 and save (drafts only, or
  enabled → marks "changes pending Apply").
- `POST /models/{id}/enable` / `disable`: requires a valid manifest; changes
  state only.
- `POST /apply`: build the enabled tree (2.2) from every `enabled` model,
  then restart the store runtime (see **decision A**). Returns the applied
  revision.
- **Live load status:** the store service reads the store runtime's
  `/capabilities` (`state`, `health` per model) and the Model Management
  page shows Loading / Ready / Failed per model; failures show the runtime's
  error.

**Decision A — how Apply restarts the store runtime.** The backend has no
Docker access and should not get it.
- **A1 (recommended): token file.** Apply writes
  `state/apply-token`; a small, flag-gated watcher in the runtime
  (`STORE_APPLY_WATCH_FILE`, only set on `model-store-runtime`) exits the
  process when the token changes, and `restart: unless-stopped` brings it
  back with the new tree. ⚠ touches `ai/server/main.py` (conditional
  include); with the variable unset — as on `unified-ai-runtime` — the code
  path is identical.
- **A2: manual.** Apply writes the tree and the page says "restart
  required"; an operator runs `docker compose restart model-store-runtime`.
  No runtime change; fine for this step's goal, clumsy afterwards.

### 2.6 Backend routing: `StoreAwareRouter`

- New setting `MODEL_STORE_RUNTIME_URL` in `UnifiedRuntimeConfig` (empty =
  feature off). Added to `.env.example` and the backend's compose
  environment.
- `RuntimeRouter` gets an optional `client_for(model_id)` hook used at the
  two places it calls the runtime (`router.py:200`, `:272`); the default
  returns the existing client, so behaviour is unchanged.
- `lifespan.py:268-275`: when `MODEL_STORE_RUNTIME_URL` is set, build a
  second `UnifiedRuntimeClient(runtime_url=...)` and a router whose hook
  returns it for **store ids**: the set of models the store runtime reports
  in `/capabilities`, cached 30 s, never including a reserved built-in id.
  A failed lookup delegates to the built-in client (store ids then 404 and
  back off, as today).
- Covers both loops: the legacy loop (`submit_inference`) and the
  multi-model loop (`submit_inference_with_frame`, with the tick's shared
  frame — no extra frame fetch).
- Not covered, accepted: bookmark analysis and `POST /api/v1/ai/inference`
  create their own clients; store models aren't available there.
- The loop's shared `INFERENCE_CONCURRENCY=2` slots also cover store calls.

### 2.7 `/models/status` lists store models; the picker shows them

- `app/api/v1/models.py`: after the built-in loop, a guarded block reads the
  store runtime's `/capabilities` and **appends** one entry per store model
  (skipping any id already present). The per-model status/health body is
  extracted into a helper used by both blocks, so built-in entries are
  computed exactly as now.
- Additive optional fields on `ModelStatusInfo` (store entries only):
  `source: "store"`, `display_name`, `zone_required_rules`,
  `all_rules_need_zone`, `draws_overlay: false`.
- `cameras_active` for store entries counts sessions whose `models` JSONB
  contains the id (built-in counting unchanged).
- Feature off or store runtime unreachable → the response is exactly today's.
- **Picker (frontend):** store rows appear automatically (healthy/degraded).
  Small additive changes:
  - name from `display_name` when present (else today's rule),
  - rows with `all_rules_need_zone` disabled with the reason,
  - a "detections not drawn yet" note for `draws_overlay: false`.
- **Zone gate in the API:** `POST /devices/{id}/models` returns 422 for a
  store model whose every rule needs a zone (none of the three do).

### 2.8 Registration, health, violations

- The store runtime registers with `RUNTIME_ID=model-store-runtime`;
  `recommended_fps` for store models then comes from their manifests.
- ⚠ `health_service.py:234-249` uses the *first* registered runtime as "the
  AI runtime". Filter to the built-in runtime (id prefix `unified-runtime`)
  so the store runtime can never become the system's AI health.
- ⚠ `app/models/enums.py`: add `"missing_gloves": PPE_VIOLATION` to
  `VIOLATION_TYPE_MAP` (additive; silences the per-violation warning).
  Hard hat and vest types are already mapped.

### 2.9 GPU budget on the demo camera

Fall + three store models + DEMO-CAMERA2's PPE = 5 consumers. With the
budget's `MAX_GPU_UTILIZATION` 2.3 and latencies ~0.08 s (fall), ~0.03–0.05 s
(store models, estimated), ~0.37 s (PPE), every model stays at its 2 fps
target except PPE (`2.3 / (5 × 0.37) ≈ 1.24 fps`, down from ~1.5 today).
The budget was tuned for one runtime process; two processes on one GPU run
in parallel, so it is conservative rather than optimistic.

---

## 3. Operator-visible caveats

1. **No boxes for store models in the live view** until the generic overlay
   (Store Step 6). Violations, snapshots and `/detections` work. Pulling a
   minimal generic overlay (labelled boxes for `draws_overlay: false`
   models) forward is a small frontend change if wanted — **decision B**.
2. **Duplicate PPE alerts if both run.** Built-in `ppe_detection` also
   reports missing hardhat/vest/gloves; ticking it together with the store
   models raises two violations for the same person. Step 5 doesn't prevent
   it; the picker could warn — **decision C**.
3. Suppression is today's rule (BL-2 not applied): each enter-violation
   transition raises one violation per model.

---

## 4. Touches to existing paths (sign-off needed)

| Item | Existing file | Isolation |
|---|---|---|
| New compose service | `vas-ruthai-deploy/docker-compose.yml` | Additive service; existing services untouched |
| Router hook | `ruth-ai-backend/app/integrations/unified_runtime/router.py` | Default hook returns the existing client |
| Router wrap | `ruth-ai-backend/app/core/lifespan.py` | Only when `MODEL_STORE_RUNTIME_URL` is set |
| Setting | `.../unified_runtime/config.py`, `.env.example`, backend compose env | Empty = off |
| Append store entries | `ruth-ai-backend/app/api/v1/models.py`, `app/schemas/models.py` | Guarded block; optional fields; golden response test for built-ins |
| Health first-runtime | `ruth-ai-backend/app/services/health_service.py` | Filter to the built-in runtime id |
| `missing_gloves` mapping | `ruth-ai-backend/app/models/enums.py` | One additive entry |
| Zone gate | `ruth-ai-backend/app/api/v1/device_models.py` (M1 code) | Store ids only |
| Apply watcher (A1 only) | `ai/server/main.py` | Env-gated; unset on the built-in runtime |
| Picker extras | `AIModelSelector.tsx`, `pickerState.ts` (M3 code) | Additive props/fields |

New: `ai/store_plugin/inference.py`, store migration, store service/API
additions, tests.

## 5. Tests

- `/models/status` built-in entries byte-identical with the feature off, on,
  and with the store runtime down (golden response).
- Router: built-in ids always reach the original client (both methods);
  store ids reach the store client; lookup failure delegates.
- Legacy golden trace and M1 multi-model tests unchanged.
- Plugin: rules, class-order handling (vest), zone fail-closed, error path —
  with a fake YOLO object (no uploaded pickle executed in tests).
- Manifest validation against introspected classes; Apply tree (no
  symlinks, atomic swap, rollback).
- Frontend: store rows (display name, disabled reason, overlay note); M2/M3
  suites unchanged.

## 6. Live verification (demo camera only, UI idle)

1. Apply the three models; store runtime `/capabilities` shows them READY;
   Model Management shows Ready.
2. `/models/status` lists the 5 built-ins exactly as before plus 3 store
   entries; the picker shows Hard Hat, Safety Vest, Gloves.
3. Tick Fall, then Hard Hat, Safety Vest, Gloves: one session, 4 models;
   `/detections` returns 4 entries; runtime logs show store inference on
   `model-store-runtime` and fall on `unified-ai-runtime`.
4. Stand in view without a hard hat: a `ppe_violation` with
   `type_detail=missing_hardhat`, model_id `hard_hat`, boxes in frame pixels.
5. Latency per model (exact attribution from both runtimes' logs) and
   DEMO-CAMERA2's PPE rate before/after.
6. Restart only `model-store-runtime`: fall keeps running; store models back
   off and resume.
7. Untick everything; camera ends with no session.

## 7. Order and effort (estimate)

| # | Piece | Days |
|---|---|---|
| 1 | Plugin + manifests + enabled tree (scripted) + compose service | 3 |
| 2 | Routing, `/models/status` append, health filter, enum entry | 2–3 |
| 3 | Store manifest / enable / Apply / load status (+ migration) | 3 |
| 4 | Picker extras + zone gate | 1 |
| 5 | Tests, live verification | 2 |

≈ 2–2.5 weeks. Piece 1 + 2 alone reach the goal with manifests installed by
a script and a manual restart (A2); 3 makes it self-service.

## 8. Decisions needed

- **A.** Apply restart: A1 token watcher (⚠ `ai/server/main.py`, env-gated)
  or A2 manual restart.
- **B.** Minimal generic overlay for store models now, or wait for Step 6.
- **C.** Warn in the picker when built-in PPE and store PPE models run
  together, or leave it.
- **D.** Severity for gloves (`high` proposed; hardhat/vest `critical` as
  built-in PPE does).
- **E.** Landing pieces 1+2 first (goal reachable, script-installed
  manifests) and 3 after, or all at once.
