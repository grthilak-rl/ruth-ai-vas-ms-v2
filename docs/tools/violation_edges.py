"""How many violations would be WRITTEN if the gate were the manifest's
min_confidence instead of the session's 0.7.

The backend creates a violation on a false->true edge per (session,
model) and suppresses while it stays true (no zones for PPE), so the
count of edges in the plugin's own violation_detected signal is exactly
the number of rows that gate would produce.
"""
import csv, gzip, os, sys, collections
from datetime import datetime, timezone

ARCH = os.environ.get("ARCH", ".")
START = datetime.fromisoformat(sys.argv[1]).replace(tzinfo=timezone.utc)
END = datetime.fromisoformat(sys.argv[2]).replace(tzinfo=timezone.utc)

state = {}
edges = collections.Counter()
frames = collections.Counter()
viol_frames = collections.Counter()
first = last = None

with gzip.open(f"{ARCH}/joined.csv.gz", "rt") as fh:
    for r in csv.DictReader(fh):
        ts = datetime.fromisoformat(r["ts"].replace("Z", "+00:00"))
        if ts < START or ts > END: continue
        first = first or ts; last = ts
        key = (r["stream_id"], r["model_id"])
        v = r["violation"] == "1"
        frames[r["model_id"]] += 1
        if v: viol_frames[r["model_id"]] += 1
        if v and not state.get(key, False):
            edges[r["model_id"]] += 1
        state[key] = v

hours = (last - first).total_seconds() / 3600 if first else 1
print(f"window {first:%Y-%m-%d %H:%M} -> {last:%Y-%m-%d %H:%M} UTC ({hours:.1f} h)\n")
print(f"{'model':13} {'frames':>9} {'viol frames':>12} {'EDGES':>8} {'per hour':>9} {'per day':>9}")
print("-"*66)
for m in sorted(frames):
    e = edges[m]
    print(f"{m:13} {frames[m]:9} {viol_frames[m]:12} {e:8} {e/hours:9.1f} {e/hours*24:9.0f}")
