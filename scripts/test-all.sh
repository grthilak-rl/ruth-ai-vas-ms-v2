#!/usr/bin/env bash
# Run every Ruth AI test suite and lint; one summary line per suite.
# Exit status is non-zero if any suite fails.
#
#   make test                      (or: scripts/test-all.sh)
#
# Every run keeps each suite's full output in a dated folder:
# test-logs/<YYYYmmdd-HHMMSS>/ in the repo (git-ignored; test-logs/latest
# points at the newest; the last $TEST_LOGS_KEEP runs, default 20, are kept).
# Set TEST_LOGS_ROOT to put them elsewhere. On a FAIL the failing test names
# are printed under the summary, so a failure is never unidentified.
#
# Needs docker and node/npm. Backend suites run in a test image built from
# the deployed ruth-ai-backend image (scripts/test-runner.Dockerfile, cached
# as ruth-ai-test-runner:local). DB suites use a throwaway Postgres
# container on a private network; nothing touches the live databases.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BASE_IMAGE="${RUTH_BACKEND_IMAGE:-vas-ruthai-deploy-ruth-ai-backend}"
RUNNER="ruth-ai-test-runner:local"
RUN_ID="ruth-test-$$"
NET="$RUN_ID-net"
PG="$RUN_ID-pg"
LOGS_ROOT="${TEST_LOGS_ROOT:-$REPO/test-logs}"
LOGS="$LOGS_ROOT/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$LOGS" && ln -sfn "$(basename "$LOGS")" "$LOGS_ROOT/latest"
FAILED=0
SUMMARY=()
DETAILS=()  # per failing suite: the names of the failing tests

cleanup() {
  docker rm -fv "$PG" >/dev/null 2>&1   # -v: also its anonymous data volume
  docker network rm "$NET" >/dev/null 2>&1
  # Keep the newest TEST_LOGS_KEEP run folders (dated names sort by time).
  ls -1d "$LOGS_ROOT"/[0-9]*-[0-9]* 2>/dev/null | sort | head -n "-${TEST_LOGS_KEEP:-20}" | xargs -r rm -rf
  echo "Logs: $LOGS"
}
trap cleanup EXIT

line() {  # status, suite, detail
  SUMMARY+=("$(printf '%-8s %-26s %s' "$1" "$2" "$3")")
  if [ "$1" = FAIL ]; then FAILED=1; fi
  return 0
}

detail() {  # suite, log, names (one per line); falls back to the log's tail
  local names="$3"
  [ -n "$names" ] || names="$(sed 's/\x1b\[[0-9;]*m//g' "$2" 2>/dev/null | tail -n 15)"
  DETAILS+=("$1 ($2):" "$(sed 's/^/    /' <<<"$names")")
}

pytest_summary() {  # last pytest "=== ... ===" line, without colour or bars
  sed 's/\x1b\[[0-9;]*m//g' "$1" | grep -E '^=+ .*(passed|failed|error|skipped|no tests ran).* =+$' | tail -1 | sed -E 's/^=+ //; s/ =+$//'
}

run_pytest() {  # suite name, test path, extra docker args...
  local name="$1" path="$2"; shift 2
  local log="$LOGS/$name.log"
  docker run --rm --network "$NET" -v "$REPO":/src:ro -w /src/ruth-ai-backend \
    -e PYTHONDONTWRITEBYTECODE=1 "$@" --entrypoint python "$RUNNER" \
    -m pytest -p no:cacheprovider -q -rfEs "$path" >"$log" 2>&1
  local rc=$? s; s="$(pytest_summary "$log")"
  # A skipped DB suite means its database URL did not reach it: that is a failure here.
  if [ $rc = 0 ] && ! grep -q skipped <<<"$s"; then
    line PASS "$name" "$s"
  else
    line FAIL "$name" "${s:-exit $rc, see log}"
    # -rfEs short summary: one "FAILED path::test - reason" / "ERROR ..." /
    # "SKIPPED ..." line per test.
    detail "$name" "$log" "$(sed 's/\x1b\[[0-9;]*m//g' "$log" | grep -E '^(FAILED|ERROR|SKIPPED) ')"
  fi
}

echo "Preparing test runner and throwaway Postgres..."
docker build -q -t "$RUNNER" --build-arg BASE_IMAGE="$BASE_IMAGE" \
  -f "$REPO/scripts/test-runner.Dockerfile" "$REPO/scripts" >"$LOGS/build.log" 2>&1 \
  || { cat "$LOGS/build.log"; echo "FAIL     test runner image"; FAILED=1; exit 1; }
docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_USER=ruth \
  -e POSTGRES_PASSWORD=scratch -e POSTGRES_DB=postgres postgres:15-alpine >/dev/null
for _ in $(seq 60); do docker exec "$PG" pg_isready -U ruth -d postgres >/dev/null 2>&1 && break; sleep 1; done
sleep 1
B="postgresql+asyncpg://ruth:scratch@$PG:5432"
for db in mmtest sstest schematest ptest mstest; do
  docker exec "$PG" psql -U ruth -d postgres -qc "create database $db" >/dev/null
done
# Suites that expect a migrated database.
for db in mmtest sstest schematest; do
  docker run --rm --network "$NET" -v "$REPO":/src:ro -w /src/ruth-ai-backend \
    -e DATABASE_URL="$B/$db" --entrypoint alembic "$RUNNER" upgrade head >"$LOGS/migrate-$db.log" 2>&1 \
    || { line FAIL "migrate $db" "alembic upgrade head failed"; detail "migrate $db" "$LOGS/migrate-$db.log" ""; }
done

echo "Running suites..."
run_pytest "backend unit"            tests/unit
run_pytest "backend multi_model"     tests/multi_model     -e MULTI_MODEL_TEST_DATABASE_URL="$B/mmtest"
run_pytest "backend stream_sessions" tests/stream_sessions -e STREAM_SESSIONS_TEST_DATABASE_URL="$B/sstest"
run_pytest "backend schema"          tests/schema          -e SCHEMA_TEST_DATABASE_URL="$B/schematest"
run_pytest "backend projects"        tests/projects        -e PROJECT_TEST_DATABASE_URL="$B/ptest"
run_pytest "backend model_store"     tests/model_store     -e MODEL_STORE_TEST_DATABASE_URL="$B/mstest"

cd "$REPO/frontend"
npx vitest run >"$LOGS/frontend-vitest.log" 2>&1; rc=$?
s="$(sed 's/\x1b\[[0-9;]*m//g' "$LOGS/frontend-vitest.log" | grep -E '^ +Tests ' | sed -E 's/^ +Tests +//')"
if [ $rc = 0 ]; then
  line PASS "frontend vitest" "$s"
else
  line FAIL "frontend vitest" "${s:-exit $rc, see log}"
  # Failing files (" FAIL  src/...") and failing tests (" × ..." / " ✗ ...").
  detail "frontend vitest" "$LOGS/frontend-vitest.log" \
    "$(sed 's/\x1b\[[0-9;]*m//g' "$LOGS/frontend-vitest.log" | grep -E '^ *(FAIL|×|✗) ' | sort -u)"
fi

npx eslint . -f json -o "$LOGS/frontend-lint.json" >"$LOGS/frontend-lint.log" 2>&1
s="$(node -e '
  const r = require(process.argv[1]); let e = 0, w = 0;
  for (const f of r) for (const m of f.messages) m.severity === 2 ? e++ : w++;
  console.log(`${e} errors, ${w} warnings`); process.exit(e ? 1 : 0);
' "$LOGS/frontend-lint.json")"; rc=$?
if [ $rc = 0 ]; then
  line PASS "frontend lint" "$s"
else
  line FAIL "frontend lint" "${s:-eslint did not run, see log}"
  detail "frontend lint" "$LOGS/frontend-lint.json" "$(node -e '
    const r = require(process.argv[1]);
    for (const f of r) for (const m of f.messages) if (m.severity === 2)
      console.log(`${f.filePath.replace(process.argv[2] + "/", "")}:${m.line} ${m.ruleId || ""} ${m.message}`);
  ' "$LOGS/frontend-lint.json" "$REPO/frontend" 2>/dev/null)"
fi

line "NOT RUN" "backend integration" "legacy, hard-coded localhost DB (BACKLOG BL-18)"

echo
printf '%s\n' "${SUMMARY[@]}"
echo
if [ "$FAILED" = 0 ]; then
  echo "ALL GREEN"
else
  echo "FAILURES:"
  printf '  %s\n' "${DETAILS[@]}"
fi
exit "$FAILED"
