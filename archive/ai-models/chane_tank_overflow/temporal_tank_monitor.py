"""
=============================================================================
TANK MONITOR v3 — Manual Click Calibration + Per-Video Cache
=============================================================================
Fix in this version
-------------------
  NULL window handler crash on Linux Qt builds is resolved by:
    * Short ASCII window name (long names with special chars fail on Qt)
    * WINDOW_AUTOSIZE  (more reliably initialised than WINDOW_NORMAL)
    * Poll cv2.getWindowProperty() until the native handle is live
      BEFORE calling setMouseCallback

How it works
------------
  FIRST RUN on a new video / camera:
    1. Calibration window opens on first frame.
    2. Click the CENTER of the tank opening.
    3. Radius auto-detected via ray-casting (72 rays; median of hits).
    4. Scroll wheel UP/DOWN to fine-tune radius (+/- 2 px per tick).
    5. ENTER or SPACE to confirm -> analysis begins immediately.
    6. (cx, cy, r) saved to roi_cache.json keyed by video fingerprint.

  SUBSEQUENT RUNS: cache hit -> zero interaction, straight to analysis.

  Press R during playback to recalibrate.
  Press Q or ESC to quit.
=============================================================================
"""

import cv2
import numpy as np
from collections import deque
import csv, os, json, hashlib
from datetime import datetime

# =============================================================================
#  CONFIG
# =============================================================================

VIDEO_SOURCE    = r"/home/ai/trimmed/cam2-029.mp4"
OUTPUT_DIR      = r"/home/ai/Downloads"
SAVE_VIDEO      = True
CACHE_FILE      = os.path.join(OUTPUT_DIR, "roi_cache.json")

TEMPORAL_WINDOW = 90
W_FRAMEDIFF     = 0.40
W_OPTFLOW       = 0.35
W_BGRESID       = 0.25
HEATMAP_ALPHA   = 0.55

RAY_DIRECTIONS     = 72
RAY_MAX_LEN_FRAC   = 0.48
RAY_EDGE_JUMP      = 25
RAY_MIN_VALID_FRAC = 0.40

# Tank fill level detection
FILL_WINDOW_SIZE = 15            # Number of frames to average
FILL_THRESHOLD   = 0.120         # Blend value threshold for 90% fill
FILL_PERCENT_90  = 90            # Percentage fill when threshold is met

PROCESS_FRAME_INTERVAL = 12      # Process detection every N frames (≈2 fps for 25 fps video)


# =============================================================================
#  ROI CACHE
# =============================================================================

class ROICache:
    def __init__(self, path):
        self.path  = path
        self._data = {}
        if os.path.isfile(path):
            try:
                with open(path) as f:
                    self._data = json.load(f)
            except Exception:
                pass

    @staticmethod
    def fingerprint(src, frame):
        h = hashlib.sha256()
        h.update(src.encode())
        h.update(frame.tobytes()[:8192])
        return h.hexdigest()[:24]

    def get(self, key):
        e = self._data.get(key)
        return (e["cx"], e["cy"], e["r"]) if e else None

    def set(self, key, cx, cy, r):
        self._data[key] = {"cx": cx, "cy": cy, "r": r,
                           "ts": datetime.now().isoformat(timespec="seconds")}
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2)
        print(f"[Cache] Saved ({cx},{cy},r={r})  key={key}")

    def delete(self, key):
        if key in self._data:
            del self._data[key]
            with open(self.path, "w") as f:
                json.dump(self._data, f, indent=2)


# =============================================================================
#  RADIUS AUTO-DETECTION
# =============================================================================

def detect_radius_from_center(gray, cx, cy, fH, fW):
    max_len    = int(min(fH, fW) * RAY_MAX_LEN_FRAC)
    interior_r = max(5, max_len // 10)
    ys = np.arange(max(0, cy - interior_r), min(fH, cy + interior_r))
    xs = np.arange(max(0, cx - interior_r), min(fW, cx + interior_r))
    if ys.size == 0 or xs.size == 0:
        return int(min(fH, fW) * 0.15)

    interior_mean = float(np.mean(gray[np.ix_(ys, xs)]))
    angles = np.linspace(0, 2 * np.pi, RAY_DIRECTIONS, endpoint=False)
    radii  = []

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
        r = int(np.median(radii))
        print(f"[Radius] r={r}  ({len(radii)}/{RAY_DIRECTIONS} rays valid)")
        return r
    fallback = int(min(fH, fW) * 0.15)
    print(f"[Radius] Too few rays ({len(radii)}), fallback r={fallback}")
    return fallback


# =============================================================================
#  CALIBRATION UI
# =============================================================================

class CalibrationUI:
    def __init__(self, frame):
        self.fH, self.fW = frame.shape[:2]
        # Pre-scale frame so it fits on screen without needing WINDOW_NORMAL
        self._scale = min(1.0, 1280.0 / max(self.fW, 1),
                              720.0  / max(self.fH, 1))
        dW = int(self.fW * self._scale)
        dH = int(self.fH * self._scale)
        self._base = cv2.resize(frame, (dW, dH)) if self._scale < 1.0 \
                     else frame.copy()
        self._dH, self._dW = self._base.shape[:2]
        self.gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # All coordinates stored in DISPLAY space
        self.cx = None
        self.cy = None
        self.r  = int(min(self._dH, self._dW) * 0.15)

    def _mouse_cb(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            # Ray-cast in original frame space, store result in display space
            fx = int(x / self._scale)
            fy = int(y / self._scale)
            r_orig = detect_radius_from_center(
                self.gray, fx, fy, self.fH, self.fW)
            self.cx = x
            self.cy = y
            self.r  = int(r_orig * self._scale)
            print(f"[Calib] display=({x},{y})  frame=({fx},{fy})  r={r_orig}")

        elif event == cv2.EVENT_MOUSEWHEEL:
            if self.cx is not None:
                self.r = max(5, self.r + (2 if flags > 0 else -2))

    def _draw(self):
        out = self._base.copy()
        dH, dW = self._dH, self._dW

        for i, txt in enumerate([
            "CALIBRATION: click the CENTER of the tank opening",
            "Scroll = adjust radius    ENTER/SPACE = confirm    ESC = quit",
        ]):
            cv2.putText(out, txt, (10, 26 + i * 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.60, (0, 0, 0), 4)
            cv2.putText(out, txt, (10, 26 + i * 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.60, (50, 230, 255), 2)

        if self.cx is not None:
            cx, cy, r = self.cx, self.cy, self.r
            ov = out.copy()
            cv2.circle(ov, (cx, cy), r, (0, 255, 180), -1)
            cv2.addWeighted(ov, 0.18, out, 0.82, 0, out)
            cv2.circle(out, (cx, cy), r,     (0, 255, 100), 3)
            cv2.circle(out, (cx, cy), r - 4, (0, 200, 80),  1)
            cv2.line(out, (cx - 12, cy), (cx + 12, cy), (0, 255, 100), 2)
            cv2.line(out, (cx, cy - 12), (cx, cy + 12), (0, 255, 100), 2)
            fx     = int(cx / self._scale)
            fy     = int(cy / self._scale)
            r_real = int(r  / self._scale)
            lbl = f"frame cx={fx}  cy={fy}  r={r_real}"
            cv2.putText(out, lbl, (10, dH - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
            cv2.putText(out, lbl, (10, dH - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (50, 230, 255), 1)
        return out

    def run(self):
        """
        Returns (cx, cy, r) in original frame coordinates, or None.

        The three-step fix for NULL window handler on Linux Qt:
          1. Short ASCII window name
          2. WINDOW_AUTOSIZE flag
          3. Poll WND_PROP_VISIBLE before setMouseCallback
        """
        WIN = "Calibration"          # SHORT, ASCII only — critical for Qt
        cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
        cv2.imshow(WIN, self._draw())

        # Wait up to 5 s for the native handle to be ready
        for _ in range(100):
            cv2.waitKey(50)
            try:
                prop = cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE)
                if prop >= 0:
                    break
            except Exception:
                pass

        cv2.setMouseCallback(WIN, self._mouse_cb)
        print("\n[Calib] Click the CENTER of the tank opening in the window.")
        print("        Scroll to adjust radius, then press ENTER or SPACE.\n")

        while True:
            cv2.imshow(WIN, self._draw())
            key = cv2.waitKey(30) & 0xFF

            if key in (13, ord(' ')):
                if self.cx is None:
                    print("[Calib] Please click the tank center first.")
                    continue
                cv2.destroyWindow(WIN)
                cv2.waitKey(1)
                fx     = int(self.cx / self._scale)
                fy     = int(self.cy / self._scale)
                r_real = int(self.r  / self._scale)
                return fx, fy, r_real

            elif key == 27:
                cv2.destroyWindow(WIN)
                cv2.waitKey(1)
                return None


# =============================================================================
#  TANK FILL LEVEL DETECTOR
# =============================================================================

class TankFillDetector:
    def __init__(self, window_size=FILL_WINDOW_SIZE, threshold=FILL_THRESHOLD):
        self.window_size = window_size
        self.threshold = threshold
        self.blend_history = deque(maxlen=window_size)
        self.fill_90_detected = False
        self.fill_frame = None

    def update(self, blend_mean, frame_number):
        """Update with current blend mean value and return fill status"""
        self.blend_history.append(blend_mean)

        # Check if we have enough frames
        if len(self.blend_history) == self.window_size:
            avg_blend = np.mean(self.blend_history)

            # Check if average blend meets threshold
            if avg_blend >= self.threshold and not self.fill_90_detected:
                self.fill_90_detected = True
                self.fill_frame = frame_number
                print(f"\n{'='*60}")
                print(f"TANK 90% FILLED DETECTED at frame {frame_number}!")
                print(f"Average blend over last {self.window_size} frames: {avg_blend:.2f}")
                print(f"{'='*60}\n")
                return True, avg_blend

        return False, np.mean(self.blend_history) if self.blend_history else 0.0

    def get_fill_percentage(self):
        """Calculate approximate fill percentage based on current average"""
        if len(self.blend_history) < self.window_size:
            return 0.0

        avg_blend = np.mean(self.blend_history)
        # Scale 0-100 threshold to 0-90 percent fill
        percentage = min(90.0, (avg_blend / self.threshold) * FILL_PERCENT_90)
        return percentage


# =============================================================================
#  TEMPORAL ENGINE
# =============================================================================

class TemporalEngine:
    def __init__(self, window=TEMPORAL_WINDOW):
        self.window    = window
        self.prev_gray = None
        self.prev_roi  = None
        self.bg2       = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=20, detectShadows=False)
        self.blend_history    = deque(maxlen=window)
        self.last_stats       = {}
        self.last_heatmap_bgr = None

    @staticmethod
    def _extract(frame, cx, cy, r):
        x0 = max(0, cx - r);  y0 = max(0, cy - r)
        x1 = min(frame.shape[1], cx + r)
        y1 = min(frame.shape[0], cy + r)
        roi  = frame[y0:y1, x0:x1].copy()
        mask = np.zeros(roi.shape[:2], np.uint8)
        cv2.circle(mask, (cx - x0, cy - y0), max(1, r - 5), 255, -1)
        return roi, mask, x0, y0

    def _frame_diff(self, g):
        if self.prev_roi is not None and self.prev_roi.shape == g.shape:
            d = cv2.absdiff(g, self.prev_roi).astype(np.float32)
        else:
            d = np.zeros(g.shape, np.float32)
        self.prev_roi = g.copy()
        return d

    def _optical_flow(self, g):
        if self.prev_gray is not None:
            try:
                h, w   = g.shape
                sc     = min(1.0, 160.0 / max(h, w))
                sw, sh = max(1, int(w * sc)), max(1, int(h * sc))
                flow   = cv2.calcOpticalFlowFarneback(
                    cv2.resize(self.prev_gray, (sw, sh)),
                    cv2.resize(g, (sw, sh)),
                    None, 0.5, 3, 15, 3, 5, 1.2, 0)
                mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                out    = cv2.resize(mag, (w, h)) / max(sc, 1e-6)
            except Exception:
                out = np.zeros(g.shape, np.float32)
        else:
            out = np.zeros(g.shape, np.float32)
        self.prev_gray = g.copy()
        return out.astype(np.float32)

    def _bg_residual(self, roi):
        return self.bg2.apply(roi, learningRate=0.002).astype(np.float32)

    @staticmethod
    def _norm(arr, mask):
        v = arr[mask == 255]
        if v.size == 0:
            return np.zeros_like(arr)
        p = float(np.percentile(v, 99))
        return np.zeros_like(arr) if p < 1e-6 else \
               np.clip(arr / p, 0, 1).astype(np.float32)

    @staticmethod
    def _stats(arr, mask, pfx):
        v = arr[mask == 255].astype(float)
        if v.size == 0:
            return {f"{pfx}_mean": 0., f"{pfx}_std": 0., f"{pfx}_max": 0.}
        return {f"{pfx}_mean": round(float(np.mean(v)), 4),
                f"{pfx}_std":  round(float(np.std(v)),  4),
                f"{pfx}_max":  round(float(np.max(v)),  4)}

    def update(self, frame, cx, cy, r):
        roi, mask, x0, y0 = self._extract(frame, cx, cy, r)
        fH, fW = frame.shape[:2]
        canvas = np.zeros((fH, fW, 3), np.uint8)
        if roi.size == 0:
            return self.last_stats, canvas

        g    = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        fd_n = self._norm(self._frame_diff(g),    mask)
        of_n = self._norm(self._optical_flow(g),  mask)
        bg_n = self._norm(self._bg_residual(roi), mask)
        blend = W_FRAMEDIFF * fd_n + W_OPTFLOW * of_n + W_BGRESID * bg_n
        blend[mask == 0] = 0.0

        heat = cv2.applyColorMap((blend * 255).astype(np.uint8),
                                 cv2.COLORMAP_JET)
        heat[mask == 0] = 0
        rh, rw = roi.shape[:2]
        canvas[y0:y0+rh, x0:x0+rw] = heat

        stats = {}
        for a, p in [(fd_n,"fd"),(of_n,"of"),(bg_n,"bg"),(blend,"blend")]:
            stats.update(self._stats(a, mask, p))

        self.blend_history.append(stats["blend_mean"])
        lvls = np.array(self.blend_history)
        flag, reason = False, ""
        if len(lvls) >= 2 and abs(lvls[-1] - lvls[-2]) > 0.15:
            flag   = True
            reason = f"Blend jump {abs(lvls[-1]-lvls[-2]):.3f}"
        if len(lvls) >= 5 and np.std(lvls) > 0.12:
            flag   = True
            reason += (" | " if reason else "") + f"High std={np.std(lvls):.3f}"
        if stats["fd_mean"] > 0.6:
            flag   = True
            reason += (" | " if reason else "") + f"High fd={stats['fd_mean']:.3f}"

        stats["anomaly_flag"]   = flag
        stats["anomaly_reason"] = reason
        self.last_stats         = stats
        self.last_heatmap_bgr   = canvas
        return stats, canvas


# =============================================================================
#  CSV LOGGER
# =============================================================================

class CSVLogger:
    COLS = ["frame","timestamp","roi_cx","roi_cy","roi_r",
            "fd_mean","fd_std","fd_max","of_mean","of_std","of_max",
            "bg_mean","bg_std","bg_max","blend_mean","blend_std","blend_max",
            "anomaly_flag","anomaly_reason",
            "fill_90_detected","fill_frame","fill_percentage","avg_blend_40frames"]

    def __init__(self, output_dir="."):
        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(output_dir, f"tank_heatmap_{ts}.csv")
        self._fh  = open(self.path, "w", newline="", encoding="utf-8")
        self._wr  = csv.DictWriter(self._fh, fieldnames=self.COLS,
                                   extrasaction="ignore")
        self._wr.writeheader()
        self._fh.flush()
        print(f"CSV -> {self.path}")

    def write(self, row):
        self._wr.writerow({c: row.get(c, "") for c in self.COLS})
        self._fh.flush()

    def close(self):
        self._fh.close()


# =============================================================================
#  DRAW (side‑by‑side, blend text only on right)
# =============================================================================

def draw_frame(frame, circle, heatmap, stats, frame_n, fill_detector, side_by_side=True):
    fH, fW = frame.shape[:2]

    # --- Left side: original frame with basic overlay (no blend text) ---
    left = frame.copy()
    if circle:
        cx, cy, r = circle
        anom = stats.get("anomaly_flag", False)
        bm   = stats.get("blend_mean", 0.0)
        fill_90_detected = fill_detector.fill_90_detected

        # Circle colour (same as before)
        if fill_90_detected:
            col = (0, 255, 255)
        else:
            col = (0, 0, 220) if anom else ((0, 80, 255) if bm > 0.4 else (0, 210, 0))

        cv2.circle(left, (cx, cy), r, col, 3)
        cv2.circle(left, (cx, cy), r - 5, col, 1)
        cv2.circle(left, (cx, cy), 4, col, -1)
        # No blend text on left side

    # Anomaly text on left side (top)
    if stats.get("anomaly_flag"):
        cv2.putText(left, f"ANOMALY: {stats.get('anomaly_reason','')[:90]}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0,0,255), 2)

    # Statistics on left side
    y0 = 55 if stats.get("anomaly_flag") else 22
    for i, ln in enumerate([
        f"fd {stats.get('fd_mean',0):.3f}  of {stats.get('of_mean',0):.3f}  bg {stats.get('bg_mean',0):.3f}",
        f"blend mean={stats.get('blend_mean',0):.3f}  std={stats.get('blend_std',0):.3f}  max={stats.get('blend_max',0):.3f}",
    ]):
        cv2.putText(left, ln, (10, y0 + i*22), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0,0,0), 3)
        cv2.putText(left, ln, (10, y0 + i*22), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (200,230,200), 1)

    # Fill indicator on left side
    fill_pct = fill_detector.get_fill_percentage()
    avg_blend = np.mean(fill_detector.blend_history) if fill_detector.blend_history else 0
    bar_x, bar_y = 10, y0 + 50
    bar_w, bar_h = 200, 20
    cv2.rectangle(left, (bar_x, bar_y), (bar_x+bar_w, bar_y+bar_h), (50,50,50), -1)
    fill_w = int(bar_w * (fill_pct / FILL_PERCENT_90))
    fill_color = (0,255,0) if fill_pct < FILL_PERCENT_90 else (0,255,255)
    cv2.rectangle(left, (bar_x, bar_y), (bar_x+fill_w, bar_y+bar_h), fill_color, -1)
    cv2.rectangle(left, (bar_x, bar_y), (bar_x+bar_w, bar_y+bar_h), (200,200,200), 1)
    status_text = f"Fill: {fill_pct:.1f}%"
    if fill_detector.fill_90_detected:
        status_text += " [90% FILLED!]"
        cv2.putText(left, status_text, (bar_x, bar_y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,255), 2)
    else:
        cv2.putText(left, status_text, (bar_x, bar_y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200,230,200), 1)
    cv2.putText(left, f"Avg blend (40f): {avg_blend:.2f}", (bar_x, bar_y+bar_h+18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200,200,200), 1)

    # Frame counter / help text on left
    cv2.putText(left, f"f{frame_n}  R=recalibrate  Q=quit", (8, fH-8), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150,150,150), 1)

    # --- Right side: heatmap overlay (with blend text) ---
    if circle and heatmap is not None:
        cx, cy, r = circle
        cmask = np.zeros((fH, fW), np.uint8)
        cv2.circle(cmask, (cx, cy), max(1, r-5), 255, -1)
        m3 = np.stack([cmask]*3, -1).astype(np.float32) / 255.0
        right = np.clip(
            frame.astype(np.float32) * (1 - HEATMAP_ALPHA * m3) +
            heatmap.astype(np.float32) * (HEATMAP_ALPHA * m3),
            0, 255).astype(np.uint8)

        # Circle and blend text on right side
        anom = stats.get("anomaly_flag", False)
        bm   = stats.get("blend_mean", 0.0)
        if fill_90_detected:
            col = (0, 255, 255)
        else:
            col = (0, 0, 220) if anom else ((0, 80, 255) if bm > 0.4 else (0, 210, 0))
        cv2.circle(right, (cx, cy), r, col, 3)
        cv2.circle(right, (cx, cy), r-5, col, 1)
        cv2.circle(right, (cx, cy), 4, col, -1)

        # Blend value text ONLY on right side
        lbl = f"blend {bm:.3f}"
        fs = max(0.5, r / 130.0)
        th = max(1, int(fs * 2))
        tsz = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, fs, th)[0]
        tx, ty = cx - tsz[0] // 2, cy + tsz[1] // 2
        cv2.putText(right, lbl, (tx+1, ty+1), cv2.FONT_HERSHEY_SIMPLEX, fs, (0,0,0), th+1)
        cv2.putText(right, lbl, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, fs, (255,255,255), th)

        # Optional anomaly indicator on right
        if stats.get("anomaly_flag"):
            cv2.putText(right, f"ANOMALY", (10,30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0,0,255), 2)
    else:
        right = frame.copy()

    # Combine side by side
    if side_by_side:
        combined = np.hstack([left, right])
        return combined
    else:
        return right  # fallback to original behaviour


# =============================================================================
#  MAIN
# =============================================================================

def run():
    cap = cv2.VideoCapture(VIDEO_SOURCE)
    if not cap.isOpened():
        print(f"Cannot open: {VIDEO_SOURCE}")
        return

    ret, first_frame = cap.read()
    if not ret:
        print("Cannot read first frame.")
        return
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cache     = ROICache(CACHE_FILE)
    cache_key = ROICache.fingerprint(VIDEO_SOURCE, first_frame)
    print(f"[ROI] Cache key: {cache_key}")

    cached = cache.get(cache_key)
    if cached:
        cx, cy, r = cached
        print(f"[ROI] Cache hit -> ({cx},{cy},r={r})")
        circle = (cx, cy, r)
    else:
        print("[ROI] No cache — opening calibration window...")
        result = CalibrationUI(first_frame).run()
        if result is None:
            print("Cancelled.")
            cap.release()
            return
        cx, cy, r = result
        cache.set(cache_key, cx, cy, r)
        circle = (cx, cy, r)

    temporal = TemporalEngine()
    logger   = CSVLogger(OUTPUT_DIR)
    fill_detector = TankFillDetector()

    writer, vpath = None, ""
    if SAVE_VIDEO:
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        vpath = os.path.join(OUTPUT_DIR, f"tank_heatmap_{ts}.mp4")

    WIN = "TankMonitor"
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    print(f"\n[Main] ROI ({cx},{cy},r={r})  —  R=recalibrate  Q=quit\n")
    print(f"[Main] Processing detection every {PROCESS_FRAME_INTERVAL} frames (~2fps)\n")

    frame_n = 0
    stats = {}
    heatmap = None
    prev_stats = {}
    prev_heatmap = None

    while True:
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue

        frame_n += 1
        fH, fW = frame.shape[:2]

        if SAVE_VIDEO and writer is None:
            # Output width is doubled for side‑by‑side
            writer = cv2.VideoWriter(
                vpath, cv2.VideoWriter_fourcc(*"mp4v"), 25.0, (fW*2, fH))
            print(f"Video -> {vpath}")

        cx, cy, r = circle

        # Process detection only every N frames
        if frame_n % PROCESS_FRAME_INTERVAL == 0 or frame_n == 1:
            stats, heatmap = temporal.update(frame, cx, cy, r)
            prev_stats = stats
            prev_heatmap = heatmap

            # Update fill detector with current blend mean
            blend_mean = stats.get("blend_mean", 0.0)
            fill_90_detected, avg_blend = fill_detector.update(blend_mean, frame_n)
        else:
            # Reuse previous results
            stats = prev_stats
            heatmap = prev_heatmap
            fill_90_detected = fill_detector.fill_90_detected
            avg_blend = np.mean(fill_detector.blend_history) if fill_detector.blend_history else 0.0

        # Add fill info to stats for logging
        stats["fill_90_detected"] = fill_90_detected
        stats["fill_frame"] = fill_detector.fill_frame if fill_detector.fill_frame else 0
        stats["fill_percentage"] = fill_detector.get_fill_percentage()
        stats["avg_blend_40frames"] = avg_blend

        logger.write({"frame": frame_n,
                      "timestamp": datetime.now().isoformat(timespec="milliseconds"),
                      "roi_cx": cx, "roi_cy": cy, "roi_r": r,
                      **stats})

        out = draw_frame(frame, circle, heatmap, stats, frame_n, fill_detector, side_by_side=True)
        cv2.imshow(WIN, out)
        if writer:
            writer.write(out)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break
        elif key == ord('r'):
            cache.delete(cache_key)
            result = CalibrationUI(frame).run()
            if result:
                cx, cy, r = result
                cache.set(cache_key, cx, cy, r)
                circle   = (cx, cy, r)
                temporal = TemporalEngine()
                fill_detector = TankFillDetector()
                stats, heatmap = {}, None
                prev_stats, prev_heatmap = {}, None

    cap.release()
    if writer:
        writer.release()
    cv2.destroyAllWindows()
    logger.close()
    print("Done.")


if __name__ == "__main__":
    run()