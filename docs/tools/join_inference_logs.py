"""Join 'request received' (has stream_id) to 'completed' (has the
plugin's violation_detected) on request_id.

The runtime logs the two halves separately, so neither line alone says
"camera X was in violation at time T" — which is what counting violation
*transitions* needs.
"""
import sys, json, csv
pending = {}
w = csv.writer(sys.stdout)
w.writerow(["ts", "model_id", "stream_id", "violation", "detection_count"])
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("{"): continue
    try: d = json.loads(line)
    except Exception: continue
    msg = d.get("message")
    rid = d.get("request_id")
    if msg == "Inference request received":
        pending[rid] = (d["timestamp"], d.get("model_id"), d.get("stream_id"))
    elif msg == "Inference completed successfully":
        got = pending.pop(rid, None)
        if not got: continue
        ts, model, stream = got
        w.writerow([ts, model, stream,
                    int(bool(d.get("violation_detected"))),
                    d.get("detection_count") or 0])
