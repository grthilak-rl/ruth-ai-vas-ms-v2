import { useEffect, useRef, useState, useCallback } from 'react';
import type { Device } from '../types';
import { connectToStream, disconnectStream } from '../services/webrtc';
import type { WebRTCConnection } from '../services/webrtc';
import {
  FallDetectionManager,
  type FallDetectionResult,
  type Detection,
  SKELETON_CONNECTIONS,
} from '../services/fallDetection';
import './VideoPlayer.css';

// Model outputs coordinates in 640x640 space
const MODEL_SIZE = 640;

interface VideoPlayerProps {
  device: Device | null;
}

/**
 * Draw detection overlays (bounding boxes and skeletons) on canvas
 */
function drawDetections(
  ctx: CanvasRenderingContext2D,
  detections: Detection[],
  canvasWidth: number,
  canvasHeight: number,
  isFallDetected: boolean
): void {
  // Scale factors from model coordinates (640x640) to canvas size
  const scaleX = canvasWidth / MODEL_SIZE;
  const scaleY = canvasHeight / MODEL_SIZE;

  detections.forEach((detection, idx) => {
    const [x1, y1, x2, y2] = detection.bbox;

    // Scale bounding box coordinates
    const sx1 = x1 * scaleX;
    const sy1 = y1 * scaleY;
    const sx2 = x2 * scaleX;
    const sy2 = y2 * scaleY;

    // Draw bounding box
    ctx.strokeStyle = isFallDetected ? '#ef4444' : '#22c55e';
    ctx.lineWidth = 3;
    ctx.strokeRect(sx1, sy1, sx2 - sx1, sy2 - sy1);

    // Draw label background
    const label = `Person ${idx + 1} (${(detection.confidence * 100).toFixed(0)}%)`;
    ctx.font = 'bold 14px sans-serif';
    const textWidth = ctx.measureText(label).width;
    ctx.fillStyle = isFallDetected ? '#ef4444' : '#22c55e';
    ctx.fillRect(sx1, sy1 - 22, textWidth + 10, 22);

    // Draw label text
    ctx.fillStyle = '#ffffff';
    ctx.fillText(label, sx1 + 5, sy1 - 6);

    // Draw skeleton if keypoints exist
    if (detection.keypoints && detection.keypoints.length >= 17) {
      const keypoints = detection.keypoints;

      // Draw skeleton connections
      ctx.strokeStyle = isFallDetected ? '#fca5a5' : '#86efac';
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
          ctx.fillStyle = isFallDetected ? '#ef4444' : '#22c55e';
          ctx.fill();
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      });
    }
  });
}

export function VideoPlayer({ device }: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const connectionRef = useRef<WebRTCConnection | null>(null);
  const fallDetectionRef = useRef<FallDetectionManager | null>(null);
  const [connectionState, setConnectionState] = useState<string>('idle');
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const [fallDetection, setFallDetection] = useState<FallDetectionResult | null>(null);
  const [detectionEnabled, setDetectionEnabled] = useState(true);

  // Draw detections on canvas whenever fallDetection updates
  useEffect(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;

    if (!canvas || !video || !fallDetection || !detectionEnabled) {
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

    // Draw new detections
    if (fallDetection.detections && fallDetection.detections.length > 0) {
      drawDetections(
        ctx,
        fallDetection.detections,
        canvas.width,
        canvas.height,
        fallDetection.violation_detected
      );
    }
  }, [fallDetection, detectionEnabled]);

  // Cleanup function to disconnect current stream
  const cleanup = useCallback(async () => {
    // Stop fall detection
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
    setConnectionState('idle');
    setError(null);
    setFallDetection(null);
  }, []);

  // Connect to stream when device changes
  useEffect(() => {
    if (!device) {
      cleanup();
      return;
    }

    let isMounted = true;

    async function connect() {
      // First cleanup any existing connection
      await cleanup();

      if (!isMounted || !device) return;

      setConnectionState('connecting');
      setError(null);

      try {
        const connection = await connectToStream(
          device.id,
          (state) => {
            if (isMounted) {
              setConnectionState(state);
            }
          }
        );

        if (!isMounted) {
          // Component unmounted during connection, cleanup
          await disconnectStream(connection);
          return;
        }

        connectionRef.current = connection;

        // Attach media stream to video element
        if (videoRef.current) {
          videoRef.current.srcObject = connection.mediaStream;
          try {
            await videoRef.current.play();
            console.log('[VideoPlayer] Video playback started');

            // Start fall detection after video is playing
            // Previous: fps: 5 (200ms) caused delay due to slow CPU inference
            if (detectionEnabled) {
              fallDetectionRef.current = new FallDetectionManager({ fps: 2 });  // 500ms interval
              fallDetectionRef.current.start(videoRef.current, (result) => {
                if (isMounted) {
                  setFallDetection(result);
                  // Log detection results
                  if (result.violation_detected) {
                    console.log('[FallDetection] FALL DETECTED!', {
                      type: result.violation_type,
                      confidence: result.confidence,
                      severity: result.severity,
                    });
                  }
                }
              });
              console.log('[VideoPlayer] Fall detection started');
            }
          } catch (playError) {
            console.error('[VideoPlayer] Autoplay failed:', playError);
            // User interaction may be required for autoplay
          }
        }

        setRetryCount(0);
      } catch (err) {
        console.error('[VideoPlayer] Connection failed:', err);
        if (isMounted) {
          const message = err instanceof Error ? err.message : 'Connection failed';
          setError(message);
          setConnectionState('failed');

          // Retry once on failure
          if (retryCount < 1) {
            setRetryCount((c) => c + 1);
            console.log('[VideoPlayer] Retrying connection...');
            setTimeout(() => {
              if (isMounted) {
                connect();
              }
            }, 2000);
          }
        }
      }
    }

    connect();

    return () => {
      isMounted = false;
      cleanup();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [device?.id, cleanup]); // Only reconnect when device ID changes

  // Handle manual retry
  const handleRetry = () => {
    setRetryCount(0);
    setError(null);
    if (device) {
      setConnectionState('connecting');
      connectToStream(device.id, setConnectionState)
        .then((connection) => {
          connectionRef.current = connection;
          if (videoRef.current) {
            videoRef.current.srcObject = connection.mediaStream;
            videoRef.current.play().catch(console.error);
          }
          setRetryCount(0);
        })
        .catch((err) => {
          const message = err instanceof Error ? err.message : 'Connection failed';
          setError(message);
          setConnectionState('failed');
        });
    }
  };

  // Render no device selected state
  if (!device) {
    return (
      <div className="video-player">
        <div className="video-placeholder">
          <p>Select a device to view live feed</p>
        </div>
      </div>
    );
  }

  // Toggle fall detection
  const toggleDetection = () => {
    if (detectionEnabled && fallDetectionRef.current) {
      fallDetectionRef.current.stop();
      fallDetectionRef.current = null;
      setFallDetection(null);
    } else if (!detectionEnabled && videoRef.current && connectionState === 'connected') {
      fallDetectionRef.current = new FallDetectionManager({ fps: 2 });  // 500ms interval
      fallDetectionRef.current.start(videoRef.current, setFallDetection);
    }
    setDetectionEnabled(!detectionEnabled);
  };

  return (
    <div className="video-player">
      <div className="video-header">
        <h2>{device.name}</h2>
        <div className="header-controls">
          <button
            className={`detection-toggle ${detectionEnabled ? 'active' : ''}`}
            onClick={toggleDetection}
          >
            AI Detection: {detectionEnabled ? 'ON' : 'OFF'}
          </button>
          <span className={`connection-status ${connectionState}`}>
            {connectionState}
          </span>
        </div>
      </div>

      <div className="video-container">
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className={connectionState === 'connected' ? 'visible' : 'hidden'}
        />

        {/* Canvas overlay for bounding boxes and skeletons */}
        <canvas
          ref={canvasRef}
          className="detection-canvas"
        />

        {/* Fall Detection Status Overlay */}
        {connectionState === 'connected' && detectionEnabled && (
          <div className={`fall-detection-overlay ${fallDetection?.violation_detected ? 'fall-detected' : ''}`}>
            <div className="detection-status">
              {fallDetection ? (
                <>
                  <span className={`status-indicator ${fallDetection.violation_detected ? 'danger' : 'safe'}`}>
                    {fallDetection.violation_detected ? 'FALL DETECTED' : 'NO FALL'}
                  </span>
                  {fallDetection.violation_detected && (
                    <span className="confidence">
                      Confidence: {(fallDetection.confidence * 100).toFixed(1)}%
                    </span>
                  )}
                  <span className="detection-info">
                    Persons: {fallDetection.detection_count}
                  </span>
                </>
              ) : (
                <span className="status-indicator initializing">Initializing...</span>
              )}
            </div>
          </div>
        )}

        {connectionState !== 'connected' && (
          <div className="video-overlay">
            {connectionState === 'failed' && error ? (
              <div className="error-state">
                <p className="error-message">{error}</p>
                <button onClick={handleRetry}>Retry Connection</button>
              </div>
            ) : (
              <div className="loading-state">
                <div className="spinner"></div>
                <p>{connectionState}</p>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="video-info">
        <span>Device ID: {device.id}</span>
        {device.location && <span>Location: {device.location}</span>}
        {fallDetection && (
          <span className="model-info">Model: {fallDetection.model}</span>
        )}
      </div>
    </div>
  );
}
