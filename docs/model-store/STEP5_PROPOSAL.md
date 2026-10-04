# Model Store — Step 5 proposal (draft)

Step 5 in the landing order: **auto-integration** — store runtime, plugin,
Apply, enable/disable, live load status.

This document is started ahead of the full proposal to record a change of
plan agreed on 2026-10-04. The remaining sections are written when Step 5 is
proposed.

---

## Change of plan: enabled store models appear in the camera picker

### What the original design said

Store design §10 kept uploaded models **out of `/api/v1/models/status`**, so
the existing camera picker would never offer them; they were to be deployed
only from the Model Management page (Step 6: zone editor + deploy panel),
with "store models in the existing picker" listed under *later, needs
explicit sign-off*.

### What changes

Enabled store models must appear in the camera picker **like built-in
models**. The picker itself needs no further change for this: after M3 it
renders whatever `/models/status` returns and adds/removes models through
`POST/DELETE /devices/{id}/models`, which start, extend or shrink the
camera's one session.

### What Step 5 then needs

1. **List store-runtime models in `/models/status`, without changing how
   built-in entries look.**
   - Built-in entries keep their exact shape, values and order (golden
     response test on today's 5 models).
   - Store entries are appended after them, built from the store runtime's
     `/capabilities` (or its registration push) and only for models that are
     enabled **and** loaded/healthy there.
   - Store entries carry additive fields only: `source: "store"`, and the
     rule metadata the picker needs (`zone_required_rules`, `all_rules_need_zone`).
   - If the store runtime is down or `MODEL_STORE_ENABLED=false`, the list is
     exactly today's.
   - Model id collisions are already impossible (`RESERVED_MODEL_IDS`).

2. **Routing must land with Step 5, not Step 6.** Once the picker can add a
   store model, inference for it must reach the store runtime. The
   `StoreAwareRouter` wrapper planned for Step 6 (flag-gated wrap in
   `lifespan.py`; built-in models delegate unchanged) therefore moves into
   Step 5. It must also cover the multi-model path's per-model calls
   (`submit_inference_with_frame`), not only the legacy loop.

3. **Zone-required rules stay blocked until zones exist.**
   - The plugin already fails closed: a rule marked "requires zone" is
     evaluated only for detections inside a zone of its type in the model's
     config; with none it never fires.
   - Until the zone editor (Step 6) exists there is no way to draw zones, so:
     - a store model whose **every** violation rule needs a zone is shown in
       the picker but **disabled**, with the reason ("needs a
       `work_at_height` zone — available with zone setup");
     - a model with **some** zone-required rules can be enabled; the picker
       shows which rules are inactive on that camera.
   - The backend enforces the same rule on `POST /devices/{id}/models` (422
     with the reason), so it holds for API callers too, not just the UI.

4. **Live overlay.** Store models draw nothing in the live view until the
   generic overlay (Store Step 6) lands; the M2 fan-out ignores unknown model
   ids by design. The picker should say so for store models
   ("detections not drawn yet").

5. **GPU budget and pacing.** `InferenceBudget` must count store-model
   consumers like any other (it already keys by (session, model)), and
   `model_rates.recommended_fps` must read the store runtime's registry for
   store models; otherwise they fall back to `TARGET_FPS`.

6. **Violations.** Until Step 7 (labels for new types), store-model
   violations are stored under the fallback family. Picker exposure makes
   this reachable earlier than planned, so Step 7 should follow Step 5
   closely, or Step 5 ships with violations disabled for store models.

7. **Versions.** The store has no version concept; store entries in
   `/models/status` report the store's manifest version, and sessions pin
   nothing. (Built-in version selection is a separate issue: BL-1.)

### Touches existing paths (needs sign-off)

| Item | Existing file / behaviour | Isolation |
|---|---|---|
| Append store entries | `ruth-ai-backend/app/api/v1/models.py` (`/models/status`) | Flag-gated; built-in entries byte-identical; golden response test |
| Routing wrapper | `app/core/lifespan.py` | Flag-gated wrap; built-in model ids delegate unchanged |
| Zone gate on add | `app/api/v1/device_models.py` (new in M1, not one of the original paths) | Applies only to store model ids |
