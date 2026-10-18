# Backlog

Parked work with its findings, so it can be picked up without redoing the
investigation. Newest first.

---

## BL-12 · Frame-tap stalls: 6.3% of fetches take over a second

**Status:** open, not investigated · **Found:** 2026-10-18 (measuring
BL-10) · **Area:** `RuntimeRouter.fetch_frame` -> VAS frame tap

**Finding.** Frame fetch is bimodal, and the slow mode is severe. From
logging `fetch_seconds`, which the loop has always measured and then
discarded into the budget:

| | 20-min window | 13.5-hour corroboration |
|---|---:|---:|
| estimated fetches | 7,242 (6.1/s) | 284,433 (5.9/s) |
| **P(fetch >= 500 ms)** | **6.10%** | **6.34%** |
| body p50 / p95 / mean | 37 / 135 / 50 ms | 33 / 89 / 43 ms |
| tail p50 / p95 / max | 1,085 / 2,805 / 3,568 ms | 1,087 / 2,687 / **12,483 ms** |
| tail mean | 1,254 ms | 1,281 ms |
| true mean (EWMA sees this) | 124 ms | 122 ms |

**94% of fetches cost 37 ms and are nearly free. 6% cost over a second.**
The mean of 122 ms describes neither mode and is the number the pacing
budget has been reacting to all along.

**It is uniform across the fleet.** Every one of the 12 cameras sits
between 5.80% and 6.93% slow, with near-identical counts (1,373-1,551
each over 13.5 h). That rules out a single bad camera, a single bad
network path, or anything per-stream, and points at the shared frame-tap
path.

**Impact.** 18,033 stalls averaging 1.28 s in 13.5 hours is roughly
**6.4 hours of cumulative wall time spent waiting for frames** — more
than any pacing change on the table is worth. It also distorts every
latency figure the system reports about itself, because the budget EWMA
folds fetch and inference together.

**Hypotheses, untested, in rough order of likelihood.**

- *Keyframe or segment-boundary wait.* A tap that must wait for the next
  I-frame would stall for up to a GOP interval. A ~1 s median tail is
  suspiciously close to a 1-2 s GOP at these frame rates. **Testable:**
  the stalls would cluster at a characteristic period per camera.
- *Shared resource contention.* A connection pool, a lock, or a
  single-threaded path in VAS that 12 cameras queue behind. **Testable:**
  stalls would coincide *across* cameras.
- *Timeout-and-retry.* A silent retry after a fixed timeout would make
  the tail pile up near a round number. The tail p50 of 1,085 ms is
  suggestively close to 1 s.
- *HLS buffer rotation / `date_dir_rotator`* doing periodic work that
  blocks reads.

**Planned next measurement (read-only, cheap).** Correlate stall
timestamps *across* cameras. The logs already carry `device_id` and a
timestamp on every slow fetch, so no new instrumentation is needed:

- If the 12 cameras stall **together**, it is a shared resource — look at
  VAS's frame-tap path and its concurrency.
- If they stall **independently**, it is per-stream — look at keyframe
  cadence and the tap's buffering.
- Also worth plotting the tail's inter-arrival times per camera: a
  strong period points at a GOP or a rotation job.

Raising `RUTH_SLOW_FETCH_SECONDS` sampling is not needed; slow fetches
are already logged as a census.

**Do not "fix" this by re-pacing around it.** BL-10 (a) would make the
budget ignore fetch entirely, which would hide this fault rather than
address it — see the note there.

---

## BL-11 · A camera can stop being monitored silently, and nothing says so

**Status:** open, operational · **Found:** 2026-10-17 (HPCL) · **Area:**
backend lifespan / inference sessions, and whatever should alert on this

**Finding.** Camera **74004** had no AI inference for **21.3 hours** while
its video stream ran normally. Nobody noticed; it surfaced only because a
camera count was questioned.

| | |
|---|---|
| VAS | stream `LIVE`, device enabled, `desired_state=ACTIVE` |
| Ruth | no active session; last one `stopped` 2026-10-16 13:29 |
| last session | single-model `safety_vest`, started 13:21 |
| violations from this camera, ever | **0** |

The other 11 cameras were reconfigured to 3-model sessions between 13:27
and 13:29 that day. 74004's single-model session stopped at 13:29 with an
empty `error_message` — a clean stop — and was never restarted with the
new configuration. It looks like it was missed during that change, not
that anything crashed.

**Two separate problems.**

1. **Nothing restarts it.** Ruth's lifespan has no auto-resume for
   inference sessions: a stopped session stays stopped across backend
   restarts. The backend restarted twice on 2026-10-17 and 74004 did not
   come back. (VAS has `desired_state` + auto-resume for *video*; Ruth has
   no equivalent for *inference*.)
2. **Nothing reports it.** The camera reads as healthy almost everywhere —
   the video is live, the device is enabled and active. Only
   `streaming.ai_enabled` is false, which no alert watches. A plant can
   therefore believe a camera is monitored when it is not, which is worse
   than it being visibly offline.

**Impact.** Safety monitoring silently absent on one of twelve cameras for
most of a day. This is the failure mode the product most needs not to
have.

**Resolved for this instance:** 74004 was started manually with the same
3 models at 2026-10-17 10:52 UTC (16:22 IST), taking the fleet to 12
sessions / 36 consumers. The two defects below remain.

---

### Proposal A — persist intent, and resume it

Mirror what VAS already does for video. VAS keeps
`devices.desired_state` (`ACTIVE` / `STOPPED`), documented as *"survives
restarts and drives auto-resume: on startup, devices with ACTIVE are
restarted automatically; STOPPED devices stay down until an operator opts
back in."* Ruth has no equivalent for inference, which is the whole gap.

*Shape.* A durable per-device inference intent, set by the existing
start/stop-inference endpoints, plus a startup reconciler that brings
reality to match it.

- **Where the intent lives.** Not on `stream_sessions` — a session is a
  record of a run, and the last one here is `stopped`, which is correct
  and must stay correct. It belongs on `devices` (e.g.
  `inference_desired_state` + `inference_models` jsonb), or in a small
  `device_inference_intent` table. `devices` is the simpler read; the
  separate table avoids widening a row the VAS sync overwrites — note
  `_sync_single_device` rewrites `devices` columns on every sync, so any
  new column there must be explicitly excluded from the sync or it will
  be clobbered. **That is the trap to avoid**; it is the same mistake
  `is_active` already embodies.
- **When it reconciles.** On backend startup, after the device sync, and
  periodically (the supervisor already wakes regularly). Reconciling only
  at startup would not have fixed 74004, whose session died during a
  reconfiguration, not a restart.
- **What it must not do.** Restart inference on a camera an operator
  deliberately stopped. Hence *intent*, not "was running recently":
  stop-inference clears the intent, a crash does not.
- **Failure modes to design for.** A camera whose model no longer exists
  (uploaded model deleted) must fail visibly, not loop. A camera VAS has
  disabled (`enabled=false`) must not be resumed. Repeated start failures
  need backoff and should surface, not retry silently forever.

**Decided (2026-10-17):** desired-state model, not "last session ended
cleanly". Intent is recorded explicitly when an operator acts; a session
ending for any reason other than an operator stop is a gap to be closed.
Order: **B first, then A.**

#### Schema

```sql
CREATE TABLE device_inference_intent (
    device_id            uuid PRIMARY KEY
                           REFERENCES devices(id) ON DELETE CASCADE,
    desired_state        varchar(8)  NOT NULL DEFAULT 'off',  -- 'active' | 'off'
    models               jsonb,            -- same shape as stream_sessions.models
    inference_fps        integer,
    confidence_threshold double precision,
    consecutive_failures integer     NOT NULL DEFAULT 0,
    last_attempt_at      timestamptz,
    last_error           text,
    updated_at           timestamptz NOT NULL DEFAULT now(),
    updated_by           text,
    CONSTRAINT ck_intent_state CHECK (desired_state IN ('active', 'off'))
);
```

Why this shape:

- **A separate table, not columns on `devices`.** `_sync_single_device`
  rewrites `devices` on every VAS sync; a column there would be silently
  clobbered. This is the same trap `is_active` already embodies, and the
  reason it cannot be used as a policy flag.
- **Primary key on `device_id`** — exactly one intent per camera. No
  history: `stream_sessions` already is the history, and a second
  historical record would be a second thing to keep consistent.
- **`models` mirrors `stream_sessions.models`** so the reconciler can
  pass it straight to the existing start path with no translation. NULL
  means "the legacy single model", matching the session convention.
- **No `failed` column.** Failure is *derived*:
  `desired_state = 'active' AND consecutive_failures >= 2`. A stored
  status would be a second source of truth that can disagree with the
  counter; the counter is what the reconciler already has to maintain.
- **`ON DELETE CASCADE`** — devices are never deleted today (only marked
  inactive), but if one ever is, its intent should go with it.

#### Who writes it

Every operator action that changes what should be running:

| action | writes |
|---|---|
| picker adds a model (`POST /devices/{id}/models`) | `desired_state='active'`, models updated |
| picker changes one (`PATCH .../models/{model_id}`) | models updated |
| picker removes one (`DELETE .../models/{model_id}`) | models updated; `'off'` if it was the last |
| `POST /devices/{id}/start-inference` | `desired_state='active'` + models |
| `POST /devices/{id}/stop-inference` | **`desired_state='off'`** |

**An operator stop sets the intent off, so it is never auto-resumed.**
That is the whole safety property: the reconciler restores what somebody
asked for and never overrides what somebody switched off.

Writing intent in the same transaction as the session change keeps the
two from diverging on a crash mid-request.

#### Reconciler

A periodic task, **not** startup-only — 74004's session died during a
reconfiguration, not a restart, so a startup-only reconciler would not
have caught it.

- **Interval: 60 s**, `RUTH_INFERENCE_RECONCILE_SECONDS`. Worst-case
  coverage gap of about a minute; twelve cheap reads per minute; far
  slower than any legitimate transient. Deliberately *not* folded into
  the inference loop's existing 1 s tick: that cadence is for starting
  and stopping local tasks, while a resume calls VAS, and retrying that
  every second against a camera that is genuinely broken is a way to
  turn one failure into an outage.
- **Each pass:** for every intent with `desired_state='active'` and no
  session in (`starting`, `live`, `stopping`), attempt a start with the
  recorded models. Log every resume at INFO with device, models and the
  reason the session was missing.
- **Grace window:** skip any camera whose `updated_at` is within the last
  30 s, so the reconciler cannot race an operator action still in flight.
- **`starting` counts as present.** Treating it as missing would start a
  second session and trip `uq_stream_sessions_device_active`.
- **Never resume** a camera with `devices.enabled = false` (retired in
  VAS) or `is_active = false` (absent from VAS). Both are states where
  starting would be wrong and would fail anyway.

#### Failure handling (refined 2026-10-17)

**Distinguish shared-dependency failures from per-camera ones.** If VAS
or the target runtime is unreachable or unhealthy, *every* camera will
fail to start — and counting those would park the entire fleet within two
cycles over an outage that has nothing to do with any individual camera.
Worse, the fleet would then stay parked after the dependency recovered,
because parking is what stops retrying.

- *Shared failure* (VAS unreachable, runtime unhealthy, DB unavailable):
  **skip the cycle entirely**, do not touch `consecutive_failures` for
  any camera, and raise **one** system-level alert naming the dependency.
  One alert, not twelve.
- *Per-camera failure* (model missing, stream will not start for this
  camera, start rejected): `consecutive_failures += 1`, record
  `last_error`.

Detecting the difference cheaply: check the dependency once per cycle
before iterating cameras, and treat a run where every attempt failed with
the same dependency-shaped error as shared rather than per-camera.

**Parked is not permanent.** Two consecutive per-camera failures stop the
*fast* retry, not all retries. A parked camera is retried on a capped
backoff — **5 min → 15 min → 60 min, then every 60 min** — so a camera
that was broken for a fixable reason recovers on its own without anyone
remembering it exists.

- The alert **stays up** until a resume succeeds. Parking suppresses
  retries, never the signal; the whole failure in this backlog item was a
  silence, and the fix must not introduce a new one.
- The counter resets to 0 on **success** or on **any operator action**
  for that camera (picker change, explicit start). An operator touching a
  camera is a statement that the situation changed, and they should not
  have to wait out a 60-minute backoff to see the effect.
- `last_attempt_at` drives the backoff, so it must be written on every
  attempt including the ones that fail.

Two failures at 60 s apart means a genuine problem is retried for about a
minute, then backs off — comfortably inside B's alert debounce, so the
operator sees one actionable "failed" rather than a flapping alert, and
the system keeps trying behind it.

#### Interaction with B

They share a signal. B reports a camera as uncovered when video is live
and inference is absent; A removes the common causes. After A, anything B
still reports is either inside the 60 s reconcile window, deliberately
switched off, or genuinely failed — and the derived `failed` flag tells
them apart. Shipping B first means the metric exists to prove A works.

### Proposal B — make the gap visible (do this one first)

**Implemented 2026-10-17.** `DeviceStreaming.inference_absent_since` on
`GET /api/v1/devices`, `state/api/coverage.ts` for the classification, a
"Monitoring coverage: N of M cameras" card above the service cards on
Settings -> System, and a red **NOT MONITORED** badge on the camera grid
cell. 20 tests in `state/api/__tests__/coverage.test.ts`, including a
reproduction of the 74004 incident.

Auto-resume reduces how often this happens; an alert is what catches it
when it happens anyway, including for reasons nobody predicted. B is
independent of A and worth shipping first because it is smaller and it
is the part that failed here — 21 hours passed with nobody knowing.

*The signal.* A camera is anomalous when **video is live and inference is
absent**. Both halves are already available in one place:
`GET /api/v1/devices` returns `streaming.video_live` and
`streaming.ai_enabled` per camera. No new endpoint is needed.

*Where it should show.*

- **System Health tab** — a row or card: "Monitoring coverage: 11 of 12
  cameras". Today the page reports service health but says nothing about
  whether cameras are actually being watched, which is the question an
  operator most needs answered.
- **Camera grid** — a distinct badge. The existing `getCameraStatus`
  returns `live | offline | disabled` from *video* state only, so a
  camera with no inference currently renders as plain "Live". Adding a
  `monitoring: on | off` dimension beside it is the minimal change.
- **Overview** — the "Cameras Live" card already reads `streaming.active`
  and so would have shown 11/12. It is correct but silent; the number
  needs a comparison to make the discrepancy legible.

*Grace period.* Inference legitimately drops out for seconds during
restarts and model changes, so alerting must debounce — a few minutes,
not seconds. Pick it deliberately: too short and every deploy pages
somebody; too long and this one still goes unnoticed for a shift.

*Cheap interim, available now,* while the above is designed — a query
that lists the gap, run from cron or checked by hand:

```sql
SELECT d.name
FROM devices d
LEFT JOIN stream_sessions s
       ON s.device_id = d.id AND s.state IN ('starting','live','stopping')
WHERE d.enabled AND d.is_active AND s.id IS NULL;
```

---

## BL-10 · Inference pacing counts frame-fetch time as GPU time

**Status:** proposed, not started · **Found:** 2026-10-17 (measuring BL-5
step A) · **Area:** backend, `app/services/inference_loop.py`

**Finding.** With BL-5's offload deployed, the store runtime is no longer
the constraint — it runs at 2 concurrent and is idle two thirds of the
time (mean concurrency 1.02). The fleet still achieves only **0.48
inferences/s per camera per model against a requested 10**. The pacing is
now fully accounted for, and it is arithmetic, not a bug hiding somewhere:

```
InferenceBudget.fps_for_consumer:
    fair_share_fps = MAX_GPU_UTILIZATION / (active_count x latency)
                   = 2.3 / (33 x 0.145)
                   = 0.48          <-- exactly what is observed
```

Three inputs produce that number, and two of them are surprising:

1. **`active_count` is 33, not 11.** Multi-model sessions register one
   consumer per *(session, model)* pair, so 11 cameras x 3 models = 33
   claimants on one budget. Correct by design, but it means adding a
   model to every camera cuts every existing model's rate by a third.

2. **`latency` is 145 ms, of which only 65 ms is GPU.** Line 1020 records
   `fetch_seconds + inference_time` into the budget:

   ```python
   self._budget.record_latency(entry["model_id"], fetch_seconds + clock() - started)
   ```

   So **55% of a budget named MAX_GPU_UTILIZATION is spent on frame-fetch
   I/O**, which does not occupy the GPU at all. The GPU sits at 32% while
   the budget behaves as though it were nearly full.

3. **The backend serialises models within a tick on purpose** (`_run_due_models`,
   M1.2 fastest-first: `for i in order: await self._run_model(...)`). That
   is a deliberate latency choice — a fast model's GPU work never shares
   the device with a slow one — and it means concurrency can only ever
   come from *different cameras*. Raising a semaphore cannot create
   within-tick parallelism.

**Impact.** The plant runs at ~5% of its requested detection rate with a
GPU at 32% and a runtime idle two thirds of the time. Every lever tried so
far (BL-5 offload, the store semaphore) sits downstream of this one.

**Proposal — three candidate changes, in order of leverage per unit of risk.**

**(a) PARKED 2026-10-18 — do not enable without reading BL-12.**
The premise behind (a) was that fetch is a steady ~80 ms cost unfairly
charged to the GPU budget. Measuring it showed the mean is right (122 ms)
but the shape is not: fetch is **bimodal** — 37 ms for 94% of ticks and
over a second for 6% (BL-12). That 6% is a fault, not a budgeting error.

Two consequences:

- Excluding fetch from the budget would make the system pace as though
  fetch were free while one tick in sixteen still blocks for 1.3 s. The
  budget is a crude throttle, but it is currently the only thing
  *responding* to the stalls. Removing it masks BL-12.
- **If (a) is ever revived, the interval floor must use a high percentile
  of fetch, not the EWMA.** `min_tick_seconds` currently floors at
  `fetch_estimate() + latency`, where `fetch_estimate()` is an EWMA — and
  an EWMA of a bimodal distribution sits near neither mode. It would
  under-floor the 6% of ticks that matter, which is exactly the case the
  floor exists to protect. Track a p90/p95 of fetch instead.

The flag ships off and stays off. The code and tests remain, so reviving
it is a configuration change plus the floor fix above.

**(a) implemented 2026-10-17, shipped dark.**
`RUTH_BUDGET_EXCLUDE_FETCH` (default false) makes `record_latency` take
inference time only. `fetch_seconds` is still recorded separately, into a
fleet-wide EWMA, because the *scheduler* still needs it: a tick costs a
fetch plus an inference in wall time whatever the GPU is doing, so
`_multi_interval` is floored at `fetch + inference`. Without that floor
the freed budget could hand back an interval shorter than the work it
schedules, and the loop would fire every iteration immediately — spinning
without gaining throughput. The floor is unconditional and inert today
(a tick costs ~0.145 s against a ~2.3 s interval).

Also added: sampled `Frame fetch` logging (`RUTH_FETCH_LOG_SAMPLE`,
default 0.02) plus an unconditional line for any fetch over
`RUTH_SLOW_FETCH_SECONDS` (0.5). `fetch_seconds` has been measured on
every tick since multi-model sessions shipped and thrown straight into
the budget, so its distribution has never been looked at — the 80 ms
below is inferred from the achieved rate, and the flag should not be
enabled until it is observed. Tests: `tests/unit/test_budget_exclude_fetch.py`
(27), covering flag-off equivalence and the anti-spin floor across fleet
sizes 1-100.

- *(a) Stop counting fetch time as GPU time.* Record only the inference
  duration into the budget and account for fetch separately. On today's
  numbers this alone moves fair-share from 0.48 to
  `2.3 / (33 x 0.065)` = **1.07/s per consumer, a 2.2x gain**, with no
  change to how hard the GPU is driven — it is a correction, not a
  loosening. Needs care: fetch time is real wall-clock that limits how
  fast a camera *can* tick, so it belongs in the schedule, just not in
  the GPU budget.
- *(b) Raise `RUTH_INFERENCE_MAX_GPU_UTIL` above 2.3.* The blunt lever.
  With (a) applied, 2.3 -> 4.0 would give `4.0 / (33 x 0.065)` = 1.86/s
  per consumer. Only worth doing after (a), and only with GPU headroom
  confirmed at the new rate.
- *(c) Scope the budget per runtime.* The store models and the built-in
  models are served by different processes on the same GPU but are
  currently paced from one shared budget — the same conflation BL-5's
  semaphore split fixed for concurrency. Splitting the budget would let
  store models be paced on their own measured latency without changing
  built-in behaviour. Largest change of the three; do last if at all.

**Can it be scoped to store models only?** Partly. `MAX_GPU_UTILIZATION`,
`TARGET_FPS` and `MIN_FPS` are module-level and shared, so (b) alone
cannot be scoped — raising it speeds built-in models up too. (a) is
naturally scoped in the sense that it is a correctness fix applying
equally to both, and is the safer thing to apply globally. True per-runtime
scoping is (c).

**Measurement plan.** Same instrument as BL-5, which now has a baseline to
compare against:

```bash
python3 docs/tools/measure_inference_concurrency.py --minutes 10 \
    --label pre_c --out /tmp/pc
# apply (a) only
python3 docs/tools/measure_inference_concurrency.py --minutes 10 \
    --label post_a --out /tmp/pc
python3 docs/tools/measure_inference_concurrency.py --compare \
    /tmp/pc/pre_c.json /tmp/pc/post_a.json
```

Expected after (a): per-consumer 0.48 -> ~1.07/s, fleet ~16 -> ~35 req/s,
GPU 32% -> ~55-65%, p95 up from 114 ms (contention). Stop conditions as
BL-5: p95 > 250 ms, any error lines, any runtime restart, violation rate
falling. **One change at a time** — (a) and (b) together cannot be told
apart afterwards.

Worth confirming first, cheaply: instrument `fetch_seconds` into a log
line or a metric. It is measured in the loop today and then discarded into
the budget, so the 80 ms figure above is inferred from the observed rate
rather than measured directly. If fetch is in fact slower or more variable
than that, (a) matters even more and the fetch path itself becomes a
target.

**Note on the built-in runtime being retired.** Once every model arrives
by upload, option (c) stops being "protect the built-in path" and becomes
simply *the* budget. That removes the main objection to (b): raising
`MAX_GPU_UTILIZATION` would no longer speed up a path whose concurrency
has never been validated, because there would be no such path. Re-rank
(b) upward when that happens.

---

### (d) Cross-camera batching — the largest gain, and the largest redesign

**Where the time actually goes.** Decomposing the measured 65 ms against
the GPU reading (32% at 16.0 inf/s):

| | |
|---|---:|
| GPU kernel time | **20 ms (31%)** |
| CPU-side: JPEG decode, letterbox, NMS, HTTP, Python dispatch | **45 ms (69%)** |

**Two thirds of an "inference" is not inference.** That is what batching
attacks: the per-call share of those 45 ms is paid once per call instead
of once per frame, and a 3090 at imgsz 1280 batch-1 is badly
under-occupied.

**Estimated gain** (per model stream; assumes ~60% of CPU cost is
per-call and GPU/frame improves 20 → 12 ms with occupancy):

| batch | ms/frame | inf/s | GPU | speedup |
|---:|---:|---:|---:|---:|
| 1 (today) | 65.0 | 15.4 | 31% | 1.0x |
| 4 | 38.8 | 25.8 | 36% | **1.7x** |
| 8 | 33.4 | 30.0 | 36% | **1.9x** |
| 16 | 30.7 | 32.6 | 36% | 2.1x |

Returns flatten past batch 8 because the residual per-frame CPU cost
(decode, NMS) does not amortise. **Batching alone is worth ~2x, not 10x**
— the CPU-side work is the ceiling, and the real prize may be moving
decode/NMS off the critical path rather than batching per se. VRAM is a
non-issue: 4.5 GB of 24 GB used today, and yolov8m at 1280 batch-8 adds a
few GB.

**The cost nobody sees until it bites — batch fill time:**

| | batch 4 | batch 8 |
|---|---:|---:|
| today (12 cams x 0.44/s per model) | **0.76 s** | **1.52 s** |
| after Step C(a), scenario (ii) | 0.23 s | 0.45 s |

A batch of 8 today would wait **1.5 s to assemble a call that runs in
0.065 s** — adding 23x the inference time in latency to save 50% of it.
**Batching must come after (a), not instead of it**, and even then needs
a max-wait timeout that flushes partial batches (100-200 ms) so a quiet
site does not accumulate stale frames. There is a mild chicken-and-egg:
batching raises the ceiling, a higher ceiling fills batches faster.

**What it does to the pacer.** This is the part that makes (d) a redesign
rather than a feature:

- `record_latency` currently stores per-inference duration. With
  batching, one call covers N frames, so it must record *per-frame
  effective* latency or the budget will think the system got 8x slower
  and throttle to nothing.
- `MAX_GPU_UTILIZATION` is a sum of `latency x rate` across consumers.
  Under batching that product no longer means GPU occupancy at all —
  frames share a call. The budget would need to model calls, not frames.
- The backend's deliberate within-tick serialisation (`_run_due_models`,
  fastest-first) is per-camera. Batching is inherently *cross*-camera, so
  frames must be collected from independent camera loops into a shared
  per-model queue — a scheduler change in the backend, not just a runtime
  one.
- The store plugin contract assumes one frame per call
  (`model.predict(frame)`), so manifests would need something like
  `supports_batch` / `max_batch`, and `ai/store_plugin/inference.py`
  would need a list-accepting path.

**Recommended order:** (a) first — it is a correctness fix worth 2.2x on
its own, with no architectural change. Measure. Then reconsider (b) and
(d) against what is actually binding at that point; if the GPU is at
~71% as predicted, (d)'s 2x is no longer available without also
addressing the 69% CPU-side cost.

---

## BL-9 · `tank_overflow_monitoring` reports as "(invalid)" while running fine

**Status:** parked · **Found:** 2026-10-17 (HPCL live check) · **Area:** AI
runtime, `ai/runtime/discovery.py`, `ai/runtime/loader.py`

**Finding.** `/capabilities` returns this model with
`display_name: "tank_overflow_monitoring (invalid)"` yet
`state: "ready", health: "healthy"` — and it genuinely is healthy. It is
loaded on the GPU and serving. Exact sequence from the runtime log:

```
discovery: "Version discovered but invalid"
           errors: ["Required directory 'weights/' not found"]
registry:  Version registered           state=invalid
loader:    "Tank overflow detector loaded successfully"
loader:    Model loaded successfully    load_time_ms=14  device=cuda:0
registry:  Version state changed        old_state=invalid  new_state=ready
```

Two independent defects produce this:

1. **The validator requires a `weights/` directory.** This model is a pure
   geometry tank detector with no weights —
   `ai/models/tank_overflow_monitoring/1.0.0/` contains only
   `inference.py`, `model.yaml` and `tank_detector.py`. It fails a rule
   that does not apply to it.
2. **`display_name` is stamped once at discovery and never refreshed.**
   `discovery.py:235` sets `display_name=f"{model_id} (invalid)"` on the
   invalid descriptor. The loader then succeeds and the registry corrects
   the **state** to `ready`, but nothing anywhere rewrites the name —
   neither `loader.py` nor `registry.py` touches that field. The model's
   own `model.yaml` already says `display_name: "Tank Overflow Monitoring"`.

Defect 2 is the more general one: *any* model that fails validation and is
then loaded successfully keeps a wrong name for the life of the process.

**Impact.** Cosmetic today, but actively misleading: the Settings → AI
Models list and the System tab both show a working model labelled
"(invalid)", which invites someone to "fix" a model that is fine. It also
defeats the backend's own guard — `app/api/v1/models.py` filters entries
with `state == "invalid"`, which never matches here because by the time
the backend asks, the state is legitimately `ready`.

**Proposal (two parts, independently shippable).**

- *Validator:* make `weights/` optional. A model that declares no weights
  in its `model.yaml` should not be required to carry an empty directory.
  Prefer keying off the manifest rather than special-casing this model id.
- *Loader/registry:* on a successful load, refresh the descriptor's
  `display_name` from the manifest — or stop deriving it at discovery and
  read it from `model.yaml` at the point of use. Then a model that
  recovers stops advertising the failure it recovered from.

Worth doing together with a check that no other model is silently in this
state: `curl -sS <runtime>/capabilities | grep invalid`.

---

## BL-8 · Fullscreen camera page shows only the video

**Status:** parked (work on fullscreen later) · **Found:** 2026-10-04 (M3
live check, step 7) · **Area:** frontend, `pages/CameraFullscreenPage.*`

**Finding.** Opening a camera fullscreen (⤢ on a grid tile →
`/cameras/fullscreen/:id`) shows only the video feed. The page's code
renders a header (close button, status) and an info panel below the video
(camera info, the AI detection list — read-only since M3 — and today's
violations), but none of it appeared. Not investigated; one lead:
`.camera-fullscreen-page` is a `100vh` flex column and the video container
is `flex: 1`, so the info panel may be pushed off-screen or clipped.

Related, from the M3 check:
- The page's device data is fetched once, with no polling; it refreshes
  only on tab focus after 30 s (app-wide `staleTime`) or on reload, so the
  AI list can lag changes made in the grid.
- "Today's violations" is a static placeholder ("No violations detected
  today", count 0).

**Proposal.** When fullscreen is picked up: make the header and info panel
visible (layout fix, check at common viewport sizes), decide whether the
AI list polls (e.g. with the devices list interval) and wire the violations
section to real data.

---

## BL-7 · Multi-model overlay styling should count only models that drew person boxes

**Status:** parked · **Found:** 2026-10-04 (M3 live check) · **Area:** frontend overlay

**Finding.** `LiveVideoPlayer.tsx:177-184` applies the multi-model styles
(label prefixes, PPE dashed box, PPE label one row up) when **two or more of
fall, PPE, tank and chane have a result** this frame. Geo is never counted
(its zones are drawn separately; its person boxes aren't drawn), so fall +
geo is correctly unstyled. Two cases are not:
- tank and chane count although they draw no person labels: fall + tank
  prefixes fall's labels with nothing to tell them apart from;
- a result with nothing in it still counts: fall + PPE with no PPE person
  still prefixes fall's labels.

**Proposal.** Count only models that draw person boxes **and** have at least
one to draw this frame (today: fall and PPE). Single-model output stays
identical (golden tests in `components/video/__tests__` must keep passing);
add cases for fall + tank, fall + empty PPE, fall + PPE with persons.

---

## BL-6 · Geo/tank setup modal: rectangle mode, loaded zones, edits overwritten

**Status:** parked · **Found:** 2026-10-04 (M3 live check) · **Area:**
frontend, `GeofenceSetupModal.tsx`, `VideoCanvas.tsx`, `ROICanvas.tsx`
(unchanged since `2722551`; not caused by M2/M3)

**Findings.**
1. **Rectangle mode looks broken.** The drag works and stores 4 corners
   (TL, TR, BR, BL), enabling Apply, but `ROICanvas.tsx:44-47` draws from
   `corners[0]` to the *last* corner (BL): a zero-width rectangle, so the box
   disappears on release.
2. **Mouse-up off the image leaves the drag stuck** (`isDrawing` stays true);
   there is no handler for leaving the canvas or a window-level mouse-up.
3. **A saved zone looks empty when the modal opens.** The zone is loaded
   (`initialConfig` → corners), but the modal always opens in Rectangle mode,
   which draws it with the same bug as a sliver; switching to Manual calls
   Reset and erases it ("Click the top-left corner").
4. **Edits can be overwritten.** The modal re-reads `initialConfig` in an
   effect keyed on its reference, so a refetch that changes the camera's
   config while the modal is open replaces the points being edited.

**Proposal.**
- Draw a 4-point zone as a polygon in both modes (or rectangle from
  `corners[0]` to `corners[2]`).
- End the drag on leaving the image (or a window mouse-up).
- Open in Manual mode when a saved zone exists, Rectangle only for an
  axis-aligned rectangle; a mode switch keeps a loaded zone, only Reset clears.
- Read the initial config once per opening.
- Display/editing only: the saved config format is unchanged. Used by
  geo_fencing and tank_overflow_monitoring setup, so it needs sign-off under
  the existing-paths constraint.

---

## BL-5 · Runtime serializes all inference across cameras (blocking call in an async handler)

**Status:** parked — revisit after Model Store Step 5 · **Found:** 2026-10-04 ·
**Area:** AI runtime (existing path)

**Finding.** `ai/server/routes/inference.py:310` (`async def submit_inference`)
calls `sandbox_manager.execute(...)` synchronously at line 379. That blocks
the runtime's event loop for the whole inference, so the runtime serves **one
request at a time across all cameras and models**, even though the container
runs with `MAX_CONCURRENT_INFERENCES=10` and `ai/runtime/concurrency.py`
defines per-model limits. Runtime logs show it directly: a request is only
"received" after the previous one "completed".

**Measurements (2026-10-04, demo camera fall+PPE while DEMO-CAMERA2 ran PPE).**
Attributed exactly via the runtime's per-request logs (`stream_id`,
`model_id`), joined with the backend's frame reads:

| | Median |
|---|---|
| Fall alone: frame read → fall response | 110 ms (136 ticks) |
| Fall alone: wait before the runtime receives the request | 21 ms |
| Fall alone: runtime `inference_time_ms` | 72 ms |
| Fall+PPE: frame read → first response | **415 ms** (190 ticks) |
| Fall+PPE: wait before the runtime receives the fall request | **344 ms** |
| Fall+PPE: PPE response after fall's | 287 ms |
| PPE `inference_time_ms` (either camera) | ~370 ms |

Within a tick the M1.2 order is correct (fall first in 170 of 190 ticks); the
delay is the fall request queuing behind **another camera's** 370 ms PPE
inside the runtime. The M1.2 live check (first response ≤ max(1.5× solo,
solo + 40 ms)) therefore fails whenever another camera is inferring, for a
reason outside the backend loop.

Per-model publish rates in that window: fall 1.98/s alone, then fall 1.16/s
and PPE 1.19/s together, with DEMO-CAMERA2's PPE also running.

**Impact.** Every added camera or model lengthens every other model's
latency by the full duration of whatever is ahead of it; a slow uploaded
model would delay all built-in ones. Running uploaded models alongside
built-in ones (Step 5) makes this more visible.

**Confirmed at scale on the HPCL store deployment (2026-10-17).** 11
cameras x 3 store models (`gloves`, `hard_hat`, `safety_vest`), measured
over a 10-minute window by pairing every runtime request to its completion
by `request_id`:

| | |
|---|---|
| paired spans | 9,670 |
| **max concurrent in-flight** | **1** |
| overlapping spans | **0** |
| idle gap between spans, p50 | 6.5 ms |
| runtime busy | 69.4% (416.6 s of 600 s) |
| aggregate throughput | 16.1 inferences/s |
| mean latency | 43.1 ms (p95 ~86 ms) |
| GPU utilisation | 22-41%, median 26%; VRAM 17% |
| achieved per camera per model | 0.49/s against a requested 10 |

Not one request in 9,670 overlapped another. **The GPU is not the
constraint** — this invalidates the note previously carried at
`inference_loop.py:110`, which concluded the GPU was binding from a
measurement taken against the built-in runtime (that comment has been
corrected in place). A second, independent cap sits in the backend:
`INFERENCE_CONCURRENCY = 2` (`inference_loop.py:121`), so **raising either
one alone changes almost nothing** — they must move together.

**Proposal (to evaluate after Step 5).**
- Run the blocking `execute` off the event loop (`await
  asyncio.to_thread(...)` or a bounded executor), so `MAX_CONCURRENT_INFERENCES`
  and the per-model limits in `concurrency.py` actually apply.
- Measure GPU behaviour with true concurrency (contention may lengthen each
  inference; the gain is that a fast model no longer waits for a slow one).
- Optionally a priority or per-model queue so fast models are never queued
  behind slow ones.
- This changes an existing runtime path used by all 5 models: needs explicit
  sign-off and a before/after latency run per model.

**Tool:** `docs/tools/measure_inference_concurrency.py` — committed because
this question has now been asked twice and answered twice with a throwaway
script, and the answer changed between them. Read-only; run it against a
live deployment:

```bash
python3 docs/tools/measure_inference_concurrency.py --minutes 10 \
    --label baseline --out /tmp/p1
# ... make the change ...
python3 docs/tools/measure_inference_concurrency.py --minutes 10 \
    --label after --out /tmp/p1
python3 docs/tools/measure_inference_concurrency.py \
    --compare /tmp/p1/baseline.json /tmp/p1/after.json
```

`--compare` prints the before/after table and evaluates the stop
conditions below. The older `check_fastest_first_rt.py` (scratch) produced
the 2026-10-04 table above.

**Fix, as built (2026-10-17), awaiting the deploy window.**
`RUTH_RUNTIME_OFFLOAD_INFERENCE` gates the thread hand-off in
`ai/server/routes/inference.py`; off by default, so the built-in runtime is
byte-identical (`ai/tests/test_inference_offload.py` asserts the two
branches forward identical arguments and that the flag defaults off).
`RUTH_STORE_INFERENCE_CONCURRENCY` gives uploaded models their own backend
semaphore so the two runtimes stop throttling each other; also defaults to
2, so nothing changes until both are raised deliberately.

Thread safety was checked first, offline, against the frozen frames in
`/mnt/storage/ruth-models/eval/2026-10-17/frames/`: 4 threads x 5 repeats
x 32 frames per model, comparing every box against a serial ground truth.
All three store models returned byte-identical results with zero errors
across 480 concurrent calls, so **no per-model lock is needed**.

**Deployed on the store runtime, 2026-10-17 10:06 UTC.** The flag alone,
with the backend budget left at 2:

| | baseline | after |
|---|---:|---:|
| max concurrent | **1** | **2** |
| overlapping pairs | 0 of 8,141 | 8,236 of 9,597 |
| requests/s | 13.57 | 15.99 |
| latency mean / p95 ms | 50.0 / 97.0 | 65.2 / 114.5 |
| runtime busy | 67.8% | 104.2% |
| GPU util mean | 29.8% | 32.5% |
| fleet publications/s | 14.03 | 14.53 |
| error lines | 0 | 0 |

Serialisation is gone — zero overlapping spans became 8,236. The latency
rise is the expected contention trade, well inside the 250 ms stop
condition, and buys the property that actually mattered: a fast model no
longer waits behind a slow one.

**The end-to-end gain is only +4% on fleet publications, and the reason
matters.** Step B (raising `RUTH_STORE_INFERENCE_CONCURRENCY`) was
prepared and then *not* applied, because the measurement showed the
semaphore is not the constraint:

```
mean concurrency        1.02   (semaphore allows 2)
time at concurrency >=2 33.2%
```

The budget of 2 sits idle two thirds of the time. At 65 ms mean, two slots
could serve ~30 req/s; the runtime is serving 16. The limiter has moved
upstream to `InferenceBudget` (`RUTH_INFERENCE_TARGET_FPS` 2.0,
`RUTH_INFERENCE_MIN_FPS` 0.2, `RUTH_INFERENCE_MAX_GPU_UTIL` 2.3), which
paces every camera deliberately and is what holds the fleet near 0.5
ticks/s per camera. **This corrects the expectation recorded above** that
the two changes had to move together: they do, but the second one is the
pacer, not the semaphore.

Raising the pacer is tracked separately as BL-10 — it touches the budget
shared with built-in models, so it needs its own scoping and before/after.

One defect found and fixed during the deploy: the startup line confirming
the flag never printed. `ai/server/main.py` imports the routes module
before the lifespan calls `configure_logging()`, so a module-level
`logger.info` is emitted against an unconfigured logging system and
dropped. It read exactly like the flag failing, when the flag was active.
The value is now exposed as `inference.offload_status()` and logged from
the lifespan; `ai/tests/test_inference_offload.py` covers it.

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
