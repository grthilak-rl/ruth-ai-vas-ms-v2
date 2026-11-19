"""Side-by-side parity replay: built-in fall_detection vs fall_pose (store).

Used to validate the fall_pose migration (docs/model-store/FALL_POSE_MIGRATION.md).
Each mode runs in its own process so GPU memory figures are per model.

    fall_parity_replay.py old   <list> <out.jsonl>
        built-in fall_detection (YOLOv7-w6-pose), plus the store pose_fall
        rule applied to the built-in model's own keypoints (rule parity)
    fall_parity_replay.py store <list> <out.jsonl> <version_dir>
        store plugin infer() from an installed-layout version dir

<list> is a file of image paths (one per line). Output is one JSON line per
frame; "old"/"new"/"rule_on_old_kpts" are what the backend would record:
[violation_type, confidence] or null (0.7 gate applied, as for built-ins).

Run inside the runtime image, never against live services, e.g.:

    docker run --rm --gpus all --network none --user 0 --entrypoint sh \\
      -v $REPO/ai:/repo/ai:ro -v /mnt/storage/snapshots:/mnt/storage/snapshots:ro \\
      -v /mnt/storage/ruth-evidence/frames:/mnt/storage/ruth-evidence/frames:ro \\
      -v $WORK:/work -e YOLO_OFFLINE=1 -e YOLO_CONFIG_DIR=/tmp/yolo \\
      ruth-ai-unified-runtime:2026.11-gpu-required-offload -c \\
      'python -I /repo/ai/store_plugin/tools/fall_parity_replay.py old /work/all.txt /work/old.jsonl'

(--user 0: the evidence frames are not readable by the image's `ruth` user;
the mounts are read-only.) Build <version_dir> with install_enabled.build()
against a scratch store root.
"""

import importlib.util
import json
import sys
import time
from pathlib import Path

import cv2
import torch

REPO_AI = Path("/repo/ai")
PLUGIN = REPO_AI / "store_plugin" / "inference.py"
MANIFEST = json.loads((REPO_AI / "store_plugin" / "manifests" / "fall_pose.json").read_text())
GATE = 0.7  # the backend session threshold applied to the built-in model


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def recorded(vtype, conf, detected):
    """What the backend would write: (type, conf) or None."""
    if not detected or vtype is None or conf < GATE:
        return None
    return [vtype, round(float(conf), 6)]


def run_old(frames, out):
    model_dir = REPO_AI / "models" / "fall_detection" / "1.0.0"
    old = load(model_dir / "inference.py", "old_fall")
    loader = load(model_dir / "loader.py", "old_fall_loader")
    model = loader.load(model_dir / "weights", device="cuda:0")
    rules = load(PLUGIN, "store_rules")
    for _ in range(2):
        old._run_inference_with_model(cv2.imread(frames[0]), model)
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    with open(out, "w") as fh:
        for path in frames:
            frame = cv2.imread(path)
            if frame is None:
                fh.write(json.dumps({"path": path, "error": "unreadable"}) + "\n")
                continue
            t = time.perf_counter()
            res = old._run_inference_with_model(frame, model)
            torch.cuda.synchronize()
            ms = (time.perf_counter() - t) * 1000
            h, w = frame.shape[:2]
            # Store rule on the old model's own keypoints: 640 space -> frame px.
            objects = [
                {
                    "bbox": d["bbox"], "confidence": d["confidence"], "class_id": 0,
                    "class_name": "person", "violation": False,
                    "keypoints": [{"x": k["x"] * w / 640.0, "y": k["y"] * h / 640.0,
                                   "confidence": k["confidence"]} for k in d["keypoints"]],
                }
                for d in res["detections"]
            ]
            rule = rules.apply_rules(objects, MANIFEST, None, frame_shape=frame.shape)
            fh.write(json.dumps({
                "path": path, "shape": [h, w], "ms": ms,
                "persons": res["detection_count"],
                "raw": [res["violation_type"], res["confidence"]] if res["violation_detected"] else None,
                "old": recorded(res["violation_type"], res["confidence"], res["violation_detected"]),
                "rule_on_old_kpts": recorded(rule["violation_type"], rule["confidence"], rule["violation_detected"]),
                "rule_severity": rule["severity"] if rule["violation_detected"] else None,
            }) + "\n")
    print(json.dumps({"peak_mem_mb": torch.cuda.max_memory_reserved() / 2**20,
                      "alloc_mb": torch.cuda.memory_allocated() / 2**20}))


def run_store(frames, out, version_dir):
    plugin = load(Path(version_dir) / "inference.py", "store_plugin_under_test")
    for _ in range(2):
        plugin.infer(cv2.imread(frames[0]))
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    with open(out, "w") as fh:
        for path in frames:
            frame = cv2.imread(path)
            if frame is None:
                fh.write(json.dumps({"path": path, "error": "unreadable"}) + "\n")
                continue
            t = time.perf_counter()
            res = plugin.infer(frame)
            torch.cuda.synchronize()
            ms = (time.perf_counter() - t) * 1000
            res["metadata"].pop("inference_ms", None)
            fh.write(json.dumps({
                "path": path, "ms": ms,
                "persons": res["detection_count"],
                "new": recorded(res["violation_type"], res["confidence"], res["violation_detected"]),
                "severity": res["severity"] if res["violation_detected"] else None,
                "result": res,
            }) + "\n")
    print(json.dumps({"peak_mem_mb": torch.cuda.max_memory_reserved() / 2**20,
                      "alloc_mb": torch.cuda.memory_allocated() / 2**20}))


if __name__ == "__main__":
    mode, listfile, out = sys.argv[1:4]
    frames = [l.strip() for l in open(listfile) if l.strip()]
    if mode == "old":
        run_old(frames, out)
    else:
        run_store(frames, out, sys.argv[4])
