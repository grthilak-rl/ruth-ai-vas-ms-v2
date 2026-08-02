import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { VideoErrorBoundary } from './VideoErrorBoundary';
import { connectToStream, disconnectStream, type WebRTCConnection } from '../../services/webrtc';
import { type FallDetectionResult, drawFallDetections } from '../../services/fallDetection';
import {
  type PPEDetectionResult,
  type RawUnifiedPPEResponse,
  drawPPEDetections,
  transformAPIResponse as transformPPEResponse,
} from '../../services/ppeDetection';
import { type TankDetectionResult, drawTankDetections } from '../../services/tankDetection';
import { type ChaneTankResult, drawChaneTankMonitor } from '../../services/chaneTankMonitor';
import { estimateRadiusFromClick } from '../../services/roiRayCast';
import { useCameraDetections } from '../../state/hooks/useCameraDetections';
import './LiveVideoPlayer.css';

/**
 * How many times to chase a restarted stream before surfacing an error.
 * With 1s-doubling backoff capped at 10s this spans ~1 minute, comfortably
 * longer than a normal restart (~2-5s) without spinning forever on a camera
 * that is genuinely gone.
 */
const MAX_PRODUCER_RECONNECT_ATTEMPTS = 8;

type PlayerState =
  | 'idle'
  | 'connecting'
  | 'playing'
  | 'paused'
  | 'reconnecting'
  | 'error'
  | 'offline';

interface GeofenceZone {
  id: string;
  name: string;
  points: number[][];
  type: 'restricted' | 'allowed';
}

interface LiveVideoPlayerProps {
  deviceId: string;
  deviceName: string;
  isAvailable: boolean;
  streamId?: string | null;
  isDetectionActive?: boolean;
  showOverlays?: boolean;
  isFallDetectionEnabled?: boolean;
  isPPEDetectionEnabled?: boolean;
  isTankOverflowEnabled?: boolean;
  isChaneTankEnabled?: boolean;
  isGeofencingEnabled?: boolean;
  tankCorners?: number[][];
  chaneTankRoiCircle?: { cx: number; cy: number; r: number };
  /** chane_tank_monitor: commit an operator-clicked ROI circle (intrinsic px). */
  onChaneRoiConfirm?: (roi: { cx: number; cy: number; r: number }) => void;
  geofenceZones?: GeofenceZone[];
  /**
   * When true, connect to the live stream automatically on mount /
   * when this prop flips on, instead of waiting for the user to
   * click "Play Live Video". Off by default — only the monitoring
   * grid opts in, so other callers (camera detail, fullscreen tab)
   * keep their manual-play behaviour.
   */
  shouldAutoConnect?: boolean;
  /**
   * Delay before auto-connecting, in milliseconds. Lets the
   * monitoring grid stagger N cameras so they don't all open
   * WebRTC peers in the same tick. Ignored when shouldAutoConnect
   * is false.
   */
  autoConnectDelayMs?: number;
}

export function LiveVideoPlayer({
  deviceId,
  deviceName,
  isAvailable,
  streamId: _streamId,
  isDetectionActive = true,
  showOverlays = true,
  isFallDetectionEnabled = true,
  isPPEDetectionEnabled = false,
  isTankOverflowEnabled = false,
  isChaneTankEnabled = false,
  isGeofencingEnabled = false,
  tankCorners,
  chaneTankRoiCircle,
  onChaneRoiConfirm,
  geofenceZones,
  shouldAutoConnect = false,
  autoConnectDelayMs = 0,
}: LiveVideoPlayerProps) {
  const [playerState, setPlayerState] = useState<PlayerState>(
    isAvailable ? 'idle' : 'offline'
  );
  const [connectionStatus, setConnectionStatus] = useState<string>('');

  // Detections are READ from the backend, not computed here.
  //
  // The backend inference loop already runs every active model against frames
  // tapped from VAS's decode pipeline, so a browser-side loop would be a
  // second inference of the same footage — the cost that made a 16-tile wall
  // untenable (16 JPEG encodes + 16 POSTs per second on the main thread).
  // Reading instead makes the backend the single source and leaves this
  // component doing nothing but drawing.
  //
  // The hook is keyed by device, so several tiles showing one camera share a
  // single poll.
  const { detection } = useCameraDetections(deviceId, isDetectionActive);

  // Fan the one backend result out to the per-model shapes the draw effect
  // below already expects. Only the model that actually ran has a result, so
  // at most one of these is non-null. Memoised because the draw effect
  // depends on them by reference and would otherwise re-run every render.
  const { fallDetection, ppeDetection, tankDetection, chaneTankDetection } = useMemo(() => {
    const empty = {
      fallDetection: null as FallDetectionResult | null,
      ppeDetection: null as PPEDetectionResult | null,
      tankDetection: null as TankDetectionResult | null,
      chaneTankDetection: null as ChaneTankResult | null,
    };
    if (!detection?.result) return empty;

    const raw = detection.result as Record<string, unknown>;
    const frameWidth = detection.frame_width ?? undefined;
    const frameHeight = detection.frame_height ?? undefined;

    switch (detection.model_id) {
      case 'fall_detection':
        // Boxes are in the model's 640x640 space; drawFallDetections scales
        // by MODEL_SIZE, so no coordinate work is needed. The defaults mirror
        // what the old client-side path applied before handing results on —
        // the renderer assumes `detections` is always an array.
        return {
          ...empty,
          fallDetection: {
            ...(raw as unknown as FallDetectionResult),
            detections: (raw.detections as FallDetectionResult['detections']) ?? [],
            confidence: (raw.confidence as number) ?? 0,
            videoWidth: frameWidth,
            videoHeight: frameHeight,
          },
        };
      case 'ppe_detection':
        // MUST go through the same transform the browser-side path used. The
        // runtime returns flat {item, status, bbox} rows; drawPPEDetections
        // destructures {person_bbox, ppe_items, violations, missing_ppe} off
        // each element and calls violations.length. Passing the raw response
        // through crashes the render on the first PPE result.
        //
        // Frame geometry comes from the backend's tapped frame rather than
        // this <video> element, since PPE reports in frame pixels and the two
        // are not necessarily the same size.
        return {
          ...empty,
          ppeDetection: transformPPEResponse(
            raw as unknown as RawUnifiedPPEResponse,
            'full',
            frameWidth,
            frameHeight
          ),
        };
      case 'tank_overflow_monitoring':
        return { ...empty, tankDetection: raw as unknown as TankDetectionResult };
      case 'chane_tank_monitor':
        return { ...empty, chaneTankDetection: raw as unknown as ChaneTankResult };
      default:
        return empty;
    }
  }, [detection]);
  // chane_tank_monitor click-to-set-ROI: provisional circle (intrinsic px),
  // not committed until the operator confirms.
  const [provisionalRoi, setProvisionalRoi] = useState<{ cx: number; cy: number; r: number } | null>(null);
  // Explicit ROI selection state. true => overlay captures clicks. Confirm /
  // Cancel exits; the player controls then work. Only "Re-select ROI" re-enters.
  const [roiSelecting, setRoiSelecting] = useState<boolean>(false);

  // Auto-enter ROI selection when chane is enabled with no confirmed ROI yet;
  // exit whenever chane is disabled. A confirmed ROI keeps us OUT of selection
  // (player controls live) until the operator clicks "Re-select ROI".
  useEffect(() => {
    if (isChaneTankEnabled && !!onChaneRoiConfirm && !chaneTankRoiCircle) {
      setRoiSelecting(true);
    } else if (!isChaneTankEnabled) {
      setRoiSelecting(false);
      setProvisionalRoi(null);
    }
  }, [isChaneTankEnabled, onChaneRoiConfirm, chaneTankRoiCircle]);

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const connectionRef = useRef<WebRTCConnection | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Producer-death recovery: attempt counter for backoff, and a ref to the
  // latest handleConnect so scheduleReconnect can invoke it without a
  // circular useCallback dependency.
  const reconnectAttemptsRef = useRef(0);
  const handleConnectRef = useRef<(() => Promise<void>) | null>(null);
  const streamIdRef = useRef<string | null>(null);  // Use ref for immediate access in callbacks

  // Violation reporting deliberately removed: the backend inference loop
  // already creates violation records for every active session. Reporting
  // from here as well produced duplicate rows for the same event, and did
  // so once per open browser view.

  // Draw detections on canvas whenever fallDetection, ppeDetection, or tankDetection updates
  useEffect(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;

    const hasFallDetection = fallDetection && isFallDetectionEnabled;
    const hasPPEDetection = ppeDetection && isPPEDetectionEnabled;
    const hasTankDetection = tankDetection && isTankOverflowEnabled && tankDetection.level_percent !== undefined;
    const hasChaneTankDetection = chaneTankDetection && isChaneTankEnabled && chaneTankDetection.fill_percentage !== undefined;
    const hasGeofenceZones = isGeofencingEnabled && geofenceZones && geofenceZones.length > 0;

    // Debug logging
    if (tankDetection) {
      console.log('[LiveVideoPlayer] Tank Draw check:', {
        hasTankDetection,
        isTankOverflowEnabled,
        showOverlays,
        isDetectionActive,
        level_percent: tankDetection.level_percent,
        canvasExists: !!canvas,
        videoExists: !!video,
      });
    }

    // The provisional ROI must render even before any inference result and
    // regardless of showOverlays/isDetectionActive, so the operator can place
    // it while paused. It's handled as a separate concern below.
    const onlyProvisional = !!provisionalRoi && video?.videoWidth ? true : false;

    if (!canvas || !video || ((!hasFallDetection && !hasPPEDetection && !hasTankDetection && !hasChaneTankDetection && !hasGeofenceZones) && !onlyProvisional) || (!onlyProvisional && (!showOverlays || !isDetectionActive))) {
      // Clear canvas if detection is disabled
      if (canvas) {
        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
      }
      return;
    }

    // Update canvas size to match video display size
    const rect = video.getBoundingClientRect();
    if (canvas.width !== rect.width || canvas.height !== rect.height) {
      canvas.width = rect.width;
      canvas.height = rect.height;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear previous drawings
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Draw fall detections if enabled and available
    if (hasFallDetection && fallDetection.detections && fallDetection.detections.length > 0) {
      drawFallDetections(
        ctx,
        fallDetection.detections,
        canvas.width,
        canvas.height,
      );
    }

    // Draw PPE detections if enabled and available
    if (hasPPEDetection && ppeDetection.detections && ppeDetection.detections.length > 0) {
      drawPPEDetections(
        ctx,
        ppeDetection.detections,
        canvas.width,
        canvas.height,
        ppeDetection.videoWidth,
        ppeDetection.videoHeight
      );
    }

    // Draw tank overflow detection if enabled and available
    // Note: Tank detection may have empty detections array but still have level data
    if (hasTankDetection) {
      console.log('[LiveVideoPlayer] Drawing tank detection overlay:', {
        level_percent: tankDetection!.level_percent,
        severity: tankDetection!.severity,
        canvasSize: `${canvas.width}x${canvas.height}`,
      });
      drawTankDetections(
        ctx,
        tankDetection!,
        canvas.width,
        canvas.height,
        tankCorners
      );
    }

    // Draw chane tank monitor overlay if enabled and available
    if (hasChaneTankDetection) {
      drawChaneTankMonitor(
        ctx,
        chaneTankDetection!,
        canvas.width,
        canvas.height,
      );
    }

    // Provisional ROI circle (chane_tank_monitor click-to-set, pre-confirm).
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

    // Draw geofence zones if enabled and available
    if (hasGeofenceZones) {
      // Draw each zone as a semi-transparent polygon
      for (const zone of geofenceZones!) {
        if (!zone.points || zone.points.length < 3) continue;

        // Zone points are stored as [x, y] in pixel coordinates (1920x1080 video space)
        // Scale to canvas size
        const videoWidth = video.videoWidth || 1920;
        const videoHeight = video.videoHeight || 1080;
        const scaledPoints = zone.points.map((point) => ({
          x: (point[0] / videoWidth) * canvas.width,
          y: (point[1] / videoHeight) * canvas.height,
        }));

        ctx.save();

        // Draw filled zone
        ctx.beginPath();
        ctx.moveTo(scaledPoints[0].x, scaledPoints[0].y);
        for (let i = 1; i < scaledPoints.length; i++) {
          ctx.lineTo(scaledPoints[i].x, scaledPoints[i].y);
        }
        ctx.closePath();

        // Color based on zone type
        if (zone.type === 'restricted') {
          ctx.fillStyle = 'rgba(255, 0, 0, 0.15)'; // Semi-transparent red for restricted
          ctx.strokeStyle = 'rgba(255, 0, 0, 0.8)';
        } else {
          ctx.fillStyle = 'rgba(0, 255, 0, 0.15)'; // Semi-transparent green for allowed
          ctx.strokeStyle = 'rgba(0, 255, 0, 0.8)';
        }
        ctx.fill();

        // Draw border
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 5]); // Dashed line
        ctx.stroke();

        // Draw zone label
        ctx.setLineDash([]); // Reset line dash
        ctx.font = 'bold 14px Arial';
        ctx.fillStyle = zone.type === 'restricted' ? 'rgba(255, 0, 0, 0.9)' : 'rgba(0, 255, 0, 0.9)';

        // Position label at top-left of zone
        const labelX = Math.min(...scaledPoints.map(p => p.x)) + 5;
        const labelY = Math.min(...scaledPoints.map(p => p.y)) + 18;

        // Draw label background
        const labelText = zone.name || (zone.type === 'restricted' ? 'Restricted Zone' : 'Allowed Zone');
        const textMetrics = ctx.measureText(labelText);
        ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
        ctx.fillRect(labelX - 3, labelY - 14, textMetrics.width + 6, 18);

        // Draw label text
        ctx.fillStyle = zone.type === 'restricted' ? '#ff6666' : '#66ff66';
        ctx.fillText(labelText, labelX, labelY);

        ctx.restore();
      }
    }
  }, [fallDetection, ppeDetection, tankDetection, chaneTankDetection, provisionalRoi, showOverlays, isDetectionActive, isFallDetectionEnabled, isPPEDetectionEnabled, isTankOverflowEnabled, isChaneTankEnabled, isGeofencingEnabled, tankCorners, geofenceZones]);

  // Cleanup function
  const cleanup = useCallback(async () => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (connectionRef.current) {
      await disconnectStream(connectionRef.current);
      connectionRef.current = null;
    }

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    streamIdRef.current = null;
  }, []);

  // Handle WebRTC connection
  /**
   * Re-establish the stream after its producer died.
   *
   * A stream restart (disable/enable, Streams-page Stop+Start, ffmpeg
   * auto-heal, camera reconnect) mints a NEW mediasoup producer id. Our
   * consumer is bound to the old one and is now dead, but the transport stays
   * healthy — so without this the video silently holds its last frame until
   * the user refreshes or unselects/reselects the camera.
   *
   * Reconnecting is exactly what a remount does: tear down, then
   * connectToStream, whose start-stream call returns the current producer.
   * Backoff because the new producer may not be live the instant the old one
   * closes. Goes through a ref so this doesn't have to depend on
   * handleConnect, which would be circular.
   */
  const scheduleReconnect = useCallback((reason: string) => {
    if (reconnectTimeoutRef.current) {
      return; // one reconnect in flight is enough
    }

    const attempt = reconnectAttemptsRef.current + 1;
    reconnectAttemptsRef.current = attempt;

    if (attempt > MAX_PRODUCER_RECONNECT_ATTEMPTS) {
      console.error(`[LiveVideoPlayer] Giving up reconnect for ${deviceId} after ${attempt - 1} attempts`);
      setPlayerState('error');
      setConnectionStatus('Stream unavailable');
      return;
    }

    const delay = Math.min(1000 * 2 ** (attempt - 1), 10000);
    console.log(`[LiveVideoPlayer] ${reason} on ${deviceId} — reconnecting in ${delay}ms (attempt ${attempt})`);
    setPlayerState('reconnecting');
    setConnectionStatus('Stream restarted — reconnecting...');

    reconnectTimeoutRef.current = setTimeout(async () => {
      reconnectTimeoutRef.current = null;
      await cleanup();
      await handleConnectRef.current?.();
    }, delay);
  }, [deviceId, cleanup]);

  const handleConnect = useCallback(async () => {
    console.log('[LiveVideoPlayer] Starting WebRTC connection for device:', deviceId);
    setPlayerState('connecting');
    setConnectionStatus('Starting stream...');

    try {
      const connection = await connectToStream(
        deviceId,
        (state) => {
          console.log('[LiveVideoPlayer] Connection state:', state);
          setConnectionStatus(state);
          if (state === 'connected') {
            setPlayerState('playing');
          }
        },
        scheduleReconnect
      );

      // Reached a live producer, so the previous failure streak is over.
      reconnectAttemptsRef.current = 0;

      connectionRef.current = connection;
      streamIdRef.current = connection.streamId;  // Store in ref for immediate access in callbacks

      const video = videoRef.current;
      if (video) {
        video.srcObject = connection.mediaStream;
        await video.play();
        setPlayerState('playing');
        console.log('[LiveVideoPlayer] WebRTC stream playing');

        // No client-side inference here any more: the backend inference
        // loop is the single detection source and this component only
        // draws what useCameraDetections reads back.
      } else {
        console.error('[LiveVideoPlayer] Video element not found');
        setPlayerState('error');
        setConnectionStatus('Video element not available');
      }
    } catch (error) {
      console.error('[LiveVideoPlayer] WebRTC connection failed:', error);
      setPlayerState('error');
      setConnectionStatus('Connection failed');
    }
    // Connecting no longer depends on which models are enabled — that is the
    // backend's business now — so the model flags are out of the deps and a
    // toggle no longer tears down and rebuilds the WebRTC connection.
  }, [deviceId, scheduleReconnect]);

  // Keep the ref pointing at the current handleConnect so scheduleReconnect
  // can call it without taking a dependency on it.
  useEffect(() => {
    handleConnectRef.current = handleConnect;
  }, [handleConnect]);

  // Handle retry
  const handleRetry = useCallback(async () => {
    reconnectAttemptsRef.current = 0;
    await cleanup();
    handleConnect();
  }, [cleanup, handleConnect]);

  // Handle pause
  const handlePause = useCallback(() => {
    const video = videoRef.current;
    if (video) {
      video.pause();
      setPlayerState('paused');
    }
  }, []);

  // Handle resume
  const handleResume = useCallback(async () => {
    const video = videoRef.current;
    if (video) {
      try {
        await video.play();
        setPlayerState('playing');
      } catch (error) {
        console.warn('[LiveVideoPlayer] Resume failed:', error);
      }
    }
  }, []);

  // Handle availability changes
  useEffect(() => {
    if (!isAvailable) {
      cleanup();
      setPlayerState('offline');
    } else if (playerState === 'offline') {
      setPlayerState('idle');
    }
  }, [isAvailable, playerState, cleanup]);

  // The start/stop-managers-on-toggle effect is gone with them. Enabling or
  // disabling a model is now purely a backend concern: the inference loop
  // starts or stops that camera's session, and this component simply stops
  // receiving results for it.

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanup();
    };
  }, [cleanup]);

  // Auto-connect on mount / when caller flips shouldAutoConnect on.
  // Mirrors what a user clicking "Play Live Video" would do, but only
  // when the consumer opts in (the monitoring grid does; detail and
  // fullscreen don't). Strictly gated on playerState === 'idle' so
  // this can't double-fire while already connecting/playing/reconnecting.
  useEffect(() => {
    if (!shouldAutoConnect) return;
    if (!isAvailable) return;
    if (playerState !== 'idle') return;

    if (autoConnectDelayMs <= 0) {
      handleConnect();
      return;
    }

    const timeoutId = setTimeout(() => {
      handleConnect();
    }, autoConnectDelayMs);

    return () => {
      clearTimeout(timeoutId);
    };
  }, [shouldAutoConnect, autoConnectDelayMs, isAvailable, playerState, handleConnect]);

  // Render offline state
  if (playerState === 'offline' || !isAvailable) {
    return (
      <div className="live-video-player live-video-player--offline">
        <div className="live-video-player__offline-content">
          <span className="live-video-player__offline-icon" aria-hidden="true">
            &#9679;
          </span>
          <p className="live-video-player__offline-title">Camera Offline</p>
          <p className="live-video-player__offline-message">
            {deviceName} is not streaming. Video will resume when the camera reconnects.
          </p>
        </div>
      </div>
    );
  }

  // Render error state
  if (playerState === 'error') {
    return (
      <div className="live-video-player live-video-player--error">
        <div className="live-video-player__error-content">
          <p className="live-video-player__error-title">
            Video temporarily unavailable
          </p>
          <p className="live-video-player__error-message">
            Unable to connect to live video. The camera may be reconnecting.
          </p>
          <button
            type="button"
            className="live-video-player__retry-button"
            onClick={handleRetry}
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  // chane_tank_monitor click-to-set-ROI handlers (live view).
  const roiSelectable = isChaneTankEnabled && !!onChaneRoiConfirm;
  const handleRoiClick = (e: ReactMouseEvent<HTMLCanvasElement>) => {
    // Only react while actively selecting; outside selection the overlay is
    // click-through (pointer-events: none) and this never fires.
    if (!roiSelectable || !roiSelecting) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || video.videoWidth === 0) return;
    const rect = canvas.getBoundingClientRect();
    const cx = Math.round(((e.clientX - rect.left) / rect.width) * video.videoWidth);
    const cy = Math.round(((e.clientY - rect.top) / rect.height) * video.videoHeight);
    const r = estimateRadiusFromClick(video, cx, cy);
    setProvisionalRoi({ cx, cy, r });
  };
  const nudgeRoiRadius = (delta: number) =>
    setProvisionalRoi((prev) => (prev ? { ...prev, r: Math.max(5, prev.r + delta) } : prev));
  const confirmRoiLive = () => {
    if (provisionalRoi && onChaneRoiConfirm) onChaneRoiConfirm({ ...provisionalRoi });
    setProvisionalRoi(null);
    // EXIT selection mode so the player controls become live again.
    setRoiSelecting(false);
  };
  const cancelRoiLive = () => {
    setProvisionalRoi(null);
    setRoiSelecting(false);
  };
  const reselectRoiLive = () => {
    setProvisionalRoi(null);
    setRoiSelecting(true);
  };

  return (
    <VideoErrorBoundary deviceName={deviceName}>
      <div className={`live-video-player live-video-player--${playerState}`}>
        {/* Video element */}
        <video
          ref={videoRef}
          className="live-video-player__video"
          playsInline
          muted
          autoPlay
        />

        {/* Canvas overlay for bounding boxes and skeletons (from POC) */}
        <canvas
          ref={canvasRef}
          className="live-video-player__detection-canvas"
          onClick={handleRoiClick}
          // Capture clicks only while picking an ROI for chane_tank_monitor.
          style={{ pointerEvents: roiSelecting ? 'auto' : 'none' }}
        />

        {/* chane_tank_monitor ROI toolbar (live view) */}
        {roiSelectable && (
          <div className="live-video-player__roi-toolbar">
            {roiSelecting ? (
              provisionalRoi ? (
                <>
                  <span>
                    ROI ({provisionalRoi.cx}, {provisionalRoi.cy}) r {provisionalRoi.r}
                  </span>
                  <button type="button" onClick={() => nudgeRoiRadius(-5)}>r −</button>
                  <button type="button" onClick={() => nudgeRoiRadius(5)}>r +</button>
                  <button type="button" onClick={confirmRoiLive}>Confirm ROI</button>
                  <button type="button" onClick={cancelRoiLive}>Cancel</button>
                </>
              ) : (
                <span>Click the tank-opening center, then Confirm.</span>
              )
            ) : (
              <>
                <span>{chaneTankRoiCircle ? 'ROI set — controls live' : 'No ROI set'}</span>
                <button type="button" onClick={reselectRoiLive}>Re-select ROI</button>
              </>
            )}
          </div>
        )}

        {/* Idle state overlay */}
        {playerState === 'idle' && (
          <div className="live-video-player__idle-overlay">
            <button
              type="button"
              className="live-video-player__play-button"
              onClick={handleConnect}
              aria-label={`Play live video from ${deviceName}`}
            >
              <span className="live-video-player__play-icon" aria-hidden="true">
                ▶
              </span>
              <span className="live-video-player__play-text">Play Live Video</span>
            </button>
          </div>
        )}

        {/* Live indicator */}
        {playerState === 'playing' && (
          <div className="live-video-player__live-badge">
            <span className="live-video-player__live-dot" />
            LIVE
          </div>
        )}

        {/* Connecting overlay */}
        {(playerState === 'connecting' || playerState === 'reconnecting') && (
          <div className="live-video-player__loading-overlay">
            <div className="live-video-player__spinner" />
            <p className="live-video-player__loading-text">
              {connectionStatus || 'Connecting...'}
            </p>
          </div>
        )}

        {/* Video controls */}
        {playerState === 'playing' && (
          <div className="live-video-player__controls">
            <button
              type="button"
              className="live-video-player__control-button"
              onClick={handlePause}
              aria-label="Pause video"
            >
              ❚❚
            </button>
          </div>
        )}

        {playerState === 'paused' && (
          <div className="live-video-player__paused-overlay">
            <button
              type="button"
              className="live-video-player__resume-button"
              onClick={handleResume}
              aria-label="Resume video"
            >
              <span className="live-video-player__resume-icon">▶</span>
            </button>
          </div>
        )}
      </div>
    </VideoErrorBoundary>
  );
}
