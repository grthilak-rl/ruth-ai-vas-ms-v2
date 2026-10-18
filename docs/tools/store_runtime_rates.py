"""Per-model rate from store-runtime logs.

Consumers are counted from the live sessions, not assumed to be
cameras x models: once one model runs on a subset of cameras that
assumption is wrong, and it silently understates per-consumer rate.
"""
import sys, json, subprocess, collections, statistics as st
from datetime import datetime

def live_consumers():
    """{model_id: n_cameras} from stream_sessions."""
    sql = ("select m->>'model_id', count(*) from stream_sessions s, "
           "lateral jsonb_array_elements(s.models) m where s.state='live' group by 1;")
    out = subprocess.run(
        ["docker", "exec", "ruth-ai-vas-postgres", "sh", "-c",
         f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "{sql}"'],
        capture_output=True, text=True)
    per = {}
    for line in out.stdout.strip().splitlines():
        if "|" in line:
            k, v = line.rsplit("|", 1)
            per[k.strip()] = int(v)
    return per

lat=collections.defaultdict(list); times=collections.defaultdict(list)
viol=collections.Counter(); nz=collections.Counter()
for line in sys.stdin:
    line=line.strip()
    if not line.startswith("{"): continue
    try: d=json.loads(line)
    except Exception: continue
    if d.get("message")=="Inference completed successfully":
        m=d["model_id"]
        lat[m].append(d["inference_time_ms"])
        times[m].append(datetime.fromisoformat(d["timestamp"].replace("Z","+00:00")))
        if d.get("violation_detected"): viol[m]+=1
        if d.get("detection_count"): nz[m]+=1
if not lat:
    print("no completions in window"); sys.exit()

per = live_consumers()
allts=sorted(t for v in times.values() for t in v)
span=(allts[-1]-allts[0]).total_seconds() or 1
print(f"window {allts[0]:%H:%M:%S}-{allts[-1]:%H:%M:%S} UTC ({span/60:.1f} min)\n")
print(f"{'model':13} {'cams':>4} {'n':>7} {'rate/s':>7} {'per-cam':>8} {'p50ms':>6} {'p95ms':>6} "
      f"{'frames w/det':>12} {'viol':>5}")
print("-"*82)
tot=0; totcons=0
for m in sorted(lat):
    v=sorted(lat[m]); r=len(v)/span; tot+=r
    c=per.get(m, 0); totcons+=c
    print(f"{m:13} {c:4} {len(v):7} {r:7.2f} {(r/c if c else 0):8.3f} "
          f"{v[len(v)//2]:6.1f} {v[int(len(v)*.95)]:6.1f} {nz[m]:12} {viol[m]:5}")
print("-"*82)
print(f"{'TOTAL':13} {totcons:4} {sum(len(v) for v in lat.values()):7} {tot:7.2f} "
      f"{(tot/totcons if totcons else 0):8.3f}")
print(f"\nconsumers (camera x model, from live sessions): {totcons}")
print(f"per consumer: {tot/totcons:.3f}/s = one frame every {totcons/tot:.1f}s")
