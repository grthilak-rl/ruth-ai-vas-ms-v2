import { useState, useRef, useCallback, useEffect } from 'react';
import { VideoErrorBoundary } from './VideoErrorBoundary';
import { connectToStream, disconnectStream, type WebRTCConnection } from '../../services/webrtc';
import { FallDetectionManager, type FallDetectionResult, type Detection, SKELETON_CONNECTIONS } from '../../services/fallDetection';
import { reportFallEvent, type BoundingBox } from '../../services/api';
import './LiveVideoPlayer.css';

// Model outputs coordinates in 640x640 space (matching POC)
const MODEL_SIZE = 640;

type PlayerState =
  | 'idle'
  | 'connecting'
  | 'playing'
  | 'paused'
  | 'reconnecting'
  | 'error'
  | 'offline';

interface LiveVideoPlayerProps {
  deviceId: string;
  deviceName: string;
  isAvailable: boolean;
  streamId?: string | null;
  isDetectionActive?: boolean;
  showOverlays?: boolean;
}

/**
 * Check if a detection represents a fallen person based on pose
 * Uses keypoint positions to determine if person is horizontal/fallen
 */
function isPersonFallen(detection: Detection): boolean {
  if (!detection.keypoints || detection.keypoints.length < 17) {
    return false;
  }

  const keypoints = detection.keypoints;

  // Get key body points (COCO format)
  const leftShoulder = keypoints[5];
  const rightShoulder = keypoints[6];
  const leftHip = keypoints[11];
  const rightHip = keypoints[12];
  const leftAnkle = keypoints[15];
  const rightAnkle = keypoints[16];

  // Calculate average positions
  const shoulderY = (leftShoulder.confidence > 0.3 && rightShoulder.confidence > 0.3)
    ? (leftShoulder.y + rightShoulder.y) / 2
    : null;
  const hipY = (leftHip.confidence > 0.3 && rightHip.confidence > 0.3)
    ? (leftHip.y + rightHip.y) / 2
    : null;
  const ankleY = (leftAnkle.confidence > 0.3 && rightAnkle.confidence > 0.3)
    ? (leftAnkle.y + rightAnkle.y) / 2
    : null;

  // If we have shoulder and hip, check if person is roughly horizontal
  if (shoulderY !== null && hipY !== null) {
    const verticalDiff = Math.abs(shoulderY - hipY);
    // If shoulders and hips are at similar Y level (horizontal), person may be fallen
    // Normal standing: hip Y > shoulder Y by significant amount
    // Fallen: hip Y ≈ shoulder Y (person is horizontal)
    if (verticalDiff < 50) { // Threshold for "approximately same level"
      return true;
    }
  }

  // Alternative check: if ankles are at same level as hips/shoulders
  if (ankleY !== null && hipY !== null) {
    const ankleHipDiff = Math.abs(ankleY - hipY);
    if (ankleHipDiff < 80) { // Person lying down
      return true;
    }
  }

  return false;
}

/**
 * Draw detection overlays (bounding boxes and skeletons) on canvas
 * Each detection is colored based on its own fall state
 */
function drawDetections(
  ctx: CanvasRenderingContext2D,
  detections: Detection[],
  canvasWidth: number,
  canvasHeight: number,
  _globalFallDetected: boolean // Kept for API compat, but we check per-detection
): void {
  // Scale factors from model coordinates (640x640) to canvas size
  const scaleX = canvasWidth / MODEL_SIZE;
  const scaleY = canvasHeight / MODEL_SIZE;

  detections.forEach((detection, idx) => {
    const [x1, y1, x2, y2] = detection.bbox;

    // Check if THIS specific person is fallen
    const isFallen = isPersonFallen(detection);

    // Scale bounding box coordinates
    const sx1 = x1 * scaleX;
    const sy1 = y1 * scaleY;
    const sx2 = x2 * scaleX;
    const sy2 = y2 * scaleY;

    // Draw bounding box - color based on individual detection state
    ctx.strokeStyle = isFallen ? '#ef4444' : '#22c55e';
    ctx.lineWidth = 3;
    ctx.strokeRect(sx1, sy1, sx2 - sx1, sy2 - sy1);

    // Draw label background
    const label = isFallen ? `Person ${idx + 1} - FALL` : `Person ${idx + 1}`;
    ctx.font = 'bold 14px sans-serif';
    const textWidth = ctx.measureText(label).width;
    ctx.fillStyle = isFallen ? '#ef4444' : '#22c55e';
    ctx.fillRect(sx1, sy1 - 22, textWidth + 10, 22);

    // Draw label text
    ctx.fillStyle = '#ffffff';
    ctx.fillText(label, sx1 + 5, sy1 - 6);

    // Draw skeleton if keypoints exist
    if (detection.keypoints && detection.keypoints.length >= 17) {
      const keypoints = detection.keypoints;

      // Draw skeleton connections
      ctx.strokeStyle = isFallen ? '#fca5a5' : '#86efac';
      ctx.lineWidth = 2;

      SKELETON_CONNECTIONS.forEach(([i, j]) => {
        const kp1 = keypoints[i];
        const kp2 = keypoints[j];

        // Only draw if both keypoints have sufficient confidence
        if (kp1.confidence > 0.3 && kp2.confidence > 0.3) {
          ctx.beginPath();
          ctx.moveTo(kp1.x * scaleX, kp1.y * scaleY);
          ctx.lineTo(kp2.x * scaleX, kp2.y * scaleY);
          ctx.stroke();
        }
      });

      // Draw keypoints
      keypoints.forEach((kp) => {
        if (kp.confidence > 0.3) {
          ctx.beginPath();
          ctx.arc(kp.x * scaleX, kp.y * scaleY, 4, 0, 2 * Math.PI);
          ctx.fillStyle = isFallen ? '#ef4444' : '#22c55e';
          ctx.fill();
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      });
    }
  });
}

export function LiveVideoPlayer({
  deviceId,
  deviceName,
  isAvailable,
  streamId: _streamId,
  isDetectionActive = true,
  showOverlays = true,
}: LiveVideoPlayerProps) {
  const [playerState, setPlayerState] = useState<PlayerState>(
    isAvailable ? 'idle' : 'offline'
  );
  const [connectionStatus, setConnectionStatus] = useState<string>('');
  const [fallDetection, setFallDetection] = useState<FallDetectionResult | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const connectionRef = useRef<WebRTCConnection | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fallDetectionRef = useRef<FallDetectionManager | null>(null);
  const lastFallReportTimeRef = useRef<number>(0);
  const streamIdRef = useRef<string | null>(null);  // Use ref for immediate access in callbacks

  // Debounce interval for fall reporting (30 seconds between reports for same device)
  const FALL_REPORT_DEBOUNCE_MS = 30000;

  /**
   * Report a fall detection to the backend (with debouncing)
   * Only reports if enough time has passed since the last report
   * Now includes VAS stream ID for snapshot capture
   */
  const reportFallToBackend = useCallback(async (
    detections: Detection[],
    confidence: number
  ) => {
    const now = Date.now();

    // Check debounce - don't report if we recently reported a fall
    if (now - lastFallReportTimeRef.current < FALL_REPORT_DEBOUNCE_MS) {
      console.log('[LiveVideoPlayer] Skipping fall report - debounced');
      return;
    }

    // Convert detections to bounding boxes for the API
    const boundingBoxes: BoundingBox[] = detections
      .filter(d => isPersonFallen(d))
      .map(d => {
        const [x1, y1, x2, y2] = d.bbox;
        return {
          x: Math.round(x1),
          y: Math.round(y1),
          w: Math.round(x2 - x1),
          h: Math.round(y2 - y1),
        };
      });

    if (boundingBoxes.length === 0) {
      return;
    }

    try {
      // Use ref for immediate access to latest stream ID (state may be stale in callback)
      const streamId = streamIdRef.current;
      console.log('[LiveVideoPlayer] Reporting fall to backend for device:', deviceId, 'stream:', streamId);
      const response = await reportFallEvent(
        deviceId,
        confidence,
        boundingBoxes,
        streamId || undefined  // Pass stream ID for snapshot capture
      );
      lastFallReportTimeRef.current = now;
      console.log('[LiveVideoPlayer] Fall reported successfully:', response);

      if (response.violation_id) {
        console.log('[LiveVideoPlayer] Violation created:', response.violation_id);
      }
    } catch (error) {
      console.error('[LiveVideoPlayer] Failed to report fall:', error);
    }
  }, [deviceId]);  // Use ref for streamId, so no dependency needed

  // Draw detections on canvas whenever fallDetection updates (from POC)
  useEffect(() => {
    console.log('[LiveVideoPlayer] Draw effect triggered, fallDetection:', fallDetection ? 'present' : 'null');
    const canvas = canvasRef.current;
    const video = videoRef.current;

    if (!canvas || !video || !fallDetection || !showOverlays || !isDetectionActive) {
      console.log('[LiveVideoPlayer] Early return - canvas:', !!canvas, 'video:', !!video, 'fallDetection:', !!fallDetection, 'showOverlays:', showOverlays, 'isDetectionActive:', isDetectionActive);
      // Clear canvas if detection is disabled
      if (canvas) {
        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
      }
      return;
    }

    // Update canvas size to match video display size (from POC)
    const rect = video.getBoundingClientRect();
    console.log('[LiveVideoPlayer] Video rect:', rect.width, 'x', rect.height);
    console.log('[LiveVideoPlayer] Video native:', video.videoWidth, 'x', video.videoHeight);
    console.log('[LiveVideoPlayer] Canvas before:', canvas.width, 'x', canvas.height);
    if (canvas.width !== rect.width || canvas.height !== rect.height) {
      canvas.width = rect.width;
      canvas.height = rect.height;
      console.log('[LiveVideoPlayer] Canvas after:', canvas.width, 'x', canvas.height);
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear previous drawings
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Draw new detections
    if (fallDetection.detections && fallDetection.detections.length > 0) {
      console.log('[LiveVideoPlayer] Drawing detections:', fallDetection.detections.length);
      console.log('[LiveVideoPlayer] First detection bbox:', fallDetection.detections[0].bbox);
      console.log('[LiveVideoPlayer] Canvas size for drawing:', canvas.width, 'x', canvas.height);
      drawDetections(
        ctx,
        fallDetection.detections,
        canvas.width,
        canvas.height,
        fallDetection.violation_detected
      );
    }
  }, [fallDetection, showOverlays, isDetectionActive]);

  // Cleanup function
  const cleanup = useCallback(async () => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (fallDetectionRef.current) {
      fallDetectionRef.current.stop();
      fallDetectionRef.current = null;
    }

    if (connectionRef.current) {
      await disconnectStream(connectionRef.current);
      connectionRef.current = null;
    }

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    setFallDetection(null);
    streamIdRef.current = null;
  }, []);

  // Handle WebRTC connection
  const handleConnect = useCallback(async () => {
    console.log('[LiveVideoPlayer] Starting WebRTC connection for device:', deviceId);
    setPlayerState('connecting');
    setConnectionStatus('Starting stream...');

    try {
      const connection = await connectToStream(deviceId, (state) => {
        console.log('[LiveVideoPlayer] Connection state:', state);
        setConnectionStatus(state);
        if (state === 'connected') {
          setPlayerState('playing');
        }
      });

      connectionRef.current = connection;
      streamIdRef.current = connection.streamId;  // Store in ref for immediate access in callbacks

      const video = videoRef.current;
      if (video) {
        video.srcObject = connection.mediaStream;
        await video.play();
        setPlayerState('playing');
        console.log('[LiveVideoPlayer] WebRTC stream playing');

        // Start fall detection after video is playing (from POC)
        if (isDetectionActive) {
          // Previous: fps: 5 (200ms) caused 30s delay due to slow CPU inference
          fallDetectionRef.current = new FallDetectionManager({ fps: 2 });  // 500ms interval
          fallDetectionRef.current.start(video, (result) => {
            console.log('[LiveVideoPlayer] Got detection result:', result.detections?.length || 0, 'detections');
            setFallDetection(result);

            // Check if any person in the frame is fallen (using our per-detection logic)
            const fallenDetections = result.detections?.filter(d => isPersonFallen(d)) || [];
            if (fallenDetections.length > 0) {
              console.log('[LiveVideoPlayer] Fall detected!', fallenDetections.length, 'person(s) fallen');
              // Report to backend (with debouncing)
              reportFallToBackend(result.detections || [], result.confidence);
            }
          });
          console.log('[LiveVideoPlayer] Fall detection started');
        }
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
  }, [deviceId, isDetectionActive, reportFallToBackend]);

  // Handle retry
  const handleRetry = useCallback(async () => {
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

  // Handle isDetectionActive changes while stream is playing
  useEffect(() => {
    const video = videoRef.current;

    if (playerState !== 'playing' || !video) {
      return;
    }

    if (isDetectionActive && !fallDetectionRef.current) {
      // Start detection if enabled and not already running
      console.log('[LiveVideoPlayer] Starting fall detection (enabled while playing)');
      fallDetectionRef.current = new FallDetectionManager({ fps: 2 });
      fallDetectionRef.current.start(video, (result) => {
        console.log('[LiveVideoPlayer] Got detection result:', result.detections?.length || 0, 'detections');
        setFallDetection(result);

        const fallenDetections = result.detections?.filter(d => isPersonFallen(d)) || [];
        if (fallenDetections.length > 0) {
          console.log('[LiveVideoPlayer] Fall detected!', fallenDetections.length, 'person(s) fallen');
          reportFallToBackend(result.detections || [], result.confidence);
        }
      });
    } else if (!isDetectionActive && fallDetectionRef.current) {
      // Stop detection if disabled
      console.log('[LiveVideoPlayer] Stopping fall detection (disabled while playing)');
      fallDetectionRef.current.stop();
      fallDetectionRef.current = null;
      setFallDetection(null);
    }
  }, [isDetectionActive, playerState, reportFallToBackend]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanup();
    };
  }, [cleanup]);

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
        />

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
