# Start New Project — migration notes and deploy sequence

Admin action that archives a finished project's detection data so a new site
or campaign begins with 0 open alerts, 0 violations and clean analytics.
**Nothing is deleted and no file on disk is moved.**

- UI: `/admin/projects` (behind the admin login, linked from Model Management)
- API: `GET|POST /api/v1/admin/projects{,/preflight,/start}`
- CLI: `python -m scripts.start_new_project`

---

## 1. Why archive tables rather than a `project_id` filter

Not one dashboard number in this product is stored. The "116,941 Open Alerts"
figure is `SELECT count(*) FROM violations WHERE status='open'` — no time
bound — re-evaluated on every poll
([violations.py:152](../ruth-ai-backend/app/api/v1/violations.py#L152)).
Analytics, the shift badges, the exports and the alerts badge are all live
aggregates over the same five tables.

Two consequences decided the design:

1. **There is no counter to reset.** Emptying the tables *is* the reset, and
   it needs no new code in any read path.
2. **One reader cannot be taught to filter.** The NLP chatbot is text-to-SQL
   against this same database, with a hardcoded schema prompt and regex
   fallbacks that literally contain `SELECT COUNT(*) FROM violations`
   ([chat_service.py:224](../ruth-ai-nlp-chat/app/services/chat_service.py#L224)).
   A `project_id` or `created_at >= start` scheme would have to be applied
   correctly in ~40 query sites *and* inside LLM-generated SQL. Moving the
   rows makes "starts at zero" true of the data itself.

So: `violations`, `events`, `evidence`, `stream_sessions` and
`bookmark_analyses` move into `*_archive` twins. **Zero existing read paths
changed.**

Three deliberate differences in the archive tables
([archive.py](../ruth-ai-backend/app/models/archive.py)):

| | Why |
|---|---|
| No foreign keys | The archive must survive a device being retired and the live tables being rebuilt. UUIDs are kept as plain columns. |
| Enums stored as text | `violation_type` gains and loses values as models ship. An archive referencing the live enum type would break retroactively when a value was removed. |
| One index per table | Append-only, read rarely. Also keeps the archiving INSERT cheap. |

---

## 2. Measured on the live database (2026-10-16)

| Table | Rows | Size |
|---|---:|---:|
`violations` | 116,953 | 103 MB |
`evidence` | 116,937 | 36 MB |
`events` | 13,318 | 9.4 MB |
`stream_sessions` | 79 | 232 kB |
`bookmark_analyses` | 0 | — |
| **Total** | **247,287** | **~150 MB** |

Open violations: **116,941** (the dashboard figure). Violations span
2026-07-24 → 2026-10-16.

**Verified end to end on a restored copy of this exact data:** archive ran in
**12.9 s**, all five live tables went to 0, the Open Alerts query returned 0,
and a full restore brought back 116,941 open alerts with all 13,318
event→violation links intact. Comfortably one transaction; no batching
needed.

---

## 3. The FK ordering, which is the one real correctness hazard

The foreign keys are asymmetric:

```
events.violation_id          ON DELETE SET NULL
events.stream_session_id     ON DELETE SET NULL
evidence.violation_id        ON DELETE CASCADE
violations.stream_session_id ON DELETE SET NULL
```

Delete `violations` before `events` are copied and **every archived event
silently loses its violation link** — no error, and the row counts still
balance. Delete `violations` before `evidence` is copied and the evidence
rows are cascaded away entirely.

The archiver therefore **copies everything first**, verifies every live row
has an archived twin (and raises, rolling back, if not), and only then
deletes in the order `events → evidence → violations → stream_sessions →
bookmark_analyses`. Restore inserts in the exact reverse. Both orderings are
covered by named tests in
[tests/projects/test_archive.py](../ruth-ai-backend/tests/projects/test_archive.py).

---

## 4. Migrations

Two, both additive. **Neither touches an existing column, index or row**, so
the backend behaves identically until the new admin action is used.

| Revision | Down-revision | What |
|---|---|---|
`add_projects_and_archive` | `stream_session_models` | Creates `projects` + the five `*_archive` tables |
`add_device_enabled` | `add_projects_and_archive` | Adds `devices.enabled` (default `true`) + its index |

Notes:

- **`add_projects_and_archive` can be applied with the backend up.** It only
  creates empty tables.
- **`add_device_enabled` backfills `true`.** Correct: a camera is enabled
  unless VAS says otherwise, and the next device sync (on startup or via
  `POST /internal/sync/devices`) corrects the ones that are not. At authoring
  time 3 of VAS's 15 devices are disabled, so expect 3 cameras to disappear
  from the default camera list after the first sync.
- **Downgrade refuses while any archive table holds rows**, rather than
  silently destroying a closed project's history. Verified — it lists the
  per-table counts and aborts. Empty, it drops cleanly.
- `projects` carries a partial unique index `uq_projects_one_active` on
  `state = 'active'`, so two concurrent starts cannot both commit even if the
  advisory lock were bypassed.

---

## 5. Deploy sequence

Backup **before** migrating. The migrations are additive and reversible, but
`add_device_enabled` is a table rewrite candidate and the whole point of this
feature is not losing data.

```bash
# ── 0. Backup, before anything else ────────────────────────────────────────
docker exec ruth-ai-vas-postgres pg_dump -U ruth -d ruth_ai -Fc \
  -f /tmp/pre-projects-$(date -u +%Y%m%dT%H%M%SZ).dump
docker cp ruth-ai-vas-postgres:/tmp/pre-projects-*.dump ./backups/
# Verify it is a readable archive, not just a non-empty file:
pg_restore -l ./backups/pre-projects-*.dump | head

# ── 1. Prerequisite: the host backup directory (uid 1000) ─────────────────
# The image now ships postgresql-client-15 and compose bind-mounts
# ${RUTH_BACKUP_HOST_DIR:-/mnt/storage/ruth-backups} at /var/backups/ruth-ai,
# but the host directory still has to exist and be writable by appuser.
# The action REFUSES to archive without a verified dump, by design.
sudo mkdir -p /mnt/storage/ruth-backups
sudo chown 1000:1000 /mnt/storage/ruth-backups
# Confirm after the backend is up:
docker exec ruth-ai-vas-backend pg_dump --version        # expect 15.x
docker exec ruth-ai-vas-backend sh -c 'test -w /var/backups/ruth-ai && echo writable'

# ── 2. Deploy VAS first ────────────────────────────────────────────────────
# Adds POST /v2/media-paths/{snapshots,bookmarks} (scope-gated, read-only)
# and allows that prefix through the API-key middleware. No schema change.
# Ruth tolerates its absence — it just records vas_paths_resolved=false —
# but deploying VAS first means the first archive captures paths.
docker compose up -d --build vas-backend

# ── 3. Raise VAS retention to 365 days, via storage config (no code change) ─
# storage_config is currently EMPTY, so VAS is running on the code defaults
# of 30 days. This writes a row that overrides them.
#
# No token: /v2/storage/* declares no auth dependency AND is listed in
# JWT_AUTH_PREFIXES, so the API-key middleware skips it too. Verified:
# GET /v2/storage/config returns 200 unauthenticated. See the warning below.
curl -sS -X PUT "$VAS_BASE_URL/v2/storage/config" \
  -H 'Content-Type: application/json' \
  -d '{"snapshot_retention_days": 365, "bookmark_retention_days": 365}'
curl -sS "$VAS_BASE_URL/v2/storage/config"
# Check free disk first: this stops reaping snapshots at 30 days.

# ── 4. Migrate Ruth ────────────────────────────────────────────────────────
docker compose up -d --build ruth-ai-backend
docker exec ruth-ai-vas-backend alembic current      # stream_session_models
docker exec ruth-ai-vas-backend alembic upgrade head
docker exec ruth-ai-vas-backend alembic current      # add_device_enabled

# ── 5. Sync devices, so `enabled` reflects VAS ─────────────────────────────
curl -sS -X POST http://localhost:8090/internal/sync/devices
# Expect the 3 VAS-disabled cameras to drop out of the default camera list.

# ── 6. Deploy the frontend ─────────────────────────────────────────────────
docker compose up -d --build ruth-ai-frontend

# ── 7. Smoke test without archiving anything ───────────────────────────────
TOKEN=$(curl -sS -X POST http://localhost:8090/api/v1/admin/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"'"$RUTH_ADMIN_USERNAME"'","password":"'"$RUTH_ADMIN_PASSWORD"'"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

# Read-only; mutates nothing. Should report the row counts and any blockers.
curl -sS -H "Authorization: Bearer $TOKEN" \
  http://localhost:8090/api/v1/admin/projects/preflight | python3 -m json.tool

# Or from the CLI:
docker exec ruth-ai-vas-backend python -m scripts.start_new_project --dry-run
```

### Rollback

```bash
# Code only (archive tables stay, harmless and unread):
docker compose up -d ruth-ai-backend:<previous-tag>

# Schema too — only possible while the archive tables are empty:
docker exec ruth-ai-vas-backend alembic downgrade stream_session_models
# With archived data present this aborts and lists the counts. To genuinely
# back out after an archive: restore the batch first (step below), then
# downgrade.
```

> **Pre-existing security gap, unrelated to this work.** Every endpoint
> under `/v2/storage/*` is effectively unauthenticated: none of them declare
> `require_scope`/`get_current_user`, and the prefix is in
> `JWT_AUTH_PREFIXES`, so `api_key_middleware` waves it through on the
> assumption those endpoints "handle their own JWT auth". They do not.
> Anyone who can reach the VAS port can read and rewrite storage paths,
> retention windows and the backup schedule, and trigger media cleanup.
> Confirmed empirically: `GET /v2/storage/config` -> 200 with no credentials,
> where a correctly-gated endpoint (`GET /v2/snapshots`) -> 403. Worth
> fixing separately; it makes the retention change below easy, but for the
> wrong reason.

---

## 6. Running the action

### UI

`/admin/projects`. The page shows the server's own preflight counts, requires
the new project name to be **retyped exactly**, and refuses while inference is
live until the operator ticks **"Stop all inference and proceed"** — which
re-runs preflight so the consequence is visible before submitting. Video
streams keep running; only detection stops, and it is **not** restarted
automatically.

### CLI

```bash
docker exec -it ruth-ai-vas-backend python -m scripts.start_new_project --dry-run
docker exec -it ruth-ai-vas-backend python -m scripts.start_new_project \
    --name "Coke Drum Campaign 2026-Q4" --stop-streams
docker exec ruth-ai-vas-backend python -m scripts.start_new_project --list
```

Exit codes: `0` success, `1` refused (preflight or confirmation), `2`
operational failure (backup, database).

### Restore

Deliberately **not** on the HTTP API. Restoring 117k violations into whatever
project is running has a judgement call attached and should not sit one click
from the archive button.

```bash
docker exec ruth-ai-vas-backend python -m scripts.start_new_project --list
docker exec -it ruth-ai-vas-backend python -m scripts.start_new_project \
    --restore <archive_batch_id>
```

Refuses unless the live tables are empty — merging an archived project into a
running one cannot be undone.

---

## 7. Files on disk

**Confirmed: this action moves and deletes nothing on disk.**

- Ruth stores no media paths at all. `Evidence` holds only `vas_snapshot_id` /
  `vas_bookmark_id` and serves media by proxying to VAS.
- Files live under VAS in per-camera directories derived from
  `sanitize_dirname(device.name)` — a layout with no project concept.
- VAS's `snapshots` / `bookmarks` / `recordings` rows are not touched.

`evidence_archive` additionally captures VAS's own `file_path` /
`video_file_path` / `thumbnail_path` at archive time, via the new
`POST /v2/media-paths/*` endpoints, so an archived violation stays traceable
to a file even after VAS removes its row. `vas_paths_resolved` distinguishes
"VAS said it is gone" from "we could not ask" (VAS unreachable — which never
blocks an archive).

### Finding, as measured 2026-10-16

> Ruth holds **116,725** evidence rows referencing a VAS snapshot id. VAS
> currently holds **194** snapshots and **0** bookmarks, the oldest from
> 2026-10-04.

So **~99.8% of those ids are already dangling** — the files were reaped by the
30-day retention long before this feature existed, and no path capture can
recover them. Capturing paths is still worth doing, but its value is
**prospective**: combined with retention at 365 days (step 3), evidence
archived from the *next* project onward will be traceable. Archived evidence
from the current data set will mostly show no viewable media, and that is
pre-existing, not caused by archiving.

---

## 8. What is kept across projects

| Kept | Archived |
|---|---|
`devices` (all cameras) | `violations` |
`app_settings` (shift schedule) | `events` |
`model_store_*` (uploaded models) | `evidence` |
| | `stream_sessions` (incl. their counters) |
| | `bookmark_analyses` |

### Retiring old cameras (COKEDRUM etc.)

Cameras are **not** archived — a new project at the same plant reuses them,
and keeping the rows means archived violations still resolve their camera.

Retire a camera in **VAS**, which owns the durable policy flag:

```bash
curl -sS -X PATCH "$VAS_BASE_URL/api/v1/devices/<device_id>/enabled" \
  -H "Authorization: Bearer $VAS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"enabled": false}'
```

Ruth mirrors `enabled` on every device sync and **hides disabled cameras from
every camera list by default** (`GET /api/v1/devices?include_disabled=true`
returns them). The Cameras page has a **"Show disabled cameras"** toggle, off
by default, remembered per browser.

Do not try to express this with `is_active`: VAS resets that flag to `false`
on every boot, and Ruth's sync overwrites whatever is written there
([device_service.py](../ruth-ai-backend/app/services/device_service.py)).

---

## 9. Risks and current status

| Risk | Status |
|---|---|
Event→violation links lost to FK ordering | **Closed.** Copy-then-verify-then-delete; named test; verified on real data (13,318/13,318 links survived). |
Evidence cascaded away | **Closed.** Copied before violations are deleted; named test. |
`pg_dump` / backup volume absent from the image | **Open — deploy step 1.** The action refuses rather than archiving unbacked. |
Archived evidence unviewable | **Pre-existing, partially mitigated.** §7: 99.8% already dangling; retention at 365 days protects future projects. |
Unexpected data growth | Preflight refuses above 5,000,000 rows (currently 247k) and says so. |
Operator thinks data was deleted | Mitigated in copy: the result screen states the counts archived, the batch id and the backup path, and says "Nothing was deleted" explicitly. |
Concurrent starts | Advisory lock + partial unique index + a live re-check under the lock. |
Stale UI after archiving | Both devices-list cache variants are invalidated; react-query keys invalidated on success. |

---

## 10. Tests

```bash
# Unit (no database)
pytest tests/unit/test_project_service_unit.py

# DB-backed; needs a throwaway Postgres, skipped without it
PROJECT_TEST_DATABASE_URL=postgresql+asyncpg://ruth:ruth@localhost:5433/proj_test \
  pytest tests/projects
```

50 passed, 1 skipped (the unwritable-directory assertion cannot hold when the
suite runs as root).

**Pre-existing failures elsewhere, not caused by this work.** `tests/unit`
and `tests/integration` report 38 failures in this environment, all from two
causes that predate these changes and whose tracebacks touch none of the
files here:

- `AttributeError: ONLINE` — `tests/unit/conftest.py:349` and
  `tests/integration/conftest.py:428` reference `DeviceStatus.ONLINE`, but
  `DeviceStatus` in `app/integrations/vas/models.py` is a Pydantic model with
  no such member. Raised while building the fixture, before any service code
  runs.
- `VASAuthenticationError.__init__() got an unexpected keyword argument
  'status_code'` in `tests/unit/test_error_mapping.py`.

Worth fixing, but separately.
