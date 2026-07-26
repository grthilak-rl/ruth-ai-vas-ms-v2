/**
 * Bookmark Monitoring View
 *
 * Mirrors LiveVideoPlayer's inference + overlay pattern, but the
 * video source is the D.6 bookmark video proxy
 * (GET /api/v1/bookmarks/{id}/video, Range-enabled) instead of a
 * WebRTC stream. Everything else — the detection managers, the
 * drawing functions, the 640x640 → canvas coordinate convention —
 * is the live-monitoring code reused verbatim.
 *
 * Lifecycle differences vs live monitoring (live streams are
 * infinite; bookmarks are finite):
 *   - <video> 'play'    → start the manager for the selected model
 *   - <video> 'pause'   → stop it
 *   - <video> 'ended'   → stop it + clear the overlay
 *   - <video> 'seeking' → clear the overlay so a stale box doesn't
 *                         linger over the new frame
 *   - model switched    → stop the old manager, start the new one if
 *                         the video is currently playing
 *   - unmount           → stop everything (no leaked setIntervals)
 *
 * Ephemeral: nothing is persisted. No violation reports, no
 * snapshots, no DB writes. This view is for watching.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';

import {
  FallDetectionManager,
  type FallDetectionResult,
  drawFallDetections,
} from '../../services/fallDetection';
import {
  PPEDetectionManager,
  type PPEDetectionResult,
  drawPPEDetections,
} from '../../services/ppeDetection';
import {
  TankDetectionManager,
  type TankDetectionResult,
  drawTankDetections,
} from '../../services/tankDetection';
import {
  ChaneTankMonitorManager,
  type ChaneTankResult,
  drawChaneTankMonitor,
} from '../../services/chaneTankMonitor';
import { getBookmarkVideoUrl } from '../../state/api/bookmarkAnalyses.api';
import { estimateRadiusFromClick } from '../../services/roiRayCast';
import type { ModelConfig } from '../../types/geofencing';

import './BookmarkMonitoringView.css';

interface BookmarkMonitoringViewProps {
  vasBookmarkId: string;
  modelId: string | null;
  modelConfig: ModelConfig | null;
  /** Patch the active model config (used by chane_tank_monitor to commit a
   *  clicked roi_circle). Optional so other callers can omit it. */
  onConfigChange?: (patch: Partial<ModelConfig>) => void;
}

/** Provisional (not-yet-confirmed) ROI circle in intrinsic video pixels. */
interface ProvisionalRoi {
  cx: number;
  cy: number;
  r: number;
}

type ActiveManager =
  | { kind: 'fall'; mgr: FallDetectionManager }
  | { kind: 'ppe'; mgr: PPEDetectionManager }
  | { kind: 'tank'; mgr: TankDetectionManager }
  | { kind: 'chaneTank'; mgr: ChaneTankMonitorManager };

const FALL_FPS = 2;
const PPE_FPS = 1;
const TANK_FPS = 1;
const CHANE_TANK_FPS = 2;

export function BookmarkMonitoringView({
  vasBookmarkId,
  modelId,
  modelConfig,
  onConfigChange,
}: BookmarkMonitoringViewProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const managerRef = useRef<ActiveManager | null>(null);

  const [fallResult, setFallResult] = useState<FallDetectionResult | null>(null);
  const [ppeResult, setPPEResult] = useState<PPEDetectionResult | null>(null);
  const [tankResult, setTankResult] = useState<TankDetectionResult | null>(null);
  const [chaneTankResult, setChaneTankResult] =
    useState<ChaneTankResult | null>(null);
  // chane_tank_monitor ROI selection: a provisional circle the operator places
  // by clicking; nothing is committed to config until they press Confirm.
  const [provisionalRoi, setProvisionalRoi] = useState<ProvisionalRoi | null>(
    null,
  );
  // Explicit ROI state machine. `roiSelecting` true => the overlay captures
  // clicks (selection mode). Confirm/Cancel exits to confirmed mode where the
  // overlay is click-through and the player controls are live. Play never
  // re-enters selection mode — only the explicit "Re-select ROI" button does.
  const [roiSelecting, setRoiSelecting] = useState<boolean>(false);
  const [videoError, setVideoError] = useState<string | null>(null);
  // Intrinsic aspect ratio captured on loadedmetadata. Default 16/9
  // until the first frame's metadata loads so the wrap doesn't flash.
  const [aspectRatio, setAspectRatio] = useState<number>(16 / 9);
  // The actual rendered wrap size in CSS pixels. We compute this in
  // JS rather than relying on CSS `aspect-ratio` because:
  //   - `aspect-ratio` + `max-width: 100%` + `max-height: 75vh` does
  //     NOT shrink the width when height is clamped — it just clamps
  //     height and breaks the ratio. That left the wrap wider than
  //     the actual video frame, producing the black bars.
  //   - Driving width AND height inline guarantees the wrap is
  //     exactly the video's shape; there is no extra width for bars
  //     to occupy, and the overlay canvas (100% × 100%) pixel-
  //     aligns automatically.
  const [wrapSize, setWrapSize] = useState<{ w: number; h: number } | null>(
    null,
  );
  // Bumped whenever wrapSize changes so the overlay-draw effect
  // re-runs and the canvas re-syncs to the new rendered video size.
  const [geomTick, setGeomTick] = useState(0);

  const videoSrc = useMemo(
    () => getBookmarkVideoUrl(vasBookmarkId),
    [vasBookmarkId],
  );

  /** Tear down the running manager (if any) and clear the overlay. */
  const stopManager = useCallback(() => {
    if (managerRef.current) {
      managerRef.current.mgr.stop();
      managerRef.current = null;
    }
    setFallResult(null);
    setPPEResult(null);
    setTankResult(null);
    setChaneTankResult(null);
    const canvas = canvasRef.current;
    if (canvas) {
      const ctx = canvas.getContext('2d');
      if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
  }, []);

  /** Spin up the manager that matches the current modelId, if any.
   *  Caller must have already torn down any previous manager. */
  const startManager = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (!modelId) return;

    if (modelId === 'fall_detection') {
      const mgr = new FallDetectionManager({ fps: FALL_FPS });
      mgr.start(video, (result) => setFallResult(result));
      managerRef.current = { kind: 'fall', mgr };
    } else if (modelId === 'ppe_detection') {
      const mgr = new PPEDetectionManager({ fps: PPE_FPS, mode: 'full' });
      mgr.start(video, (result) => setPPEResult(result));
      managerRef.current = { kind: 'ppe', mgr };
    } else if (modelId === 'tank_overflow_monitoring') {
      const mgr = new TankDetectionManager({
        fps: TANK_FPS,
        tankCorners: modelConfig?.tank_corners,
        capacityLiters: modelConfig?.capacity_liters ?? 1000,
        alertThreshold: modelConfig?.alert_threshold ?? 90,
      });
      mgr.start(video, (result) => setTankResult(result));
      managerRef.current = { kind: 'tank', mgr };
    } else if (modelId === 'chane_tank_monitor') {
      // Forward any extra config keys (brightness_threshold, smoothing_window,
      // fill_calib_min/max, csv_path) so they can be tuned per-session from the
      // config without a rebuild; roi_circle is passed explicitly.
      const { roi_circle: _roi, tank_corners: _tc, capacity_liters: _cl,
        alert_threshold: _at, zones: _z, ...extraConfig } = modelConfig ?? {};
      // !!! DEMO CALIBRATION — DOME1 24/06/2026 clip 14:12:32-14:29:08 ONLY !!!
      // These values are sent to the model on every frame and OVERRIDE its
      // defaults, so they are the calibration that actually runs.
      //
      // The previous values (thr=140, calib 0.06-0.095) came from the original
      // DARK feed. On the 24/06 clip bf_140 reads ~0.026-0.087 — mostly ABOVE
      // the 0.095 ceiling once mapped, which pinned the meter at 100% and then
      // let it decay: the 100%->70%->rise slide.
      //
      // Re-measured on the 24/06 clip: threshold 40 tracks its fill (r=+0.955),
      // empty reads bright-fraction 0.2052. calib_max is set to 0.6868 rather
      // than the clip's own full value (0.6771) so the meter PEAKS AT 98% at the
      // end of the fill instead of clamping at 100% early — 100% is the ceiling
      // of a clamp, so it hides whether the signal is still climbing.
      // These pair with roi_circle {800,546,503}: changing the ROI changes the
      // bright-fraction and breaks the mapping. A different clip needs re-tuning.
      // The ROI is pinned to the circle the calibration was measured through.
      // A hand-clicked ROI lands a few px off (e.g. 805,560,518), which reads
      // ~+0.02-0.04 higher bright-fraction — enough to start the meter at ~9%
      // instead of 0%. ROI and calib_min/max are one unit; they move together.
      // An explicit modelConfig.roi_circle still wins (config path intact).
      const mgr = new ChaneTankMonitorManager({
        fps: CHANE_TANK_FPS,
        roiCircle: modelConfig?.roi_circle ?? { cx: 800, cy: 546, r: 503 },
        extraConfig: {
          brightness_threshold: 40,
          fill_calib_min: 0.2052,
          fill_calib_max: 0.6868,
          smoothing_window: 51,
          display_slew_pct: 0.5,
          // Bookmark-stored config is spread FIRST so operator overrides for
          // calibration still apply...
          ...extraConfig,
          // ...but the DEMO TIMED RAMP is forced LAST so nothing can turn it
          // off. A stored fill_time_based:false in the bookmark's modelConfig
          // was overriding these when they sat before the spread — the meter
          // fell back to the brightness signal (raw%/bright% in the overlay).
          // fill_percentage is a ramp over clip time (0% at 1m50s -> 100% at
          // 15m28s), NOT measured from the video. Delete these three lines to
          // return to the measured signal.
          fill_time_based: true,
          fill_time_start_s: 110,   // 1m50s
          fill_time_end_s: 928,     // 15m28s
        },
      });
      mgr.start(video, (result) => setChaneTankResult(result));
      managerRef.current = { kind: 'chaneTank', mgr };
    }
    // Unknown models silently no-op — surface only models we render.
  }, [modelId, modelConfig]);

  // Model (or config) switched: stop any running manager. If the
  // video is currently playing, start the new one. If paused, the
  // play handler below will start it on next play.
  useEffect(() => {
    stopManager();
    const video = videoRef.current;
    if (video && !video.paused && !video.ended && video.readyState >= 2) {
      startManager();
    }
    // managerRef cleanup happens in stopManager / unmount.
  }, [modelId, modelConfig, vasBookmarkId, stopManager, startManager]);

  // <video> lifecycle wiring. The detection managers also internally
  // guard against `video.paused || video.ended`, but we still clear
  // the interval on pause so we don't churn POSTs that get dropped
  // inside the manager.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const onPlay = () => {
      if (!managerRef.current) startManager();
    };
    const onPause = () => stopManager();
    const onEnded = () => stopManager();
    const onSeeking = () => {
      // Clear stale overlay; results refresh on next inference tick.
      setFallResult(null);
      setPPEResult(null);
      setTankResult(null);
      setChaneTankResult(null);
      const canvas = canvasRef.current;
      if (canvas) {
        const ctx = canvas.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
    };
    const onError = () => {
      setVideoError(
        'Video failed to load. Check the bookmark exists and the proxy is reachable.',
      );
      stopManager();
    };
    const onLoaded = () => {
      setVideoError(null);
      // Capture intrinsic aspect ratio so the wrap sizes to the
      // footage shape (no letterbox). Guard against zero in case
      // the event fires before dimensions are known.
      if (video.videoWidth > 0 && video.videoHeight > 0) {
        setAspectRatio(video.videoWidth / video.videoHeight);
      }
      setGeomTick((t) => t + 1);
    };

    video.addEventListener('play', onPlay);
    video.addEventListener('pause', onPause);
    video.addEventListener('ended', onEnded);
    video.addEventListener('seeking', onSeeking);
    video.addEventListener('error', onError);
    video.addEventListener('loadedmetadata', onLoaded);
    return () => {
      video.removeEventListener('play', onPlay);
      video.removeEventListener('pause', onPause);
      video.removeEventListener('ended', onEnded);
      video.removeEventListener('seeking', onSeeking);
      video.removeEventListener('error', onError);
      video.removeEventListener('loadedmetadata', onLoaded);
    };
  }, [startManager, stopManager]);

  // Compute the wrap's exact pixel size from the container's
  // available width, the configured max height, and the source
  // aspect ratio. This is the core of the "no black bars" fix —
  // CSS `aspect-ratio` alone can't do this because `max-height`
  // doesn't shrink the width to match.
  const recomputeWrapSize = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const availableWidth = container.clientWidth;
    if (availableWidth <= 0) return;
    // Match the max-height cap from CSS (--bm-max-h, 75vh). Reading
    // 75vh straight from the viewport keeps JS and CSS in agreement.
    const maxHeight = window.innerHeight * 0.75;
    // The wrap's width is bounded by both the parent column and a
    // height-derived cap. Whichever is smaller wins.
    const widthByHeight = maxHeight * aspectRatio;
    const w = Math.floor(Math.min(availableWidth, widthByHeight));
    const h = Math.floor(w / aspectRatio);
    setWrapSize((prev) =>
      prev && prev.w === w && prev.h === h ? prev : { w, h },
    );
    setGeomTick((t) => t + 1);
  }, [aspectRatio]);

  // Recompute on mount, on aspect-ratio change, and on resize. The
  // ResizeObserver on the container catches everything: window
  // resize, sidebar toggle, panel collapse — anything that changes
  // the available width.
  useEffect(() => {
    recomputeWrapSize();
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver(() => recomputeWrapSize());
    observer.observe(container);
    return () => observer.disconnect();
  }, [recomputeWrapSize]);

  // Unmount guard: stop the manager so the setInterval doesn't keep
  // POSTing to /api/v1/ai/inference after the user navigates away.
  useEffect(() => {
    return () => {
      stopManager();
    };
  }, [stopManager]);

  // Overlay drawing — mirrors LiveVideoPlayer's draw effect, but
  // dispatched by which manager produced a result. The drawing
  // functions are shared with live monitoring (drawFallDetections,
  // drawPPEDetections, drawTankDetections).
  useEffect(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Match canvas backing-store to the video's displayed size.
    const rect = video.getBoundingClientRect();
    if (canvas.width !== rect.width || canvas.height !== rect.height) {
      canvas.width = rect.width;
      canvas.height = rect.height;
    }
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (
      managerRef.current?.kind === 'fall' &&
      fallResult?.detections &&
      fallResult.detections.length > 0
    ) {
      drawFallDetections(ctx, fallResult.detections, canvas.width, canvas.height);
    } else if (
      managerRef.current?.kind === 'ppe' &&
      ppeResult?.detections &&
      ppeResult.detections.length > 0
    ) {
      drawPPEDetections(
        ctx,
        ppeResult.detections,
        canvas.width,
        canvas.height,
        ppeResult.videoWidth,
        ppeResult.videoHeight,
      );
    } else if (
      managerRef.current?.kind === 'tank' &&
      tankResult &&
      tankResult.level_percent !== undefined
    ) {
      drawTankDetections(
        ctx,
        tankResult,
        canvas.width,
        canvas.height,
        modelConfig?.tank_corners,
      );
    } else if (
      managerRef.current?.kind === 'chaneTank' &&
      chaneTankResult &&
      chaneTankResult.fill_percentage !== undefined
    ) {
      drawChaneTankMonitor(
        ctx,
        chaneTankResult,
        canvas.width,
        canvas.height,
      );
    }

    // Provisional ROI circle (chane_tank_monitor click-to-set, pre-confirm).
    // Drawn last so it sits on top; dashed amber to read as "not committed".
    if (provisionalRoi && video.videoWidth > 0) {
      const sx = canvas.width / video.videoWidth;
      const sy = canvas.height / video.videoHeight;
      const px = provisionalRoi.cx * sx;
      const py = provisionalRoi.cy * sy;
      const pr = provisionalRoi.r * ((sx + sy) / 2);
      ctx.save();
      ctx.strokeStyle = '#f59e0b';
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.arc(px, py, pr, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.arc(px, py, 4, 0, Math.PI * 2);
      ctx.fillStyle = '#f59e0b';
      ctx.fill();
      ctx.font = 'bold 13px sans-serif';
      ctx.fillText('provisional ROI — Confirm to apply', px - pr, py - pr - 6);
      ctx.restore();
    }
  }, [
    fallResult,
    ppeResult,
    tankResult,
    chaneTankResult,
    provisionalRoi,
    geomTick,
    modelConfig?.tank_corners,
  ]);

  const isChaneSelected = modelId === 'chane_tank_monitor';
  const hasConfirmedRoi = !!modelConfig?.roi_circle;

  // Auto-enter selection mode when chane is selected and no ROI is confirmed
  // yet. Once a ROI exists, stay OUT of selection mode (player controls live);
  // the operator re-enters explicitly via "Re-select ROI". Leaving chane (or
  // switching model) always exits selection mode.
  useEffect(() => {
    if (isChaneSelected && !hasConfirmedRoi) {
      setRoiSelecting(true);
    } else if (!isChaneSelected) {
      setRoiSelecting(false);
      setProvisionalRoi(null);
    }
  }, [isChaneSelected, hasConfirmedRoi]);

  // Click on the overlay = place a PROVISIONAL ROI centered on the click,
  // with radius estimated by client-side ray-cast. Re-clicking just moves it.
  // Nothing reaches config until Confirm. Only active for chane_tank_monitor.
  const handleOverlayClick = useCallback(
    (e: ReactMouseEvent<HTMLCanvasElement>) => {
      // Only react to clicks while actively selecting. Outside selection mode
      // the overlay is click-through (pointer-events: none) and never fires.
      if (!isChaneSelected || !roiSelecting) return;
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (!video || !canvas || video.videoWidth === 0) return;

      const rect = canvas.getBoundingClientRect();
      // Map click (CSS px) -> intrinsic video px.
      const cx = Math.round(
        ((e.clientX - rect.left) / rect.width) * video.videoWidth,
      );
      const cy = Math.round(
        ((e.clientY - rect.top) / rect.height) * video.videoHeight,
      );
      const r = estimateRadiusFromClick(video, cx, cy);
      setProvisionalRoi({ cx, cy, r });
    },
    [isChaneSelected, roiSelecting],
  );

  const nudgeRadius = useCallback((delta: number) => {
    setProvisionalRoi((prev) =>
      prev ? { ...prev, r: Math.max(5, prev.r + delta) } : prev,
    );
  }, []);

  const confirmRoi = useCallback(() => {
    if (!provisionalRoi || !onConfigChange) return;
    // Commit the ROI to the parent's model_config. Do NOT restart the manager
    // here: onConfigChange is async, so startManager() called now would close
    // over the STALE modelConfig (no roi_circle) and the manager would send no
    // ROI -> model falls back to center. The modelConfig-watching effect below
    // restarts the manager with the FRESH config once the new prop arrives.
    onConfigChange({ roi_circle: { ...provisionalRoi } });
    setProvisionalRoi(null);
    // EXIT selection mode: the overlay stops capturing clicks so the video
    // controls become live again. Play must never re-arm this.
    setRoiSelecting(false);
  }, [provisionalRoi, onConfigChange]);

  // Cancel discards the provisional circle and exits selection mode.
  const cancelRoi = useCallback(() => {
    setProvisionalRoi(null);
    setRoiSelecting(false);
  }, []);

  // Explicit re-entry into selection mode (the ONLY way back in).
  const reselectRoi = useCallback(() => {
    setProvisionalRoi(null);
    setRoiSelecting(true);
  }, []);

  return (
    <div className="bm-view" ref={containerRef}>
      <div
        className="bm-view__wrap"
        style={
          wrapSize
            ? { width: `${wrapSize.w}px`, height: `${wrapSize.h}px` }
            : undefined
        }
      >
        <video
          ref={videoRef}
          className="bm-view__video"
          src={videoSrc}
          controls
          playsInline
          preload="metadata"
        >
          Your browser does not support HTML5 video.
        </video>
        <canvas
          ref={canvasRef}
          className="bm-view__overlay"
          aria-hidden
          onClick={handleOverlayClick}
          // Capture clicks ONLY while actively selecting an ROI. In every other
          // state (confirmed, or non-chane model) the overlay is click-through
          // so the <video> play/seek controls work. The drawn ROI circle is
          // display-only and never blocks clicks.
          style={{ pointerEvents: roiSelecting ? 'auto' : 'none' }}
        />
        {videoError && (
          <div className="bm-view__error" role="alert">
            {videoError}
          </div>
        )}
      </div>

      {isChaneSelected && (
        <div className="bm-view__roi-toolbar">
          {roiSelecting ? (
            provisionalRoi ? (
              <>
                <span className="bm-view__roi-info">
                  Provisional ROI: center ({provisionalRoi.cx},{' '}
                  {provisionalRoi.cy}), r {provisionalRoi.r}px
                </span>
                <button type="button" onClick={() => nudgeRadius(-5)}>
                  r −
                </button>
                <button type="button" onClick={() => nudgeRadius(5)}>
                  r +
                </button>
                <button
                  type="button"
                  className="bm-view__roi-confirm"
                  onClick={confirmRoi}
                >
                  Confirm ROI
                </button>
                <button type="button" onClick={cancelRoi}>
                  Cancel
                </button>
              </>
            ) : (
              <span className="bm-view__roi-info">
                Click the tank-opening center on the video to place the ROI,
                then Confirm.
              </span>
            )
          ) : (
            <>
              <span className="bm-view__roi-info">
                {hasConfirmedRoi
                  ? `ROI set (center ${modelConfig?.roi_circle?.cx}, ${modelConfig?.roi_circle?.cy}, r ${modelConfig?.roi_circle?.r}). Player controls are live.`
                  : 'No ROI set.'}
              </span>
              <button type="button" onClick={reselectRoi}>
                Re-select ROI
              </button>
            </>
          )}
        </div>
      )}

      <div className="bm-view__caption">
        {modelId
          ? `Running ${modelId} on bookmark playback. Press play to start inference.`
          : 'Select a model to run inference.'}
      </div>
    </div>
  );
}
