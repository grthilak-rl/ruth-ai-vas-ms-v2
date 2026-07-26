"""
Brightness-area fill detection for chane_tank_monitor.

Replaces the old motion-blend fill measure. As a top-down circular tank fills,
the bright/reflective liquid-surface AREA grows; motion peaks mid-fill and goes
calm near full (misleading). So FILL is measured by the fraction of bright
pixels inside the locked circular ROI.

This module provides:
  * BrightnessFillDetector - bright-pixel-fraction + temporal smoothing + 0-100
    mapping with config-overridable calibration points.
  * MotionBlendProbe       - a lightweight frame-diff motion signal kept ONLY
    for the instrumentation CSV (so we can confirm motion diverges from
    brightness). NOT used for fill.
  * detect_radius_from_center - unchanged ray-cast radius estimate, reused by
    the frontend's click-to-set-ROI flow (and config-less fallbacks).

All tunables are passed in from config (see inference.py); nothing here is
hardcoded-and-forgotten.
"""

from collections import deque

import cv2
import numpy as np

# ---- Ray-cast radius detection (unchanged from the original script) ----------

RAY_DIRECTIONS = 72
RAY_MAX_LEN_FRAC = 0.48
RAY_EDGE_JUMP = 25
RAY_MIN_VALID_FRAC = 0.40


def detect_radius_from_center(gray, cx, cy, fH, fW):
    """Estimate tank-opening radius by casting rays from (cx, cy) until the
    brightness jumps past the rim. Returns the median hit radius, or a
    fraction-of-frame fallback when too few rays land on an edge."""
    max_len = int(min(fH, fW) * RAY_MAX_LEN_FRAC)
    interior_r = max(5, max_len // 10)
    ys = np.arange(max(0, cy - interior_r), min(fH, cy + interior_r))
    xs = np.arange(max(0, cx - interior_r), min(fW, cx + interior_r))
    if ys.size == 0 or xs.size == 0:
        return int(min(fH, fW) * 0.15)

    interior_mean = float(np.mean(gray[np.ix_(ys, xs)]))
    angles = np.linspace(0, 2 * np.pi, RAY_DIRECTIONS, endpoint=False)
    radii = []

    for angle in angles:
        dx, dy = np.cos(angle), np.sin(angle)
        for d in range(interior_r + 2, max_len):
            px = int(round(cx + dx * d))
            py = int(round(cy + dy * d))
            if not (0 <= px < fW and 0 <= py < fH):
                break
            if float(gray[py, px]) - interior_mean > RAY_EDGE_JUMP:
                radii.append(d)
                break

    min_valid = int(RAY_DIRECTIONS * RAY_MIN_VALID_FRAC)
    if len(radii) >= min_valid:
        return int(np.median(radii))
    return int(min(fH, fW) * 0.15)


def _circle_mask(roi_shape, r):
    """Binary mask of the inscribed circle inside a 2r-ish ROI box."""
    h, w = roi_shape[:2]
    mask = np.zeros((h, w), np.uint8)
    cv2.circle(mask, (w // 2, h // 2), max(1, min(h, w) // 2 - 2), 255, -1)
    return mask


def _extract_box(frame, cx, cy, r):
    """Crop the bounding box of the ROI circle, clamped to the frame."""
    x0 = max(0, cx - r)
    y0 = max(0, cy - r)
    x1 = min(frame.shape[1], cx + r)
    y1 = min(frame.shape[0], cy + r)
    return frame[y0:y1, x0:x1]


# ---- Brightness-area fill detector ------------------------------------------

class BrightnessFillDetector:
    """Measures fill as the fraction of bright pixels inside the circular ROI.

    Tunables (all config-overridable, defaults set in inference.py):
      brightness_threshold : gray value [0-255]; pixels above = "bright surface"
      smoothing_window      : frames to average bright_fraction over
      fill_calib_min        : bright_fraction considered 0% full (empty offset)
      fill_calib_max        : bright_fraction considered 100% full

    AUTO-CALIBRATION (auto_calibrate=True)
    --------------------------------------
    Fixed calib points do not survive a feed change: on the dark feed empty/full
    were ~[0.06, 0.115]; on the brighter feed EMPTY alone reads ~0.143 — above
    the dark feed's FULL. The feed-to-feed offset (+0.08) exceeds the whole fill
    signal (+0.047), so any constant pins the display at 0% or 100%.

    Auto-cal derives the mapping from the session's OWN observed range:

      calib_min  <- empty anchor: the median smoothed bright_fraction over the
                    first `auto_warmup_frames` frames. The fill starts empty, so
                    the opening frames ARE the 0% reference. Median (not min)
                    resists a splash/glint outlier.
      calib_max  <- max(empty_anchor + auto_prior_span, running_max)
                    Seeded from a per-camera prior span so a live fill has a
                    sane 100% target BEFORE full is ever observed, then allowed
                    to GROW if the real fill overshoots the prior.

    Why not pure running min/max: during a monotonic rise the current value IS
    the running max, so pct = (v-min)/(max-min) pins ~100% from ~frame 5 while
    the tank is actually empty (verified against the real dark-feed fill). It
    only works in replay, where the full range is already known. The prior-seeded
    max is what makes the LIVE reading meaningful before "full" is seen.
    """

    def __init__(self, brightness_threshold, smoothing_window,
                 fill_calib_min, fill_calib_max,
                 auto_calibrate=False, auto_warmup_frames=30,
                 auto_prior_span=0.05, auto_min_span=0.02,
                 auto_max_grow_rate=0.02):
        self.brightness_threshold = float(brightness_threshold)
        self.smoothing_window = int(smoothing_window)
        self.fill_calib_min = float(fill_calib_min)
        self.fill_calib_max = float(fill_calib_max)
        self.history = deque(maxlen=self.smoothing_window)

        # --- auto-calibration state ---
        self.auto_calibrate = bool(auto_calibrate)
        self.auto_warmup_frames = int(auto_warmup_frames)
        self.auto_prior_span = float(auto_prior_span)
        self.auto_min_span = float(auto_min_span)
        self.auto_max_grow_rate = float(auto_max_grow_rate)
        self._warmup_samples = []      # smoothed values during warmup
        self._empty_anchor = None      # derived calib_min (0% reference)
        self._auto_max = None          # derived calib_max (100% target)
        self._frames_seen = 0

    # -- auto-calibration ------------------------------------------------

    def _update_auto_calibration(self, smoothed):
        """Derive/refresh (calib_min, calib_max) from this session's own range.

        During warmup the tank is assumed empty (the fill has not started), so
        those frames define the 0% anchor. After warmup the anchor is frozen —
        it must NOT track the rising liquid, or 0% would chase the signal and
        the reading would never climb.
        """
        self._frames_seen += 1

        if self._empty_anchor is None:
            self._warmup_samples.append(smoothed)
            if self._frames_seen < self.auto_warmup_frames:
                return None, None            # not calibrated yet
            # Median over warmup = robust empty anchor.
            ordered = sorted(self._warmup_samples)
            self._empty_anchor = ordered[len(ordered) // 2]
            self._auto_max = self._empty_anchor + self.auto_prior_span

        # Running max may only GROW, and only gradually: a glint spike must not
        # yank the scale (which would make the displayed % lurch downward).
        if smoothed > self._auto_max:
            ceiling = self._auto_max + self.auto_max_grow_rate
            self._auto_max = min(smoothed, ceiling)

        lo = self._empty_anchor
        hi = max(self._auto_max, lo + self.auto_min_span)
        return lo, hi

    def active_calibration(self):
        """The (lo, hi) actually in use this frame, and how it was derived.
        Surfaced in metadata so the operator can see what auto-cal chose."""
        if self.auto_calibrate and self._empty_anchor is not None:
            lo = self._empty_anchor
            hi = max(self._auto_max, lo + self.auto_min_span)
            return lo, hi, "auto"
        if self.auto_calibrate:
            return self.fill_calib_min, self.fill_calib_max, "auto_warmup"
        return self.fill_calib_min, self.fill_calib_max, "fixed"

    def measure(self, frame, cx, cy, r):
        """Return per-frame brightness signals for the locked ROI.

        Returns dict: bright_fraction (raw), bright_fraction_smoothed,
        mean_brightness, fill_raw (mapped, unclamped-direction), all floats.
        """
        box = _extract_box(frame, cx, cy, r)
        if box.size == 0:
            lo, hi, calib_source = self.active_calibration()
            return {
                "bright_fraction": 0.0,
                "bright_fraction_smoothed": 0.0,
                "mean_brightness": 0.0,
                "fill_raw": 0.0,
                "calib_min_active": float(lo),
                "calib_max_active": float(hi),
                "calib_source": calib_source,
            }

        gray = cv2.cvtColor(box, cv2.COLOR_BGR2GRAY)
        mask = _circle_mask(box.shape, r)
        inside = mask == 255
        total = int(np.count_nonzero(inside))
        if total == 0:
            lo, hi, calib_source = self.active_calibration()
            return {
                "bright_fraction": 0.0,
                "bright_fraction_smoothed": 0.0,
                "mean_brightness": 0.0,
                "fill_raw": 0.0,
                "calib_min_active": float(lo),
                "calib_max_active": float(hi),
                "calib_source": calib_source,
            }

        vals = gray[inside]
        bright = int(np.count_nonzero(vals > self.brightness_threshold))
        bright_fraction = bright / total
        mean_brightness = float(np.mean(vals))

        self.history.append(bright_fraction)
        smoothed = float(np.mean(self.history))

        if self.auto_calibrate:
            self._update_auto_calibration(smoothed)

        lo, hi, calib_source = self.active_calibration()
        fill_raw = self._map_to_percent(smoothed, lo, hi)

        return {
            "bright_fraction": float(bright_fraction),
            "bright_fraction_smoothed": smoothed,
            "mean_brightness": mean_brightness,
            "fill_raw": fill_raw,
            "calib_min_active": float(lo),
            "calib_max_active": float(hi),
            "calib_source": calib_source,
        }

    def sweep(self, frame, cx, cy, r, thresholds):
        """Brightness-threshold sweep for analysis. Returns, for the ROI circle:
        - 'bright_fractions': {T: fraction > T} for each T in `thresholds`
        - 'percentiles': brightness distribution (min,p10,p25,p50,p75,p90,max)
        Independent of the live measure(); purely instrumentation."""
        box = _extract_box(frame, cx, cy, r)
        empty = {
            "bright_fractions": {int(t): 0.0 for t in thresholds},
            "percentiles": {k: 0.0 for k in
                            ("min", "p10", "p25", "p50", "p75", "p90", "max")},
        }
        if box.size == 0:
            return empty
        gray = cv2.cvtColor(box, cv2.COLOR_BGR2GRAY)
        mask = _circle_mask(box.shape, r)
        vals = gray[mask == 255]
        total = int(vals.size)
        if total == 0:
            return empty
        vals_f = vals.astype(np.float32)
        fractions = {
            int(t): float(np.count_nonzero(vals > float(t)) / total)
            for t in thresholds
        }
        p = np.percentile(vals_f, [0, 10, 25, 50, 75, 90, 100])
        percentiles = {
            "min": float(p[0]), "p10": float(p[1]), "p25": float(p[2]),
            "p50": float(p[3]), "p75": float(p[4]), "p90": float(p[5]),
            "max": float(p[6]),
        }
        return {"bright_fractions": fractions, "percentiles": percentiles}

    def _map_to_percent(self, smoothed, lo=None, hi=None):
        """Map smoothed bright fraction to 0-100 via calibration points.
        `lo`/`hi` default to the fixed config calibration; auto-cal passes its
        derived range instead. Callers keep the result as fill_raw for analysis."""
        if lo is None:
            lo = self.fill_calib_min
        if hi is None:
            hi = self.fill_calib_max
        if hi <= lo:
            return 0.0
        pct = (smoothed - lo) / (hi - lo) * 100.0
        return float(max(0.0, min(100.0, pct)))


# ---- Motion blend probe (instrumentation only — NOT used for fill) ----------

class MotionBlendProbe:
    """Lightweight frame-diff motion signal, kept only so the CSV can show
    motion alongside brightness. This is intentionally simpler than the old
    TemporalEngine (no optical-flow / MOG2) — it just needs to demonstrate the
    motion-vs-brightness divergence, cheaply."""

    def __init__(self):
        self.prev_gray = None

    def update(self, frame, cx, cy, r):
        box = _extract_box(frame, cx, cy, r)
        if box.size == 0:
            return 0.0
        gray = cv2.cvtColor(box, cv2.COLOR_BGR2GRAY)
        mask = _circle_mask(box.shape, r)
        inside = mask == 255
        if self.prev_gray is not None and self.prev_gray.shape == gray.shape:
            diff = cv2.absdiff(gray, self.prev_gray)
            vals = diff[inside].astype(np.float32)
            blend = float(np.mean(vals)) / 255.0 if vals.size else 0.0
        else:
            blend = 0.0
        self.prev_gray = gray.copy()
        return blend
