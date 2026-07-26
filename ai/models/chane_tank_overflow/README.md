# Tank Monitor — README

## What It Does

Monitors a tank opening in a video feed using computer vision. It overlays a
colour heatmap inside the tank opening to visualise motion and activity, detects
anomalies, and estimates when the tank reaches 90% fill. All results are saved
to a CSV file and optionally to an output video.

---

## Quick Start

1. Open the script and set these three lines at the top:

   ```python
   VIDEO_SOURCE = r"/path/to/your/video.mp4"   # or 0 for webcam
   OUTPUT_DIR   = r"/path/to/output/folder"
   SAVE_VIDEO   = True                          # False to skip video output
   ```

2. Run it:

   ```bash
   python3 temporal_tank_monitor.py
   ```

3. A calibration window opens on the first frame. **Click the center of the
   tank opening.** The radius is detected automatically. Scroll up/down to
   adjust it. Press **Enter** or **Space** to confirm.

4. Analysis begins immediately. The result is cached so the next run on the
   same video skips calibration entirely.

---

## Controls

### Calibration window (first run only)
| Action | Effect |
|--------|--------|
| Left-click | Set tank center |
| Scroll wheel up/down | Increase / decrease radius |
| Enter or Space | Confirm and start analysis |
| ESC | Quit |

### Playback window
| Key | Effect |
|-----|--------|
| R | Recalibrate (re-opens calibration window) |
| Q or ESC | Quit |

---

## Output Files

Both files are saved to `OUTPUT_DIR` with a timestamp in the filename.

**CSV** (`tank_heatmap_YYYYMMDD_HHMMSS.csv`)  
One row per frame with these columns:

| Column | Description |
|--------|-------------|
| frame | Frame number |
| timestamp | Wall-clock time |
| roi_cx, roi_cy, roi_r | Tank circle center and radius |
| fd_mean/std/max | Frame-difference signal |
| of_mean/std/max | Optical-flow magnitude signal |
| bg_mean/std/max | Background subtraction residual |
| blend_mean/std/max | Combined heatmap signal |
| anomaly_flag | True when an anomaly is detected |
| anomaly_reason | Text description of the anomaly |
| fill_percentage | Estimated fill level (0–90%) |
| fill_90_detected | True once 90% fill is confirmed |
| fill_frame | Frame number when 90% fill was detected |
| avg_blend_40frames | Rolling average blend over last 15 frames |

***logging into csv file is for setting the threshold value so we can make this optional***

**Video** (`tank_heatmap_YYYYMMDD_HHMMSS.mp4`)  
Side-by-side: original frame on the left, heatmap overlay on the right.

**Cache** (`roi_cache.json`)  
Stores the tank circle (cx, cy, r) for each video so calibration only runs
once. Delete this file or press R to force recalibration.

---

## Display Explained

**Left panel** — original frame with:
- Coloured circle around the tank opening
- Fill level progress bar
- Signal statistics (fd / of / bg)

**Right panel** — heatmap overlay with:
- JET colour map inside the tank (blue = quiet, red = active)
- Current blend value printed in the center

**Circle colour:**
| Colour | Meaning |
|--------|---------|
| Green | Normal activity |
| Orange/Blue | Elevated activity (blend > 0.4) |
| Red | Anomaly detected |
| Cyan | 90% fill confirmed |

---

## Anomaly Detection

An anomaly is flagged when any of these conditions occur:

- Blend value jumps by more than **0.15** between consecutive processed frames
- Rolling standard deviation of blend exceeds **0.12**
- Frame-difference mean exceeds **0.6**

---

## Fill Level Detection

The fill detector watches the rolling average of `blend_mean` over the last
**15 frames**. When that average exceeds **0.120**, the tank is marked as
90% full. This threshold assumes that significant surface motion (rippling,
fluid rising) produces a measurable blend signal. Adjust `FILL_THRESHOLD` in
the config if your tank behaves differently.

---

## Configuration Reference

All settings are at the top of the script.

```python
TEMPORAL_WINDOW        = 90      # Anomaly rolling window (frames)
W_FRAMEDIFF            = 0.40    # Weight of frame-difference signal
W_OPTFLOW              = 0.35    # Weight of optical-flow signal
W_BGRESID              = 0.25    # Weight of background residual signal
HEATMAP_ALPHA          = 0.55    # Heatmap opacity (0=invisible, 1=opaque)

RAY_DIRECTIONS         = 72      # Rays cast for radius detection
RAY_EDGE_JUMP          = 25      # Brightness jump to detect rim
RAY_MIN_VALID_FRAC     = 0.40    # Minimum fraction of rays that must hit rim

FILL_WINDOW_SIZE       = 15      # Frames averaged for fill detection
FILL_THRESHOLD         = 0.120   # Blend threshold for 90% fill
PROCESS_FRAME_INTERVAL = 12      # Run detection every N frames (~2 fps)
```

---

## Requirements

```
opencv-python
numpy
```

Install with:

```bash
pip install opencv-python numpy
```

Python 3.10 or newer is required (uses `|` union type hints).

---

## Troubleshooting


**Calibration radius is wrong**  
Scroll the mouse wheel after clicking to adjust. Press R during playback to
redo calibration at any time.

**Tank not detected at all**  
Increase `RAY_EDGE_JUMP` if the rim is faint, or decrease it if the interior
is not much darker than the surroundings.

**Fill detection triggers too early / too late**  
Adjust `FILL_THRESHOLD` in the config. Check the `blend_mean` column in the
CSV to see typical values for your tank when it is empty vs. filling.
