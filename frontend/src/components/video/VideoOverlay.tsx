import { useRef, useEffect, useCallback, memo } from 'react';
import './VideoOverlay.css';

/**
 * Detection bounding box (operator-safe format)
 *
 * Per E10: No confidence numbers, no model names, no inference metrics
 */
export interface DetectionBox {
  /** Unique ID for the detection */
  id: string;
  /** X coordinate (0-1 normalized) */
  x: number;
  /** Y coordinate (0-1 normalized) */
  y: number;
  /** Width (0-1 normalized) */
  width: number;
  /** Height (0-1 normalized) */
  height: number;
  /** Optional label (operator-safe, e.g., "Person", "Activity") */
  label?: string;
  /** Category for styling (high/medium/low) - derived from confidence internally */
  category?: 'high' | 'medium' | 'low';
}

interface VideoOverlayProps {
  /** Detection boxes to render (coordinates normalized 0-1 from MODEL_SIZE) */
  detections: DetectionBox[];
  /** Canvas width (matches container) */
  videoWidth: number;
  /** Canvas height (matches container) */
  videoHeight: number;
  /** Native video width - no longer used, kept for API compat */
  nativeVideoWidth?: number;
  /** Native video height - no longer used, kept for API compat */
  nativeVideoHeight?: number;
  /** Whether overlays are enabled */
  enabled?: boolean;
  /** Whether AI detection is active */
  isDetectionActive?: boolean;
}

// Throttle config for performance
const REDRAW_THROTTLE_MS = 16; // ~60fps max

/**
 * Video Overlay Component (E10)
 *
 * Renders detection overlays on top of live video.
 *
 * Per E10 Spec:
 * - Overlays are purely visual
 * - No confidence numbers
 * - No model names
 * - No inference metrics
 * - Video playback continues even when overlays are disabled
 *
 * Per E10 Performance:
 * - Throttle overlay redraws to avoid UI jank
 * - Video rendering does not block React main thread
 *
 * HARD RULES:
 * - Overlays disappear when detection is paused/unavailable
 * - Never block video playback
 */
export const VideoOverlay = memo(function VideoOverlay({
  detections,
  videoWidth,
  videoHeight,
  nativeVideoWidth: _nativeVideoWidth, // Kept for API compat
  nativeVideoHeight: _nativeVideoHeight, // Kept for API compat
  enabled = true,
  isDetectionActive = true,
}: VideoOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const lastDrawRef = useRef<number>(0);
  const animationFrameRef = useRef<number | null>(null);

  // Draw detections on canvas
  const drawDetections = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear previous frame
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Don't draw if disabled or detection not active
    if (!enabled || !isDetectionActive || detections.length === 0) {
      return;
    }

    // Draw each detection box
    // Coordinates are normalized (0-1) from MODEL_SIZE (640x640)
    // Scale directly to canvas size
    detections.forEach(detection => {
      // Convert normalized coordinates (0-1) to pixel coordinates
      const x = detection.x * videoWidth;
      const y = detection.y * videoHeight;
      const width = detection.width * videoWidth;
      const height = detection.height * videoHeight;

      // Style based on category
      const strokeColor = getStrokeColor(detection.category);
      const fillColor = getFillColor(detection.category);

      // Draw bounding box
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, width, height);

      // Draw semi-transparent fill
      ctx.fillStyle = fillColor;
      ctx.fillRect(x, y, width, height);

      // Draw label if present
      if (detection.label) {
        const labelHeight = 20;
        const labelY = y > labelHeight ? y - labelHeight : y + height;

        // Label background
        ctx.fillStyle = strokeColor;
        const textWidth = ctx.measureText(detection.label).width + 8;
        ctx.fillRect(x, labelY, textWidth, labelHeight);

        // Label text
        ctx.fillStyle = '#ffffff';
        ctx.font = '12px sans-serif';
        ctx.fillText(detection.label, x + 4, labelY + 14);
      }
    });
  }, [detections, videoWidth, videoHeight, enabled, isDetectionActive]);

  // Throttled draw function
  const throttledDraw = useCallback(() => {
    const now = performance.now();
    if (now - lastDrawRef.current < REDRAW_THROTTLE_MS) {
      // Schedule next frame
      animationFrameRef.current = requestAnimationFrame(throttledDraw);
      return;
    }

    lastDrawRef.current = now;
    drawDetections();
  }, [drawDetections]);

  // Update canvas size when video dimensions change
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas) {
      canvas.width = videoWidth;
      canvas.height = videoHeight;
    }
  }, [videoWidth, videoHeight]);

  // Redraw when detections or enabled state changes
  useEffect(() => {
    // Cancel any pending animation frame
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
    }

    // Schedule draw
    animationFrameRef.current = requestAnimationFrame(throttledDraw);

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, [throttledDraw]);

  // Don't render canvas if no dimensions
  if (videoWidth <= 0 || videoHeight <= 0) {
    return null;
  }

  return (
    <canvas
      ref={canvasRef}
      className="video-overlay"
      width={videoWidth}
      height={videoHeight}
      aria-hidden="true"
    />
  );
});

/**
 * Get stroke color based on detection category
 */
function getStrokeColor(category?: 'high' | 'medium' | 'low'): string {
  switch (category) {
    case 'high':
      return '#c5221f'; // Red for high confidence
    case 'medium':
      return '#f9a825'; // Amber for medium
    case 'low':
      return '#1a73e8'; // Blue for low (less urgent)
    default:
      return '#1a73e8'; // Default to blue
  }
}

/**
 * Get fill color (semi-transparent) based on category
 */
function getFillColor(category?: 'high' | 'medium' | 'low'): string {
  switch (category) {
    case 'high':
      return 'rgba(197, 34, 31, 0.15)';
    case 'medium':
      return 'rgba(249, 168, 37, 0.15)';
    case 'low':
      return 'rgba(26, 115, 232, 0.15)';
    default:
      return 'rgba(26, 115, 232, 0.15)';
  }
}
