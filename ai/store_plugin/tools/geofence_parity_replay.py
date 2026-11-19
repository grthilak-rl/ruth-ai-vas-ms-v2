"""Side-by-side parity replay: built-in geo_fencing vs geofence (store).

Used to validate the geofence migration
(docs/model-store/GEOFENCE_MIGRATION.md). There are no saved polygons in
this deployment, so a fixed set of zones is drawn on every frame; the
built-in gets them in frame pixels, the store plugin normalised (as the
zone editor saves them), so the replay also covers the scaling.

    geofence_parity_replay.py <frames.txt> <out.json> <builtin_dir> <plugin.py> <manifest.json>

<builtin_dir> is ai/models/geo_fencing/1.0.0 (or its .disabled/ copy).
The store plugin runs from a scratch installed-layout dir whose weights are
the built-in's own yolov8n.pt, as the store upload will be.

Decision compared per frame and zone layout: what the backend records,
(violation_type, confidence) or nothing (0.7 gate for the built-in, the
manifest floor 0.7 for the store model), plus the zone ids of the people
in a zone, and the person boxes at 0.7 or above (the model-shift check).
The store plugin reports boxes to 0.1 px and confidences to 4 decimals (as
for every store model), so the built-in's values are compared at that
precision; "type_flips" counts comparisons where the recorded violation
type itself differs (none expected).

Run inside the runtime image, never against live services, e.g.:

    docker run --rm --gpus all --network none --user 0 --entrypoint sh \\
      -v $REPO/ai:/repo/ai:ro -v /mnt/storage/ruth-evidence/frames:/mnt/storage/ruth-evidence/frames:ro \\
      -v $WORK:/work -e YOLO_OFFLINE=1 -e YOLO_CONFIG_DIR=/tmp/yolo \\
      ruth-ai-unified-runtime:2026.11-gpu-required -c \\
      'python -I /repo/ai/store_plugin/tools/geofence_parity_replay.py /work/frames.txt /work/out.json \\
         /repo/ai/models/geo_fencing/1.0.0 /repo/ai/store_plugin/inference.py \\
         /repo/ai/store_plugin/manifests/geofence.json'
"""

import importlib.util
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
import time

import cv2

GATE = 0.7

# Zones in normalised coordinates (fractions of width, height).
LAYOUTS = {
    "restricted_lower_half": [
        {"id": "floor", "type": "restricted", "points": [[0.0, 0.5], [1.0, 0.5], [1.0, 1.0], [0.0, 1.0]]}],
    "restricted_concave": [
        {"id": "ell", "type": "restricted",
         "points": [[0.1, 0.2], [0.6, 0.2], [0.6, 0.45], [0.35, 0.45], [0.35, 0.9], [0.1, 0.9]]}],
    "allowed_centre": [
        {"id": "work_area", "type": "allowed", "points": [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]}],
    "two_restricted": [
        {"id": "left", "type": "restricted", "points": [[0.0, 0.0], [0.4, 0.0], [0.4, 1.0], [0.0, 1.0]]},
        {"id": "right", "type": "restricted", "points": [[0.6, 0.1], [0.95, 0.3], [0.9, 0.95], [0.65, 0.8]]}],
}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def pixel_zones(zones, shape):
    h, w = shape[:2]
    return [{**z, "points": [[x * w, y * h] for x, y in z["points"]]} for z in zones]


def normalised_zones(zones):
    return [{**z, "coords": "normalized"} for z in zones]


def main(frames_file, out, builtin_dir, plugin_src, manifest_path):
    random.random = lambda: 0.5  # the built-in saves a debug frame to /tmp on 1% of calls
    frames = [l.strip() for l in open(frames_file) if l.strip()]

    old = load(os.path.join(builtin_dir, "inference.py"), "builtin_geo")
    old_model = old._lazy_load_model()

    store = tempfile.mkdtemp()
    vdir = os.path.join(store, "geofence", "1.0.0")
    os.makedirs(os.path.join(vdir, "weights"))
    shutil.copyfile(plugin_src, os.path.join(vdir, "inference.py"))
    shutil.copyfile(manifest_path, os.path.join(vdir, "store_manifest.json"))
    os.symlink(os.path.join(builtin_dir, "weights", "yolov8n.pt"), os.path.join(vdir, "weights", "yolov8n.pt"))
    new = load(os.path.join(vdir, "inference.py"), "store_geofence")

    rows, new_ms = [], []
    for path in frames:
        frame = cv2.imread(path)
        if frame is None:
            continue
        for layout, zones in LAYOUTS.items():
            o = old._run_inference_with_model(frame, old_model, pixel_zones(zones, frame.shape),
                                              {"conf_threshold": 0.3, "iou_threshold": 0.5})
            t = time.perf_counter()
            n = new.infer(frame, {"zones": normalised_zones(zones)})
            new_ms.append((time.perf_counter() - t) * 1000)
            old_rec = ([o["violation_type"], round(o["confidence"], 4)]
                       if o["violation_detected"] and o["confidence"] >= GATE else None)
            new_rec = [n["violation_type"], round(n["confidence"], 4)] if n["violation_detected"] else None
            old_boxes = sorted([round(c, 1) for c in d["bbox"]] + [round(d["confidence"], 4)]
                               for d in o["detections"] if d["confidence"] >= GATE)
            new_boxes = sorted([round(c, 1) for c in d["bbox"]] + [round(d["confidence"], 4)]
                               for d in n["objects"])
            rows.append({
                "path": path, "layout": layout,
                "old": old_rec, "new": new_rec,
                "old_zones": sorted(d["zone_id"] for d in o["detections"] if d["in_zone"] and d["confidence"] >= GATE),
                "new_zones": sorted(d["zone_id"] for d in n["detections"]),
                "boxes_same": old_boxes == new_boxes,
                "persons_07": len(old_boxes),
            })

    decided = [r for r in rows if r["old"] or r["new"]]
    summary = {
        "frames": len({r["path"] for r in rows}),
        "comparisons": len(rows),
        "decision_same": sum(r["old"] == r["new"] for r in rows),
        "type_flips": sum((r["old"] or [None])[0] != (r["new"] or [None])[0] for r in rows),
        "zone_ids_same": sum(r["old_zones"] == r["new_zones"] for r in rows),
        "person_boxes_same": sum(r["boxes_same"] for r in rows),
        "recorded_fires_old": sum(1 for r in rows if r["old"]),
        "recorded_fires_new": sum(1 for r in rows if r["new"]),
        "by_layout": {
            lay: {"fires_old": sum(1 for r in rows if r["layout"] == lay and r["old"]),
                  "fires_new": sum(1 for r in rows if r["layout"] == lay and r["new"]),
                  "same": sum(1 for r in rows if r["layout"] == lay and r["old"] == r["new"])}
            for lay in LAYOUTS},
        "frames_with_persons_07": len({r["path"] for r in rows if r["persons_07"]}),
        "store_ms_median": round(statistics.median(new_ms), 1) if new_ms else None,
        "store_ms_p95": round(sorted(new_ms)[int(len(new_ms) * 0.95)], 1) if new_ms else None,
        "mismatches": [r for r in rows if r["old"] != r["new"] or r["old_zones"] != r["new_zones"]
                       or not r["boxes_same"]][:20],
        "decided_comparisons": len(decided),
    }
    json.dump(summary, open(out, "w"), indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k != "mismatches"}, indent=1))
    print("mismatches:", len(summary["mismatches"]))


if __name__ == "__main__":
    main(*sys.argv[1:6])
