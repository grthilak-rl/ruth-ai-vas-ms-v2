"""
Chane Tank Monitor — inference entry point.

Brightness-area tank-fill monitoring. For a top-down circular tank, fill is
measured by the fraction of BRIGHT (reflective liquid-surface) pixels inside a
locked circular ROI. Motion is NOT used as the fill measure (it peaks mid-fill
and goes calm near full) — it is computed only for the instrumentation CSV so
we can confirm brightness, not motion, tracks fill. Anomaly detection removed
(explicitly not required).

Runtime contract:
  infer(frame: np.ndarray, config: Dict = None, **kwargs) -> Dict

The runtime passes only `frame` (BGR np.ndarray) and `config` (the per-stream
model_config). No stream identifier reaches here today; v1 keeps a single
module-global session keyed by _session_key(), so per-stream isolation is a
drop-in if a caller later injects config["stream_id"].

ROI is resolved ONCE per session and LOCKED:
  1. config["roi_circle"] = {"cx","cy","r"}  -> source "config"  (operator click
     or manual config — the intended path; auto-detect failed on real footage)
  2. center-of-frame fallback                -> source "fallback"

Tunables (all config-overridable — they WILL be tuned after seeing the CSV):
  brightness_threshold  (default 180)   gray [0-255]; above = bright surface
  smoothing_window      (default 15)    frames to average bright_fraction
  fill_calib_min        (default 0.0)   bright_fraction mapped to 0% fill
  fill_calib_max        (default 1.0)   bright_fraction mapped to 100% fill
  csv_path              (default /tmp/chane_tank_monitor/<session>.csv)
"""

import csv
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

import cv2
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))
from fill_engine import (  # noqa: E402
    BrightnessFillDetector,
    MotionBlendProbe,
    detect_radius_from_center,
)

# Defaults (overridable via config) — kept here, not buried in the detector.
#
# !!! DEMO CALIBRATION — DOME1 24/06/2026 clip 14:12:32-14:29:08 ONLY !!!
# The runtime has NO config channel to infer(): InferenceRequest carries no
# model_config, so every value below is what ACTUALLY runs — config.get(...)
# always falls through to these. Only roi_circle arrives (via a separate path).
# Therefore these defaults ARE the tuning knobs until config plumbing exists.
#
# These numbers were measured on that ONE clip (T=40 tracks its fill at r=+0.955;
# empty=0.2052, full=0.66 bright-fraction). They DO NOT transfer: on the 01/07
# feed the best threshold was 40 with calib [0.4477, 0.86], and on the original
# dark feed it was T=140 / [0.06, 0.115]. A different clip needs re-tuning.
# See docs/ or ask before reusing these on any other footage.
DEFAULT_BRIGHTNESS_THRESHOLD = 40        # demo: 24/06 clip (was 180)
DEFAULT_SMOOTHING_WINDOW = 51            # demo: smooths hose/splash noise (was 15)
DEFAULT_FILL_CALIB_MIN = 0.2052          # demo: measured empty (was 0.0)
DEFAULT_FILL_CALIB_MAX = 0.66            # demo: measured full  (was 1.0)
DEFAULT_CSV_DIR = "/tmp/chane_tank_monitor"

# A gap this long between frames means a new clip/replay/bookmark switch, not a
# continuous fill: the session is rebuilt so no stale fill_display or smoothing
# history bleeds across. Replaying the SAME bookmark re-sends the SAME
# roi_circle, so the roi_changed check alone never fires — this is what actually
# catches a re-play. 5s is well above the ~0.5s live frame interval (2 fps).
DEFAULT_SESSION_IDLE_RESET_S = 5.0

# --- TIMED RAMP (demo playback mode) ----------------------------------------
# !!! THIS IS NOT A MEASUREMENT. !!!
# When fill_time_based=True, fill_percentage is a linear ramp over CLIP TIME and
# the video is never consulted: it reads 0% -> 100% between the two times below
# on an empty tank, a full tank, or a blank screen, and it keeps climbing if the
# camera pans away. It exists because the brightness signal's timing did not
# match this clip's real fill and a demo needed a presentable meter.
#
# It must never be mistaken for the model measuring fill: while it is on,
# metadata.fill_source = "time_ramp" (vs "brightness") and metadata carries
# fill_time_based=True. Do NOT enable it on a live camera — it will report a
# confident fill for a tank it cannot see. Default OFF.
DEFAULT_FILL_TIME_BASED = False
DEFAULT_FILL_TIME_START_S = 110.0   # 1m50s -> 0%
DEFAULT_FILL_TIME_END_S = 928.0     # 15m28s -> 100%

# !!! DEMO ROI — DOME1 24/06/2026 clip 14:12:32-14:29:08 ONLY !!!
# roi_circle does not reach infer() either (no config channel), so the old
# centre-of-frame fallback (960,540,324 on 1920x1080) locked onto the PIPE, not
# the manhole. This is the manhole circle measured on that clip: verified
# against a frame (HoughCircles independently lands on 815,556,509 — the same
# rim, ~15px off) and it is the ROI every calibration number was measured
# through, so it must stay paired with DEFAULT_FILL_CALIB_MIN/MAX above:
# the Hough circle reads ~+0.02 bright-fraction higher (more rim) and would
# make the meter start at ~7% instead of 0%.
#
# Frame-size guarded: applied only to 1920x1080 (the demo clip's geometry).
# Any other resolution falls back to centre-of-frame as before.
DEFAULT_DEMO_ROI = {"cx": 800, "cy": 546, "r": 503}
DEFAULT_DEMO_ROI_FRAME = (1920, 1080)   # (width, height) this ROI was measured on

# --- Auto-calibration defaults (all config-overridable) ----------------------
# Fixed calib does not survive a feed change (dark feed empty/full ~[0.06,0.115];
# brighter feed reads ~0.143 at EMPTY -> pins 100%). Auto-cal anchors 0% on the
# session's own empty frames and seeds 100% from a per-camera prior span.
DEFAULT_AUTO_CALIBRATE = False      # opt-in; fixed calib stays the fallback
DEFAULT_AUTO_WARMUP_FRAMES = 30     # frames assumed EMPTY -> the 0% anchor
DEFAULT_AUTO_PRIOR_SPAN = 0.05      # expected empty->full bright_fraction rise
DEFAULT_AUTO_MIN_SPAN = 0.02        # floor on (max-min); avoids divide-by-noise
DEFAULT_AUTO_MAX_GROW_RATE = 0.02   # max per-frame growth of the 100% target
DEFAULT_DISPLAY_SLEW_PCT = 0.5      # demo: 24/06-validated smooth climb (was 1.5)
# Display-only: when True the meter tracks the running max of fill_raw, so it
# only ever climbs (slew-limited, so it ratchets smoothly rather than latching).
# Opt-in: a monotonic meter cannot show a tank emptying. See infer().
DEFAULT_DISPLAY_MONOTONIC = False
# Brightness-threshold sweep set (config-overridable via "sweep_thresholds").
DEFAULT_SWEEP_THRESHOLDS = [40, 60, 80, 100, 120, 140, 160, 180]


def _csv_columns(thresholds):
    """CSV header: fixed cols + one bright_frac_<T> per swept threshold."""
    return (
        ["frame_n", "elapsed_seconds", "mean_brightness", "motion_blend"]
        + [f"bright_frac_{int(t)}" for t in thresholds]
        + ["roi_cx", "roi_cy", "roi_r", "roi_source"]
    )

# Per-session state. v1: effectively one entry ("default").
_sessions: Dict[str, Dict[str, Any]] = {}


def _session_key(config: Dict[str, Any]) -> str:
    """Identify the monitoring session. stream_id is not passed today; if a
    caller adds config["stream_id"], sessions isolate with no other change."""
    return str(config.get("stream_id", "default"))


def _resolve_roi(frame: np.ndarray, config: Dict[str, Any]):
    """Resolve (cx, cy, r, source). Called once per session, then locked.

    Auto-detect was removed from the chain: HoughCircles latched onto a pipe on
    real footage. The intended path is an operator-clicked roi_circle in config.
    """
    fH, fW = frame.shape[:2]

    roi_circle = config.get("roi_circle")
    if isinstance(roi_circle, dict) and all(k in roi_circle for k in ("cx", "cy", "r")):
        cx = max(0, min(int(roi_circle["cx"]), fW - 1))
        cy = max(0, min(int(roi_circle["cy"]), fH - 1))
        r = max(5, min(int(roi_circle["r"]), min(fW, fH) // 2))
        return cx, cy, r, "config"

    # Demo default: the hardcoded manhole ROI, used only when the frame matches
    # the geometry it was measured on. A real config roi_circle above still
    # wins — this only replaces the useless centre-of-frame guess, which landed
    # on the pipe. Reported as "demo_default" (NOT "config") so the overlay
    # never claims an operator set it.
    if (fW, fH) == DEFAULT_DEMO_ROI_FRAME:
        cx = max(0, min(int(DEFAULT_DEMO_ROI["cx"]), fW - 1))
        cy = max(0, min(int(DEFAULT_DEMO_ROI["cy"]), fH - 1))
        r = max(5, min(int(DEFAULT_DEMO_ROI["r"]), min(fW, fH) // 2))
        return cx, cy, r, "demo_default"

    # Fallback: center of frame (non-demo geometry).
    cx, cy = fW // 2, fH // 2
    r = int(min(fH, fW) * 0.30)
    return cx, cy, r, "fallback"


def _open_csv(config: Dict[str, Any], key: str, thresholds):
    """Open (and header) the instrumentation CSV. Returns (file, writer) or
    (None, None) if it can't be opened (logged, never fatal)."""
    csv_path = config.get("csv_path")
    if not csv_path:
        csv_dir = config.get("csv_dir", DEFAULT_CSV_DIR)
        safe = key.replace("/", "_")
        csv_path = os.path.join(csv_dir, f"{safe}.csv")
    try:
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        f = open(csv_path, "w", newline="")
        w = csv.writer(f)
        w.writerow(_csv_columns(thresholds))
        f.flush()
        logger.info("chane_tank_monitor instrumentation CSV: %s", csv_path)
        return f, w, csv_path
    except Exception as e:
        logger.warning("Could not open instrumentation CSV (%s): %s", csv_path, e)
        return None, None, csv_path


def _close_session(sess: Dict[str, Any]) -> None:
    """Release a session's resources (CSV file handle) before discarding it."""
    f = sess.get("csv_file")
    if f is not None:
        try:
            f.close()
        except Exception:
            pass


def _config_roi_signature(config: Dict[str, Any]):
    """The (cx,cy,r) the config is currently requesting, or None. Used to detect
    when the operator has (re)confirmed a different ROI so we can re-lock —
    otherwise an already-locked 'fallback' session would ignore a later
    roi_circle and keep measuring the wrong region."""
    rc = config.get("roi_circle")
    if isinstance(rc, dict) and all(k in rc for k in ("cx", "cy", "r")):
        return (int(rc["cx"]), int(rc["cy"]), int(rc["r"]))
    return None


def _get_session(frame: np.ndarray, config: Dict[str, Any]) -> Dict[str, Any]:
    key = _session_key(config)
    sess = _sessions.get(key)

    # Re-lock if the config now requests an ROI that differs from the locked one
    # (e.g. operator confirmed/changed roi_circle after an initial fallback lock),
    # OR if a key tunable (brightness_threshold etc.) changed — this lets the
    # operator sweep tunables from the frontend config WITHOUT a rebuild or
    # runtime restart; the next request with a new value rebuilds the session.
    if sess is not None:
        want = _config_roi_signature(config)
        roi_changed = want is not None and (
            want != (sess["roi"]["cx"], sess["roi"]["cy"], sess["roi"]["r"])
            or sess["roi"]["source"] != "config"
        )
        # A long gap since the last frame => new clip / replay / bookmark switch.
        # Without this, replaying the same bookmark keeps the SAME roi_circle, so
        # roi_changed stays False and the old session (with its stale
        # fill_display and smoothing history) is reused — the meter then starts
        # at the PREVIOUS clip's value and slews down to the new reading (the
        # 100%->60%->rise slide). Live streams tick every ~0.5s, far under this.
        idle_reset_s = float(config.get("session_idle_reset_s", DEFAULT_SESSION_IDLE_RESET_S))
        idle_gap = time.time() - sess.get("last_frame_time", time.time())
        idle_expired = idle_reset_s > 0 and idle_gap > idle_reset_s

        det = sess["detector"]
        tunables_changed = (
            float(config.get("brightness_threshold", det.brightness_threshold)) != det.brightness_threshold
            or int(config.get("smoothing_window", det.smoothing_window)) != det.smoothing_window
            or float(config.get("fill_calib_min", det.fill_calib_min)) != det.fill_calib_min
            or float(config.get("fill_calib_max", det.fill_calib_max)) != det.fill_calib_max
            # Auto-cal tunables re-lock too: a re-lock restarts warmup, which is
            # exactly what's wanted — the empty anchor must be re-measured.
            or bool(config.get("auto_calibrate", det.auto_calibrate)) != det.auto_calibrate
            or int(config.get("auto_warmup_frames", det.auto_warmup_frames)) != det.auto_warmup_frames
            or float(config.get("auto_prior_span", det.auto_prior_span)) != det.auto_prior_span
            or float(config.get("auto_min_span", det.auto_min_span)) != det.auto_min_span
            or float(config.get("auto_max_grow_rate", det.auto_max_grow_rate)) != det.auto_max_grow_rate
        )
        if roi_changed or tunables_changed or idle_expired:
            logger.info(
                "chane_tank_monitor session %s: resetting "
                "(roi_changed=%s tunables_changed=%s idle_expired=%s gap=%.1fs); "
                "re-locking with fresh display/smoothing state",
                key, roi_changed, tunables_changed, idle_expired, idle_gap,
            )
            _close_session(sess)
            sess = None
            _sessions.pop(key, None)

    if sess is None:
        cx, cy, r, source = _resolve_roi(frame, config)
        detector = BrightnessFillDetector(
            brightness_threshold=config.get("brightness_threshold", DEFAULT_BRIGHTNESS_THRESHOLD),
            smoothing_window=config.get("smoothing_window", DEFAULT_SMOOTHING_WINDOW),
            fill_calib_min=config.get("fill_calib_min", DEFAULT_FILL_CALIB_MIN),
            fill_calib_max=config.get("fill_calib_max", DEFAULT_FILL_CALIB_MAX),
            auto_calibrate=config.get("auto_calibrate", DEFAULT_AUTO_CALIBRATE),
            auto_warmup_frames=config.get("auto_warmup_frames", DEFAULT_AUTO_WARMUP_FRAMES),
            auto_prior_span=config.get("auto_prior_span", DEFAULT_AUTO_PRIOR_SPAN),
            auto_min_span=config.get("auto_min_span", DEFAULT_AUTO_MIN_SPAN),
            auto_max_grow_rate=config.get("auto_max_grow_rate", DEFAULT_AUTO_MAX_GROW_RATE),
        )
        sweep_thresholds = [
            int(t) for t in config.get("sweep_thresholds", DEFAULT_SWEEP_THRESHOLDS)
        ]
        csv_file, csv_writer, csv_path = _open_csv(config, key, sweep_thresholds)
        sess = {
            "detector": detector,
            "motion": MotionBlendProbe(),
            "roi": {"cx": cx, "cy": cy, "r": r, "source": source},
            "frame_n": 0,
            "start_time": time.time(),
            "fill_running_max": 0.0,   # reference only, not displayed
            "fill_display": None,      # slew-limited displayed value
            "last_frame_time": time.time(),  # for the idle-gap session reset
            "csv_file": csv_file,
            "csv_writer": csv_writer,
            "csv_path": csv_path,
            "sweep_thresholds": sweep_thresholds,
        }
        _sessions[key] = sess
        logger.info(
            "chane_tank_monitor session %s started; ROI locked %s source=%s "
            "thr=%s win=%s calib=[%s,%s] sweep=%s",
            key, sess["roi"], source,
            detector.brightness_threshold, detector.smoothing_window,
            detector.fill_calib_min, detector.fill_calib_max, sweep_thresholds,
        )
        # Brightness-distribution summary at session start: shows where
        # liquid-vs-background separates so the right threshold is read off
        # directly rather than guessed.
        try:
            summ = detector.sweep(frame, cx, cy, r, sweep_thresholds)["percentiles"]
            logger.info(
                "chane_tank_monitor session %s ROI brightness distribution: "
                "min=%.1f p10=%.1f p25=%.1f p50=%.1f p75=%.1f p90=%.1f max=%.1f",
                key, summ["min"], summ["p10"], summ["p25"], summ["p50"],
                summ["p75"], summ["p90"], summ["max"],
            )
        except Exception as e:
            logger.warning("brightness distribution summary failed: %s", e)
    return sess


def infer(frame: np.ndarray, config: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
    """Run one frame of brightness-area tank-fill monitoring.

    Args:
        frame: BGR numpy array.
        config: per-stream model_config (roi_circle, brightness_threshold,
            smoothing_window, fill_calib_min/max, csv_path, stream_id).
        **kwargs: runtime may inject `model`; ignored (classical CV, no weights).

    Returns:
        Result dict matching model.yaml output.schema.
    """
    if frame is None or not isinstance(frame, np.ndarray):
        raise ValueError(f"Frame must be a numpy array, got {type(frame)}")
    if config is None:
        config = {}

    start = time.time()
    try:
        sess = _get_session(frame, config)
        roi = sess["roi"]
        cx, cy, r = roi["cx"], roi["cy"], roi["r"]
        sess["frame_n"] += 1
        # Stamp AFTER _get_session so the idle-gap check above compares against
        # the previous frame's time, not this one's.
        sess["last_frame_time"] = time.time()
        elapsed = time.time() - sess["start_time"]

        signals = sess["detector"].measure(frame, cx, cy, r)
        motion_blend = sess["motion"].update(frame, cx, cy, r)
        # Per-frame brightness-threshold sweep (analysis only).
        sweep = sess["detector"].sweep(frame, cx, cy, r, sess["sweep_thresholds"])
        sweep_fracs = sweep["bright_fractions"]

        fill_raw = signals["fill_raw"]
        # fill_raw is the SMOOTHED bright fraction mapped to 0-100 — the live
        # reading. It wobbles frame-to-frame (splashing, hose motion).
        sess["fill_running_max"] = max(sess["fill_running_max"], fill_raw)

        # DISPLAY LAYER. Two modes, both slew-rate limited to display_slew_pct
        # per frame so the number never jumps:
        #
        #  display_monotonic=False (default): the display tracks fill_raw in
        #    BOTH directions. Honest — it can fall on real drainage or a scale
        #    correction — but it visibly wobbles when the signal does.
        #
        #  display_monotonic=True: the display tracks the RUNNING MAX of
        #    fill_raw, so it only ever climbs. This is NOT the old freeze bug:
        #    the old bug displayed the running max DIRECTLY, so one early noise
        #    spike latched the value forever (the 16.9% stuck reading). Here the
        #    running max is the slew TARGET — the display keeps rising toward it
        #    and, crucially, the target itself keeps rising with the signal. It
        #    is a ratchet, not a latch.
        #
        #    Trade-off, deliberate: a monotonic meter CANNOT show a tank
        #    emptying, and it hides signal quality. It is a demo/display choice
        #    for a known fill-only clip, not a measurement improvement — which is
        #    why it is opt-in and defaults to False.
        slew = float(config.get("display_slew_pct", DEFAULT_DISPLAY_SLEW_PCT))
        monotonic = bool(config.get("display_monotonic", DEFAULT_DISPLAY_MONOTONIC))

        # TIMED RAMP (demo playback mode) — see DEFAULT_FILL_TIME_BASED above.
        # Not a measurement: a linear ramp over clip time that ignores the frame.
        time_based = bool(config.get("fill_time_based", DEFAULT_FILL_TIME_BASED))
        fill_source = "brightness"
        if time_based:
            t0 = float(config.get("fill_time_start_s", DEFAULT_FILL_TIME_START_S))
            t1 = float(config.get("fill_time_end_s", DEFAULT_FILL_TIME_END_S))
            # Prefer the true clip position (survives pause/seek/replay); fall
            # back to wall-clock elapsed if the caller doesn't send it.
            clip_t = config.get("clip_time_s")
            ramp_t = float(clip_t) if clip_t is not None else elapsed
            if t1 > t0:
                pct = (ramp_t - t0) / (t1 - t0) * 100.0
            else:
                pct = 0.0
            fill_raw = float(max(0.0, min(100.0, pct)))
            fill_source = "time_ramp"
            # The ramp is already smooth and monotonic; slew/monotonic clamps
            # would only add lag, and a seek must jump straight to the new time.
            fill_percentage = fill_raw
            sess["fill_display"] = fill_percentage
        else:
            target = sess["fill_running_max"] if monotonic else fill_raw
            prev_disp = sess.get("fill_display")
            if prev_disp is None or slew <= 0:
                fill_percentage = target
            else:
                delta = max(-slew, min(slew, target - prev_disp))
                fill_percentage = prev_disp + delta
            sess["fill_display"] = fill_percentage

        # Instrumentation row (lightweight, one per processed frame).
        # Columns: frame_n, elapsed_seconds, mean_brightness, motion_blend,
        # bright_frac_<T>... (sweep), roi_cx, roi_cy, roi_r, roi_source.
        if sess["csv_writer"] is not None:
            try:
                sess["csv_writer"].writerow(
                    [
                        sess["frame_n"], round(elapsed, 3),
                        round(signals["mean_brightness"], 2),
                        round(motion_blend, 5),
                    ]
                    + [round(sweep_fracs[int(t)], 5) for t in sess["sweep_thresholds"]]
                    + [cx, cy, r, roi["source"]]
                )
                sess["csv_file"].flush()
            except Exception as e:
                logger.warning("CSV write failed: %s", e)

        return {
            "fill_percentage": round(fill_percentage, 2),   # live smoothed reading, display
            "fill_raw": round(fill_raw, 2),                  # same smoothed mapping (unclamped), analysis
            "bright_fraction": round(signals["bright_fraction"], 5),
            "bright_fraction_smoothed": round(signals["bright_fraction_smoothed"], 5),
            "mean_brightness": round(signals["mean_brightness"], 2),
            "motion_blend": round(motion_blend, 5),
            "confidence": 0.8,
            "roi": {
                "cx": int(cx), "cy": int(cy), "r": int(r),
                "source": roi["source"],
            },
            "metadata": {
                "inference_time_ms": round((time.time() - start) * 1000, 2),
                "model_name": "chane_tank_monitor",
                "model_version": "1.0.0",
                "frame_n": sess["frame_n"],
                "elapsed_seconds": round(elapsed, 3),
                "brightness_threshold": sess["detector"].brightness_threshold,
                "smoothing_window": sess["detector"].smoothing_window,
                "fill_calib_min": sess["detector"].fill_calib_min,
                "fill_calib_max": sess["detector"].fill_calib_max,
                "fill_running_max": round(sess["fill_running_max"], 2),
                # What the mapping ACTUALLY used this frame. Under auto-cal these
                # are the derived values, not the config constants above.
                "auto_calibrate": sess["detector"].auto_calibrate,
                "display_monotonic": bool(config.get("display_monotonic", DEFAULT_DISPLAY_MONOTONIC)),
                # "time_ramp" => fill_percentage is a clip-time ramp, NOT measured
                # from the video. "brightness" => measured from the ROI.
                "fill_source": fill_source,
                "fill_time_based": time_based,
                "calib_source": signals["calib_source"],
                "calib_min_active": round(signals["calib_min_active"], 5),
                "calib_max_active": round(signals["calib_max_active"], 5),
                "csv_path": sess["csv_path"],
            },
        }

    except Exception as e:
        logger.error("chane_tank_monitor inference failed: %s", e, exc_info=True)
        return _stub_response()


def _stub_response() -> Dict[str, Any]:
    """Safe zeroed result when inference can't run."""
    return {
        "fill_percentage": 0.0,
        "fill_raw": 0.0,
        "bright_fraction": 0.0,
        "bright_fraction_smoothed": 0.0,
        "mean_brightness": 0.0,
        "motion_blend": 0.0,
        "confidence": 0.0,
        "roi": {"cx": 0, "cy": 0, "r": 0, "source": "fallback"},
        "metadata": {
            "model_name": "chane_tank_monitor",
            "model_version": "1.0.0",
            "mode": "stub",
            "note": "Inference unavailable - using stub response",
        },
    }
