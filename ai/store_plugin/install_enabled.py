#!/usr/bin/env python3
"""
Install store models for the model store runtime (Step 5, pieces 1-2).

Builds ``<store>/enabled/<model_id>/1.0.0/`` for each manifest given:

    model.yaml            runtime contract, generated from the manifest
    store_manifest.json   the manifest (what the plugin runs from)
    inference.py          copy of ai/store_plugin/inference.py
    weights/<file>        hardlink to the uploaded draft (same filesystem)

The tree is built under ``staging/`` and swapped in for ``enabled/`` in one
rename; the previous tree is kept as ``state/enabled-previous-<ts>/`` for
rollback. The store runtime only sees the new tree after it is restarted
(``docker compose restart model-store-runtime``) — that restart is the
"Apply" until piece 3 automates it.

Each manifest is checked against its weights' own class names, read with a
restricted unpickler that imports and executes nothing from the file.

Standard library only; run on the host as root or uid 1000:

    python3 ai/store_plugin/install_enabled.py \\
        --store-root /mnt/storage/ruth-models \\
        ai/store_plugin/manifests/hard_hat.json \\
        ai/store_plugin/manifests/safety_vest.json \\
        ai/store_plugin/manifests/gloves.json

``--check`` validates only and changes nothing.
"""

import argparse
import io
import json
import os
import pickle
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
PLUGIN = HERE / "inference.py"
VERSION = "1.0.0"
MODEL_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,47}$")
RESERVED = {
    "fall_detection", "ppe_detection", "geo_fencing", "tank_overflow_monitoring",
    "chane_tank_monitor", "chane_tank_overflow", "helmet_detection",
    "fire_detection", "intrusion_detection",
}
SEVERITIES = {"critical", "high", "medium", "low"}
STORE_UID = STORE_GID = 1000  # owner of the model store (backend container user)


# ---------------------------------------------------------------------------
# Safe .pt introspection: never imports or runs anything from the file
# ---------------------------------------------------------------------------


class _Stub:
    def __init__(self, *args, **kwargs):
        pass

    def __setstate__(self, state):
        self.__dict__["_state"] = state


class _SafeUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) == ("collections", "OrderedDict"):
            import collections
            return collections.OrderedDict
        if module == "builtins" and name in {"set", "frozenset", "slice"}:
            import builtins
            return getattr(builtins, name)
        return type(f"{module}.{name}", (_Stub,), {"_qualname": f"{module}.{name}"})

    def persistent_load(self, pid):  # tensor storages: never loaded
        return _Stub()


def _find(obj: Any, key: str, depth: int = 0):
    if depth > 6:
        return None
    state = obj.__dict__.get("_state") if isinstance(obj, _Stub) else obj
    if isinstance(state, tuple):
        for item in state:
            found = _find(item, key, depth + 1)
            if found is not None:
                return found
    if isinstance(state, dict):
        if key in state:
            return state[key]
        for value in state.values():
            if isinstance(value, (_Stub, dict)):
                found = _find(value, key, depth + 1)
                if found is not None:
                    return found
    return None


def weights_info(path: Path) -> Dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        pkl = next(n for n in archive.namelist() if n.endswith("data.pkl"))
        top = _SafeUnpickler(io.BytesIO(archive.read(pkl))).load()
    model = top.get("model") or top.get("ema")
    names = _find(model, "names") or {}
    return {
        "model_class": getattr(type(model), "_qualname", type(model).__name__),
        "names": {str(k): str(v) for k, v in dict(names).items()},
        "task": _find(model, "task"),
        "train_imgsz": (top.get("train_args") or {}).get("imgsz"),
    }


# ---------------------------------------------------------------------------
# Manifest validation
# ---------------------------------------------------------------------------


def manifest_problems(manifest: Dict[str, Any]) -> List[str]:
    p: List[str] = []
    model_id = manifest.get("model_id", "")
    if not MODEL_ID_RE.match(model_id):
        p.append(f"model_id {model_id!r} must match {MODEL_ID_RE.pattern}")
    if model_id in RESERVED:
        p.append(f"model_id {model_id!r} is a built-in id")
    if manifest.get("task") != "detect":
        p.append("task must be 'detect'")
    imgsz = manifest.get("imgsz")
    if not isinstance(imgsz, int) or imgsz <= 0 or imgsz % 32:
        p.append("imgsz must be a positive multiple of 32")
    classes = manifest.get("classes")
    if not isinstance(classes, dict) or not classes:
        p.append("classes must be a non-empty {id: name} map")
        classes = {}
    names = set(classes.values())
    rules = manifest.get("rules")
    if not isinstance(rules, list) or not rules:
        p.append("rules must be a non-empty list")
        rules = []
    ids = set()
    for rule in rules:
        rid = rule.get("id")
        if not rid or rid in ids:
            p.append(f"rule id {rid!r} missing or duplicated")
        ids.add(rid)
        unknown = set(rule.get("classes", [])) - names
        if not rule.get("classes") or unknown:
            p.append(f"rule {rid}: classes {sorted(unknown) or '[]'} not in the model's classes")
        conf = rule.get("min_confidence")
        if not isinstance(conf, (int, float)) or not 0 < conf <= 1:
            p.append(f"rule {rid}: min_confidence must be in (0, 1]")
        if not rule.get("violation_type"):
            p.append(f"rule {rid}: violation_type required")
        if rule.get("severity") not in SEVERITIES:
            p.append(f"rule {rid}: severity must be one of {sorted(SEVERITIES)}")
        # Optional: the label violations from this rule are shown under
        # ("Missing gloves"). Absent, Ruth uses a built-in label or the
        # title-cased violation_type.
        label = rule.get("display_name")
        if label is not None and (not isinstance(label, str) or not label.strip() or len(label) > 64):
            p.append(f"rule {rid}: display_name must be a non-empty string of at most 64 characters")
    perf = manifest.get("performance", {})
    for key in ("inference_time_hint_ms", "recommended_fps"):
        # The backend's registration schema declares these int: a float
        # makes the whole runtime registration fail with a 422.
        if not isinstance(perf.get(key), int) or perf.get(key) <= 0:
            p.append(f"performance.{key} must be a positive integer")
    limits = manifest.get("limits", {})
    if not isinstance(limits.get("max_memory_mb"), int):
        p.append("limits.max_memory_mb must be an integer")
    return p


def model_yaml(manifest: Dict[str, Any]) -> str:
    """Runtime contract for the model. JSON is valid YAML."""
    contract = {
        "contract_schema_version": "1.0.0",
        "model_id": manifest["model_id"],
        "version": VERSION,
        "display_name": manifest.get("display_name", manifest["model_id"]),
        "description": "Uploaded model (model store), generic detection plugin",
        "author": "model store",
        "input": {"type": "frame", "format": "raw_bgr", "min_width": 320,
                  "min_height": 240, "max_width": 4096, "max_height": 4096, "channels": 3},
        "output": {"schema_version": "1.0", "schema": {
            "violation_detected": {"type": "boolean"},
            "violation_type": {"type": "string"},
            "severity": {"type": "string"},
            "confidence": {"type": "number"},
            "detections": {"type": "array"},
            "objects": {"type": "array"},
            "metadata": {"type": "object"},
        }},
        "hardware": {"supports_cpu": True, "supports_gpu": True, "supports_jetson": False},
        "performance": {
            "inference_time_hint_ms": manifest["performance"]["inference_time_hint_ms"],
            "recommended_fps": manifest["performance"]["recommended_fps"],
            "warmup_iterations": 1,
        },
        "limits": {
            "max_memory_mb": manifest["limits"]["max_memory_mb"],
            "inference_timeout_ms": manifest["limits"].get("inference_timeout_ms", 5000),
        },
        "entry_points": {"inference": "inference.py"},
    }
    return "# Generated by ai/store_plugin/install_enabled.py — do not edit.\n" + json.dumps(contract, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def find_draft_weights(store: Path, filename: str) -> Path:
    matches = sorted((store / "drafts").glob(f"*/weights/{filename}"))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one uploaded {filename} under drafts/, found {len(matches)}")
    return matches[0]


def _own(path: Path, mode: int) -> None:
    if os.geteuid() == 0:
        os.chown(path, STORE_UID, STORE_GID, follow_symlinks=False)
    os.chmod(path, mode)


def build(store: Path, manifests: List[Dict[str, Any]], tree: Path) -> None:
    tree.mkdir(parents=True)
    _own(tree, 0o750)
    for manifest in manifests:
        version_dir = tree / manifest["model_id"] / VERSION
        (version_dir / "weights").mkdir(parents=True)
        for d in (version_dir.parent, version_dir, version_dir / "weights"):
            _own(d, 0o750)
        src = find_draft_weights(store, manifest["weights"])
        dst = version_dir / "weights" / manifest["weights"]
        os.link(src, dst)  # hardlink: the runtime rejects symlinks leaving the dir
        (version_dir / "store_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (version_dir / "model.yaml").write_text(model_yaml(manifest))
        shutil.copyfile(PLUGIN, version_dir / "inference.py")
        for f in ("store_manifest.json", "model.yaml", "inference.py"):
            _own(version_dir / f, 0o640)


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store-root", default="/mnt/storage/ruth-models", type=Path)
    ap.add_argument("--check", action="store_true", help="validate only; change nothing")
    ap.add_argument("manifests", nargs="+", type=Path)
    args = ap.parse_args(argv)
    store: Path = args.store_root

    manifests, failed = [], False
    for path in args.manifests:
        manifest = json.loads(path.read_text())
        problems = manifest_problems(manifest)
        if not problems:
            weights = find_draft_weights(store, manifest["weights"])
            info = weights_info(weights)
            if info["task"] != "detect":
                problems.append(f"weights task is {info['task']!r}, not 'detect'")
            if info["names"] != manifest["classes"]:
                problems.append(f"classes {manifest['classes']} != weights' own {info['names']}")
            if info["train_imgsz"] and info["train_imgsz"] != manifest["imgsz"]:
                print(f"note: {manifest['model_id']}: trained at {info['train_imgsz']}, manifest imgsz {manifest['imgsz']}")
        ids = [m["model_id"] for m in manifests]
        if manifest.get("model_id") in ids:
            problems.append("model_id given twice")
        if problems:
            failed = True
            print(f"FAIL {path}:\n  - " + "\n  - ".join(problems))
        else:
            print(f"ok   {path}: {manifest['model_id']} ({manifest['weights']}, imgsz {manifest['imgsz']}, "
                  f"{len(manifest['rules'])} rule(s))")
            manifests.append(manifest)
    if failed:
        return 1
    if args.check:
        print("check only: nothing changed")
        return 0

    ts = time.strftime("%Y%m%dT%H%M%S")
    staging = store / "staging" / f"enabled-{ts}"
    enabled = store / "enabled"
    previous = store / "state" / f"enabled-previous-{ts}"
    build(store, manifests, staging)
    if enabled.exists():
        enabled.rename(previous)
    staging.rename(enabled)
    print(f"installed {len(manifests)} model(s) into {enabled}")
    if previous.exists():
        print(f"previous tree kept at {previous}")
    print("now: docker compose restart model-store-runtime   (the runtime reads the tree at start)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
