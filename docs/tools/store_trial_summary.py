"""Per-camera, per-class summary for store models in trial mode.

Reads "Store detection summary" lines (JSON, one per line) on stdin —
from `docker logs ruth-ai-model-store-runtime`, from an archive under
/mnt/storage/ruth-models/eval/*/trial-logs/, or both concatenated.

With --split-grey each model is also broken down by whether the frame was
greyscale (infrared / night) or colour. Confined-space cameras run IR for
much of the day, and a model trained on daylight colour can behave
completely differently on those; a fleet-wide average hides it.

    docker logs ruth-ai-model-store-runtime \\
      | python3 docs/tools/store_trial_summary.py --split-grey
"""

import collections
import json
import statistics as st
import sys
from datetime import datetime


def read(stream):
    rows = collections.defaultdict(list)
    for line in stream:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("message") == "Store detection summary":
            rows[d["model_id"]].append(d)
    return rows


def report(model, rs, label=""):
    if not rs:
        return
    ts = sorted(datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) for r in rs)
    span = (ts[-1] - ts[0]).total_seconds() or 1
    print(f"\n{'=' * 90}")
    print(f"{model.upper()}{label}  —  {len(rs)} inferences over {span / 60:.1f} min "
          f"({len(rs) / span:.2f}/s)   rule floor {rs[-1]['rule_floor']}, "
          f"predict floor {rs[-1]['predict_floor']}")
    print("=" * 90)

    bycam = collections.defaultdict(list)
    for r in rs:
        bycam[r.get("camera_name", "unknown")].append(r)
    classes = sorted({c for r in rs for c in r["class_summary"]})

    head = f"{'camera':10} {'n':>6} {'any det':>8}"
    for c in classes:
        head += f" | {c[:13]:>13} {'max':>6} {'p50':>6}"
    print(head)
    print("-" * len(head))

    def row(name, rr):
        line = f"{name:10} {len(rr):6} {sum(1 for r in rr if r['class_summary']):8} "
        for c in classes:
            v = sorted((r["class_summary"][c]["max_confidence"]
                        for r in rr if c in r["class_summary"]), reverse=True)
            line += (f" | {len(v):13} {v[0]:6.3f} {st.median(v):6.3f}" if v
                     else f" | {'-':>13} {'-':>6} {'-':>6}")
        return line

    for cam in sorted(bycam):
        print(row(cam, bycam[cam]))
    print("-" * len(head))
    print(row("ALL", rs))

    viol = sum(1 for r in rs if r["violation_detected"])
    gate = {c: sum(1 for r in rs if c in r["class_summary"]
                   and r["class_summary"][c]["max_confidence"] >= 0.7)
            for c in classes}
    print(f"\nplugin-level violations: {viol}   frames with a class >= 0.7: {gate}")


def main():
    split = "--split-grey" in sys.argv
    rows = read(sys.stdin)
    if not rows:
        print("no 'Store detection summary' lines on stdin")
        return
    for model in sorted(rows):
        rs = rows[model]
        if split and any("greyscale" in r for r in rs):
            report(model, [r for r in rs if r.get("greyscale") is True], "  [GREYSCALE / IR]")
            report(model, [r for r in rs if r.get("greyscale") is False], "  [COLOUR]")
            report(model, [r for r in rs if "greyscale" not in r],
                   "  [logged before the greyscale split existed]")
        else:
            report(model, rs)


if __name__ == "__main__":
    main()
