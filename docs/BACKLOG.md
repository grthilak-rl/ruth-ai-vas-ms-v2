# Backlog

Parked work with its findings, so it can be picked up without redoing the
investigation. Newest first.

---

## BL-4 · `stop-inference` returns 500 when there is nothing to stop

**Status:** parked · **Found:** 2026-10-04 · **Area:** backend, existing router

**Finding.** `POST /api/v1/devices/{id}/stop-inference` on a camera with no
active session logs `No active session to stop (idempotent)` and then fails
with `Response serialization error`, returning **500**. The handler intends an
idempotent success; the response it builds on that path doesn't validate
against the response model. Seen 2026-10-04 14:11:26Z on device
`9f415bae-…` (request `c72a892e-…`).

**Impact.** Clients that stop a camera twice (two tabs, a retry, a race with
another operator) see an error for a no-op; `fetchWithRetry` retries 500s
twice with 2 s / 5 s backoff before surfacing it.

**Proposal.** Return the same success shape as a real stop (or 200 with an
explicit `already_stopped: true`) on the idempotent path, with a test. This
touches an existing router, so it needs explicit approval under the
"existing paths unchanged" constraint.

---

## BL-3 · Fall boxes drawn in the wrong place on violation snapshots

**Status:** parked · **Found:** 2026-10-04 · **Area:** backend + frontend

**Finding.**
- `fall_detection` reports boxes in its **640×640 model input space** (the
  frame is resized to 640×640 without letterbox). PPE reports in frame pixels.
- `inference_loop._create_violation_unguarded` (`inference_loop.py:1423-1436`)
  attaches the **full frame size** (`frame_width: 1280, frame_height: 720`) to
  every model's boxes. `_normalize_bbox` converts to `{x, y, width, height}`
  without rescaling; its docstring wrongly says frame pixels.
- The only renderer of stored boxes is
  `frontend/src/components/violation-detail/SnapshotOverlay.tsx` (on-screen
  overlay, lines 174-220, and "Download annotated", lines 249-271). It scales
  by `frame_width/frame_height`, falling back to the snapshot's natural size,
  with no per-model handling.
- Result: every backend fall box is drawn at **0.5× x and width, 0.889× y and
  height**. Example: stored (198,558) 49×80 is drawn there instead of at
  (396,628) 98×90 in the 1280×720 frame.
- Older browser-source fall rows (`fall-detection-yolov8`) have no frame dims
  and fall back to the snapshot size: same misplacement.
- PPE boxes are drawn correctly.
- CSV export (`export_service.py:187-188, 234-236`) writes the raw 640-space
  numbers next to `frame_width: 1280`, which misleads consumers.
- Not affected: thumbnails and alert cards (no box overlay); there is no
  server-side overlay rendering.

**Proposal.**
- Frontend: pass `model_id` to `SnapshotOverlay` and treat fall model ids
  (`fall_detection`, `fall-detection-yolov8`) as a 640×640 source. Fixes
  existing rows as well as new ones.
- Optionally, backend: store fall boxes rescaled to frame pixels (or with
  `frame_width/height = 640`). Changes an existing path; needs approval and a
  decision on whether old rows are migrated or handled by the frontend rule.
- Correct the `_normalize_bbox` docstring either way.

---

## BL-2 · Duplicate-violation suppression: streak + real cooldown (multi-model path only)

**Status:** parked (approved in principle; implement after M3) · **Found:**
2026-10-04 · **Area:** backend, multi-model inference loop

**Finding.** The violation rule (legacy loop and its multi-model copy in
`_apply_violation_rules`) creates a violation on **every clear→violation
transition**, after even a single clear frame:
- no streak: one positive frame opens a violation;
- the 30 s `_violation_cooldown_seconds` branch is a no-op (`pass`);
- no per-person tracking.

The legacy block is byte-identical before M1 (`133e5cf`) and at HEAD, so this
is long-standing behaviour, not an M1 regression.

On 2026-10-04 one real fall on the demo camera was followed by 58 further
violations over 78 minutes, each a 1–6 frame flicker of a false positive
(see BL-1).

**Proposal.**
- Optional per-model `suppression: {min_consecutive_frames, cooldown_seconds}`
  on each `stream_sessions.models[]` entry — its own field, not `config`, so
  it is never sent to the runtime. PATCH-able.
- Defaults applied by `POST /devices/{id}/models`: `fall_detection` →
  `{2, 30}`; every other model → `{1, 0}` (today's behaviour).
- Streak: open a violation only after N consecutive qualifying results of that
  model (its own ticks); one miss resets the count.
- Cooldown: no new violation for that (session, model) within C seconds of the
  last one created, even if the state cleared in between. Geo keys the
  cooldown per zone so entering a new zone still alerts.
- Legacy loop (`models` NULL) untouched; golden legacy trace must stay
  identical; multi with `{1, 0}` must match today's multi rules exactly.
- State is in memory: a backend restart resets streaks and cooldowns.

**Evidence (simulated on the 59 episodes of 2026-10-04):**

| Setting | Violations |
|---|---|
| `{1, 0}` (today) | 59 |
| `{2, 0}` | 27 |
| `{1, 30}` | 19 |
| `{2, 30}` | 14 |
| `{3, 30}` | 10 |

Suppression reduces noise but cannot remove a persistent false positive; BL-1
is the root-cause fix.

---

## BL-1 · fall_detection 1.1.0: confidence floor, size-relative geometry, confidence from detection

**Status:** parked (approved in principle) · **Found:** 2026-10-04 · **Area:**
AI model, runtime version selection

### Root cause

`ai/models/fall_detection/1.0.0/inference.py`, `_analyze_pose_for_fall`:
- Every pose detection ≥ 0.25 (the NMS threshold) is analysed, however
  uncertain.
- Indicators use **absolute pixel thresholds in 640-space**: `horizontal_body`
  (|shoulder−hip| < 50 px, 0.8), `compact_body` (keypoint y-range < 150 px,
  0.7), `head_below_hips` (+20 px), `legs_spread` (> 100 px). Any small or
  distant person satisfies `horizontal_body` and `compact_body`.
- The result confidence is the indicator's constant (0.8 / 0.7), not the
  detection's, so it always clears the session threshold of 0.7; `possible_fall`
  at exactly 0.7 also passes `>= 0.7`.

**Incident, 2026-10-04 18:23–18:30 IST, demo camera:** after one real fall
(person box 0.79), 20 further violations came from a blue child's chair
detected as a "person" at 0.25–0.41 confidence, 49×81 px in 640-space; it
flickered in and out at the NMS threshold. All 20 snapshots show the chair and
an empty room. Session `ab705eb2` (legacy loop) reached 59 violations before
it was stopped.

### Proposed rules (as evaluated)

- Skip detections below **0.5** confidence.
- Every pixel threshold relative to person size S = the box's **longer side**:
  horizontal < 0.15·S; head below hips > 0.05·S; legs spread > 0.5·S; compact
  body < 0.35·S. (A purely height-relative test fails for a lying person,
  whose box is short.)
- Result confidence = the triggering detection's confidence (so the session
  threshold 0.7 applies to it).
- Update the hardcoded `"model_version": "1.0.0"` in the copied
  `inference.py` (lines 76 and 231).

### Validation against history (IOCL era, 2026-07-29 → 08-02)

VAS snapshots for that period no longer exist (VAS retains hours), so frames
were taken from the HLS recordings in `/mnt/storage/hot` (segment filenames
are epoch start times). For each violation, 8 frames from −3 s to +0.25 s
were decoded; the frame whose detections best matched the stored boxes was
scored with both rule sets. Stored boxes align with people/objects in the
recorded frames, confirming the time and coordinate mapping.

All 6,753 violations processed; 6,487 had a recorded frame.

| | Backend loop (3,118) | Browser path (3,369) |
|---|---|---|
| A. 1.0.0 reproduces the fall on that person | 989 | 1,405 |
| → kept by 1.1.0 | 6 | 1 |
| → dropped by 1.1.0 | 983 | 1,404 |
| B. Person present, 1.0.0 doesn't reproduce on the recorded frame | 1,046 | 365 |
| C. No detected person at the stored box (objects: glove bundle on scaffolding, pipes, lamps) | 1,083 | 1,599 |

- Drops among reproduced cases: geometry 2,304; confidence floor 69; session
  threshold (0.5–0.7) 14.
- 1.0.0 indicators that fired: `compact_body` 1,928, `horizontal_body` 1,807.
- By person size (longer side, 640-space): < 80 px 404 reproduced / 0 kept;
  80–160 px 1,386 / 1; 160–320 px 599 / 6.
- Visual review of random samples: dropped = standing/walking workers, people
  on scaffolding, bags, lamps; no lying person seen. Kept (all 7) = workers
  bent over or crouching, plus one with no person (pipe, conf 0.81).
- The only real fall available, the 2026-10-04 demo fall, is kept by 1.1.0
  (0.92).

**Caveat:** the history contains essentially no real falls. This shows 1.1.0
removes > 99 % of historical false positives; it says **nothing about recall**,
especially for small/distant people. Before shipping: a staged positive set
(near, far and partly occluded falls on 2–3 cameras).

Artifacts from the run (scratch, not in the repo): contact sheets of kept,
dropped and small-dropped samples, and per-violation results.

### Version selection — must be addressed before adding 1.1.0

Adding `ai/models/fall_detection/1.1.0` next to 1.0.0 today would:

| Component | Behaviour | Evidence |
|---|---|---|
| Runtime startup | loads **every** version (2× GPU memory) | `ai/server/main.py:203-251` |
| Runtime `/inference`, no version | first registered = **lexically lowest** (1.0.0; also "1.10.0" < "1.9.0"); logs the key as `latest`; 404 if that one isn't ready even when another is | `ai/server/routes/inference.py:363-374` |
| Backend `/models/status` | dict overwrite → **lexically highest** shown (1.1.0) | `ruth-ai-backend/app/api/v1/models.py:62-66` |
| Sessions / UI | never send a version (NULL) → runtime decides | `CameraMonitoringDashboard.tsx:209-214` |
| Violations | record the version that actually ran | `router.py:225, 290` |

So 1.0.0 would keep running everywhere while the UI shows 1.1.0.

**Proposal.** Keep the no-version default (existing paths unchanged). Roll
out per camera by pinning `model_version: "1.1.0"` on the multi-model
`models[]` entry (field already exists). Additively make `/models/status`
list every version. Semantic version ordering in the runtime is a separate,
approval-needing change.
