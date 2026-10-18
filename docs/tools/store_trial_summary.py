"""Per-camera, per-class summary for models in trial mode."""
import sys, json, collections, statistics as st
from datetime import datetime

rows = collections.defaultdict(list)
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("{"): continue
    try: d = json.loads(line)
    except Exception: continue
    if d.get("message") == "Store detection summary":
        rows[d["model_id"]].append(d)

for model in sorted(rows):
    rs = rows[model]
    ts = sorted(datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) for r in rs)
    span = (ts[-1] - ts[0]).total_seconds() or 1
    print(f"\n{'='*86}\n{model.upper()}  —  {len(rs)} inferences over {span/60:.1f} min "
          f"({len(rs)/span:.2f}/s)   rule floor {rs[-1]['rule_floor']}, "
          f"predict floor {rs[-1]['predict_floor']}\n{'='*86}")
    bycam = collections.defaultdict(list)
    for r in rs: bycam[r.get("camera_name", "unknown")].append(r)
    classes = sorted({c for r in rs for c in r["class_summary"]})
    head = f"{'camera':10} {'n':>6} {'any det':>8}"
    for c in classes: head += f" | {c[:13]:>13} {'max':>6} {'p50':>6}"
    print(head); print("-"*len(head))
    for cam in sorted(bycam):
        rr = bycam[cam]
        anyd = sum(1 for r in rr if r["class_summary"])
        line = f"{cam:10} {len(rr):6} {anyd:7} "
        for c in classes:
            v = sorted((r["class_summary"][c]["max_confidence"] for r in rr if c in r["class_summary"]), reverse=True)
            if v: line += f" | {len(v):13} {v[0]:6.3f} {st.median(v):6.3f}"
            else: line += f" | {'-':>13} {'-':>6} {'-':>6}"
        print(line)
    # fleet totals
    tot = f"{'ALL':10} {len(rs):6} {sum(1 for r in rs if r['class_summary']):7} "
    for c in classes:
        v = sorted((r["class_summary"][c]["max_confidence"] for r in rs if c in r["class_summary"]), reverse=True)
        tot += f" | {len(v):13} {v[0]:6.3f} {st.median(v):6.3f}" if v else f" | {'-':>13} {'-':>6} {'-':>6}"
    print("-"*len(head)); print(tot)
    viol = sum(1 for r in rs if r["violation_detected"])
    above = {c: sum(1 for r in rs if c in r["class_summary"] and r["class_summary"][c]["max_confidence"] >= 0.7)
             for c in classes}
    print(f"\nplugin-level violations: {viol}   frames with a class >= 0.7 (the backend's gate): {above}")
