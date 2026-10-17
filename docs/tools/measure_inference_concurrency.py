#!/usr/bin/env python3
"""Measure what the AI runtime is actually achieving. See docs/BACKLOG.md BL-5.

Written because the same question — "is the runtime serialising, and is the
GPU the constraint?" — has now been asked twice (2026-10-04 demo,
2026-10-17 HPCL) and answered both times by a throwaway script. The answer
has changed once already: the GPU *was* the binding constraint on the
built-in runtime and is *not* on the store runtime, so this needs
re-measuring per deployment rather than reasoning about.

The load-bearing measurement is **max concurrency**, obtained by pairing
every "Inference request received" to its "Inference completed
successfully" by `request_id` and sweeping the resulting intervals. A rate
or a latency figure cannot distinguish "serialised" from "concurrent but
slow"; overlapping spans can.

Read-only: reads container logs, samples nvidia-smi, and runs SELECTs.
Changes nothing. Safe against a live deployment.

Usage:
    python3 docs/tools/measure_inference_concurrency.py --minutes 10 \\
        --label baseline --out /path/to/results

    # compare two runs
    python3 docs/tools/measure_inference_concurrency.py \\
        --compare before.json after.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Defaults match the Ruth AI deployment; override on the command line.
RUNTIME_CONTAINER = "ruth-ai-model-store-runtime"
DB_CONTAINER = "ruth-ai-vas-postgres"
DB_USER = "ruth"
DB_NAME = "ruth_ai"

#: How many log lines to pull. At ~16 req/s x 2 lines, 10 minutes is
#: ~20k lines; 80k gives headroom for a faster runtime after the fix.
LOG_LINES = 120_000

REQ = "Inference request received"
DONE = "Inference completed successfully"


def sh(cmd: list[str], timeout: int = 120) -> str:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout
    ).stdout


def parse_ts(s: str) -> datetime:
    # The runtime logs "...Z" with microseconds.
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f%z" if s.endswith("+00:00")
                             else "%Y-%m-%dT%H:%M:%S.%fZ")


# -----------------------------------------------------------------------------
# Collection
# -----------------------------------------------------------------------------


def runtime_log_records(container: str) -> list[dict]:
    out = sh(["docker", "logs", "--tail", str(LOG_LINES), container])
    recs = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if "timestamp" in r:
            recs.append(r)
    return recs


def sample_gpu(seconds: float, interval: float = 1.0) -> dict:
    """Sample GPU utilisation across the window rather than once.

    A single reading is near worthless here: utilisation swings between
    inferences, and the question is whether there is headroom on average.
    """
    util, mem = [], []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        out = sh(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            timeout=20,
        ).strip()
        for row in out.splitlines():
            parts = [p.strip() for p in row.split(",")]
            if len(parts) == 3 and parts[0].isdigit():
                util.append(int(parts[0]))
                mem.append((int(parts[1]), int(parts[2])))
        time.sleep(interval)
    if not util:
        return {"available": False}
    return {
        "available": True,
        "samples": len(util),
        "util_mean": round(st.mean(util), 1),
        "util_median": st.median(util),
        "util_min": min(util),
        "util_max": max(util),
        "vram_used_mib": mem[-1][0],
        "vram_total_mib": mem[-1][1],
    }


def db_rows(sql: str) -> list[list[str]]:
    out = sh(["docker", "exec", DB_CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME,
              "-t", "-A", "-F", "|", "-c", sql])
    return [l.split("|") for l in out.strip().splitlines() if l.strip()]


def camera_rates(window_s: int) -> dict:
    """Ticks per camera, from frames_processed deltas over a real interval.

    NOTE frames_processed counts model *publications*, not ticks (it is
    incremented by the number of models that published), so a 3-model
    session advances it by up to 3 per tick. Reported as publications/s to
    match the runtime's request rate directly.
    """
    q = ("SELECT s.device_id, d.name, s.frames_processed, s.inference_fps, "
         "coalesce(jsonb_array_length(s.models),1) "
         "FROM stream_sessions s JOIN devices d ON d.id=s.device_id "
         "WHERE s.state='live' ORDER BY d.name;")
    before = {r[0]: (r[1], int(r[2]), int(r[3]), int(r[4])) for r in db_rows(q)}
    time.sleep(window_s)
    after = {r[0]: (r[1], int(r[2]), int(r[3]), int(r[4])) for r in db_rows(q)}

    per = []
    for dev, (name, f0, fps, nmodels) in before.items():
        if dev not in after:
            continue
        delta = after[dev][1] - f0
        per.append({
            "camera": name,
            "publications_per_s": round(delta / window_s, 2),
            "requested_per_s": fps * nmodels,
            "percent_of_requested": round(100 * (delta / window_s) / (fps * nmodels), 1)
            if fps * nmodels else None,
        })
    total = sum(p["publications_per_s"] for p in per)
    return {
        "window_seconds": window_s,
        "cameras": len(per),
        "fleet_publications_per_s": round(total, 2),
        "fleet_requested_per_s": sum(p["requested_per_s"] for p in per),
        "per_camera": per,
    }


def violation_count() -> int:
    rows = db_rows("SELECT count(*) FROM violations;")
    return int(rows[0][0]) if rows else -1


# -----------------------------------------------------------------------------
# Analysis
# -----------------------------------------------------------------------------


def analyse_log(recs: list[dict], minutes: int) -> dict:
    if not recs:
        return {"error": "no parsable log records"}

    end = parse_ts(recs[-1]["timestamp"])
    start = end - timedelta(minutes=minutes)
    win = [r for r in recs if parse_ts(r["timestamp"]) >= start]
    secs = (end - start).total_seconds()

    req = [r for r in win if r.get("message") == REQ]
    done = [r for r in win if r.get("message") == DONE]
    errors = [r for r in win if r.get("level") not in ("INFO", "DEBUG")]

    # Pair request -> completion and sweep for true concurrency. This is
    # the measurement the whole exercise turns on.
    opened: dict[str, datetime] = {}
    spans: list[tuple[datetime, datetime]] = []
    for r in win:
        rid = r.get("request_id")
        if not rid:
            continue
        if r.get("message") == REQ:
            opened[rid] = parse_ts(r["timestamp"])
        elif r.get("message") == DONE and rid in opened:
            spans.append((opened.pop(rid), parse_ts(r["timestamp"])))
    spans.sort()

    events: list[tuple[datetime, int]] = []
    for s, e in spans:
        events.append((s, 1))
        events.append((e, -1))
    events.sort()
    cur = peak = 0
    for _, delta in events:
        cur += delta
        peak = max(peak, cur)

    gaps = [(spans[i + 1][0] - spans[i][1]).total_seconds() * 1000
            for i in range(len(spans) - 1)]
    overlaps = sum(1 for g in gaps if g < 0)
    idle = [g for g in gaps if g >= 0]

    per_model: dict[str, dict] = {}
    for m in sorted({d.get("model_id") for d in done if d.get("model_id")}):
        lat = sorted(d["inference_time_ms"] for d in done
                     if d.get("model_id") == m and "inference_time_ms" in d)
        if not lat:
            continue
        per_model[m] = {
            "completions": len(lat),
            "per_second": round(len(lat) / secs, 2),
            "mean_ms": round(st.mean(lat), 1),
            "p50_ms": round(lat[len(lat) // 2], 1),
            "p95_ms": round(lat[int(len(lat) * 0.95)], 1),
            "max_ms": round(lat[-1], 1),
        }

    all_lat = sorted(d["inference_time_ms"] for d in done if "inference_time_ms" in d)
    busy = sum(all_lat) / 1000.0

    return {
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_seconds": round(secs),
        "requests": len(req),
        "completions": len(done),
        "requests_per_second": round(len(req) / secs, 2),
        "error_lines": len(errors),
        "paired_spans": len(spans),
        "max_concurrent": peak,
        "overlapping_pairs": overlaps,
        "idle_gap_p50_ms": round(st.median(idle), 1) if idle else None,
        "idle_gap_p95_ms": round(sorted(idle)[int(len(idle) * 0.95)], 1) if idle else None,
        "busy_percent": round(100 * busy / secs, 1),
        "latency_mean_ms": round(st.mean(all_lat), 1) if all_lat else None,
        "latency_p50_ms": round(all_lat[len(all_lat) // 2], 1) if all_lat else None,
        "latency_p95_ms": round(all_lat[int(len(all_lat) * 0.95)], 1) if all_lat else None,
        "per_model": per_model,
    }


# -----------------------------------------------------------------------------
# Reporting
# -----------------------------------------------------------------------------


def render(result: dict) -> str:
    L = result["log"]
    g = result["gpu"]
    c = result["cameras"]
    out = [
        f"=== {result['label']}  ({result['captured_at']}) ===",
        f"runtime: {result['runtime_container']}",
        "",
        f"window              {L['window_seconds']}s  "
        f"({L['window_start'][11:19]} -> {L['window_end'][11:19]})",
        f"requests            {L['requests']:6d}  ({L['requests_per_second']}/s)",
        f"completions         {L['completions']:6d}",
        f"error log lines     {L['error_lines']:6d}",
        "",
        f"MAX CONCURRENT      {L['max_concurrent']}        <-- 1 means serialised",
        f"overlapping pairs   {L['overlapping_pairs']}",
        f"runtime busy        {L['busy_percent']}%",
        f"idle gap p50/p95    {L['idle_gap_p50_ms']} / {L['idle_gap_p95_ms']} ms",
        "",
        f"latency mean        {L['latency_mean_ms']} ms",
        f"latency p50/p95     {L['latency_p50_ms']} / {L['latency_p95_ms']} ms",
        "",
        "per model:",
    ]
    for m, s in L["per_model"].items():
        out.append(f"  {m:14s} {s['completions']:5d}  ({s['per_second']}/s)  "
                   f"mean {s['mean_ms']:6.1f}  p50 {s['p50_ms']:6.1f}  "
                   f"p95 {s['p95_ms']:6.1f}  max {s['max_ms']:6.1f}")
    if g.get("available"):
        out += ["",
                f"GPU util            mean {g['util_mean']}%  median {g['util_median']}%  "
                f"min {g['util_min']}%  max {g['util_max']}%  ({g['samples']} samples)",
                f"VRAM                {g['vram_used_mib']} / {g['vram_total_mib']} MiB"]
    out += ["",
            f"cameras live        {c['cameras']}",
            f"fleet publications  {c['fleet_publications_per_s']}/s "
            f"of {c['fleet_requested_per_s']}/s requested",
            f"violations total    {result['violations']}"]
    return "\n".join(out)


def compare(before: dict, after: dict) -> str:
    b, a = before["log"], after["log"]

    def row(name, bv, av, fmt="{:.1f}", better="up"):
        if bv in (None, 0) or av is None:
            return f"  {name:24s} {bv}  ->  {av}"
        delta = (av - bv) / bv * 100
        arrow = "+" if delta >= 0 else ""
        good = (delta > 0) if better == "up" else (delta < 0)
        mark = "  ok" if good else "  <-- worse"
        return (f"  {name:24s} {fmt.format(bv):>8s}  ->  {fmt.format(av):>8s}   "
                f"{arrow}{delta:.0f}%{mark if abs(delta) > 2 else ''}")

    lines = [
        f"=== {before['label']}  ->  {after['label']} ===",
        "",
        row("max concurrent", b["max_concurrent"], a["max_concurrent"], "{:.0f}"),
        row("requests/s", b["requests_per_second"], a["requests_per_second"], "{:.2f}"),
        row("busy %", b["busy_percent"], a["busy_percent"]),
        row("latency mean ms", b["latency_mean_ms"], a["latency_mean_ms"], "{:.1f}", "down"),
        row("latency p95 ms", b["latency_p95_ms"], a["latency_p95_ms"], "{:.1f}", "down"),
        "",
        row("fleet publications/s",
            before["cameras"]["fleet_publications_per_s"],
            after["cameras"]["fleet_publications_per_s"], "{:.2f}"),
    ]
    if before["gpu"].get("available") and after["gpu"].get("available"):
        lines.append(row("GPU util mean %", before["gpu"]["util_mean"],
                         after["gpu"]["util_mean"]))
    lines += [
        "",
        f"  violations   {before['violations']}  ->  {after['violations']}  "
        f"(+{after['violations'] - before['violations']})",
        "",
        "STOP CONDITIONS (BL-5):",
        f"  p95 > 250 ms            : {'TRIPPED' if (a['latency_p95_ms'] or 0) > 250 else 'ok'}",
        f"  error lines present     : {'TRIPPED' if a['error_lines'] else 'ok'}",
        f"  concurrency unchanged   : "
        f"{'TRIPPED' if a['max_concurrent'] <= b['max_concurrent'] else 'ok'}",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=int, default=10, help="log window (default 10)")
    ap.add_argument("--label", default="run", help="name for this measurement")
    ap.add_argument("--out", default=".", help="directory for the JSON result")
    ap.add_argument("--runtime", default=RUNTIME_CONTAINER)
    ap.add_argument("--gpu-seconds", type=float, default=30.0)
    ap.add_argument("--camera-window", type=int, default=60)
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args()

    if args.compare:
        before = json.loads(Path(args.compare[0]).read_text())
        after = json.loads(Path(args.compare[1]).read_text())
        print(compare(before, after))
        return 0

    print(f"[{args.label}] sampling GPU for {args.gpu_seconds}s and camera rates "
          f"for {args.camera_window}s...", file=sys.stderr)
    gpu = sample_gpu(args.gpu_seconds)
    cams = camera_rates(args.camera_window)

    print(f"[{args.label}] reading runtime logs...", file=sys.stderr)
    result = {
        "label": args.label,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "runtime_container": args.runtime,
        "log": analyse_log(runtime_log_records(args.runtime), args.minutes),
        "gpu": gpu,
        "cameras": cams,
        "violations": violation_count(),
    }

    out = Path(args.out) / f"{args.label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(render(result))
    print(f"\nsaved: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
