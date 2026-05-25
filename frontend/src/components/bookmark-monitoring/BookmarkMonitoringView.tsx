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
import { getBookmarkVideoUrl } from '../../state/api/bookmarkAnalyses.api';
import type { ModelConfig } from '../../types/geofencing';

import './BookmarkMonitoringView.css';

interface BookmarkMonitoringViewProps {
  vasBookmarkId: string;
  modelId: string | null;
  modelConfig: ModelConfig | null;
}

type ActiveManager =
  | { kind: 'fall'; mgr: FallDetectionManager }
  | { kind: 'ppe'; mgr: PPEDetectionManager }
  | { kind: 'tank'; mgr: TankDetectionManager };

const FALL_FPS = 2;
const PPE_FPS = 1;
const TANK_FPS = 1;

export function BookmarkMonitoringView({
  vasBookmarkId,
  modelId,
  modelConfig,
}: BookmarkMonitoringViewProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const managerRef = useRef<ActiveManager | null>(null);

  const [fallResult, setFallResult] = useState<FallDetectionResult | null>(null);
  const [ppeResult, setPPEResult] = useState<PPEDetectionResult | null>(null);
  const [tankResult, setTankResult] = useState<TankDetectionResult | null>(null);
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
    }
  }, [fallResult, ppeResult, tankResult, modelConfig?.tank_corners, geomTick]);

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
        />
        {videoError && (
          <div className="bm-view__error" role="alert">
            {videoError}
          </div>
        )}
      </div>
      <div className="bm-view__caption">
        {modelId
          ? `Running ${modelId} on bookmark playback. Press play to start inference.`
          : 'Select a model to run inference.'}
      </div>
    </div>
  );
}
