/**
 * Fall Detection Service
 * Extracts frames from video element and sends to unified AI runtime via backend API
 */

export interface Keypoint {
  x: number;
  y: number;
  confidence: number;
}

export interface Detection {
  bbox: [number, number, number, number]; // [x1, y1, x2, y2]
  confidence: number;
  keypoints: Keypoint[];
}

export interface FallDetectionResult {
  success: boolean;
  model: string;
  violation_detected: boolean;
  violation_type: string | null;
  severity?: string;
  confidence: number;
  detection_count: number;
  detections: Detection[];
  timestamp: number;
  // Store video dimensions for coordinate scaling
  videoWidth?: number;
  videoHeight?: number;
}

export interface FallDetectionConfig {
  fps: number;           // Frame rate for inference (default: 5)
  enabled: boolean;      // Whether detection is active
}

// COCO keypoint connections for skeleton drawing
export const SKELETON_CONNECTIONS: [number, number][] = [
  [0, 1], [0, 2],           // nose to eyes
  [1, 3], [2, 4],           // eyes to ears
  [5, 6],                    // shoulders
  [5, 7], [7, 9],           // left arm
  [6, 8], [8, 10],          // right arm
  [5, 11], [6, 12],         // torso
  [11, 12],                  // hips
  [11, 13], [13, 15],       // left leg
  [12, 14], [14, 16],       // right leg
];

const DEFAULT_CONFIG: FallDetectionConfig = {
  // Previous setting: fps: 5 (200ms interval) - caused 30s delay due to slow CPU inference
  fps: 2,  // 500ms interval - matching earlier ruth-ai-monitor version
  enabled: true,
};

/**
 * Convert a Blob to a base64-encoded string (without the data URI prefix)
 */
function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const dataUrl = reader.result as string;
      // Strip the "data:<mime>;base64," prefix
      const base64 = dataUrl.split(',')[1];
      if (base64) {
        resolve(base64);
      } else {
        reject(new Error('Failed to convert blob to base64'));
      }
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

/**
 * Extract a single frame from video element as JPEG blob
 */
export function extractFrameFromVideo(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement
): Promise<Blob | null> {
  return new Promise((resolve) => {
    if (!video.videoWidth || !video.videoHeight) {
      console.warn('[FallDetection] Video not ready for frame extraction');
      resolve(null);
      return;
    }

    // Set canvas size to match video
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      console.error('[FallDetection] Could not get canvas context');
      resolve(null);
      return;
    }

    // Draw video frame to canvas
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    // Convert to JPEG blob
    canvas.toBlob(
      (blob) => {
        resolve(blob);
      },
      'image/jpeg',
      0.8 // Quality
    );
  });
}

/**
 * Send frame to unified AI runtime via backend API
 */
export async function detectFall(
  frameBlob: Blob,
  videoWidth?: number,
  videoHeight?: number
): Promise<FallDetectionResult | null> {
  try {
    const frameBase64 = await blobToBase64(frameBlob);

    const response = await fetch('/api/v1/ai/inference', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model_id: 'fall_detection',
        frame: frameBase64,
      }),
    });

    if (!response.ok) {
      console.error('[FallDetection] API error:', response.status, response.statusText);
      return null;
    }

    const result = await response.json();
    return {
      success: true,
      model: 'fall_detection',
      violation_detected: result.violation_detected ?? false,
      violation_type: result.violation_type ?? null,
      severity: result.severity,
      confidence: result.confidence ?? 0,
      detection_count: result.detection_count ?? (result.detections?.length ?? 0),
      detections: result.detections || [],
      timestamp: Date.now(),
      videoWidth,
      videoHeight,
    };
  } catch (error) {
    console.error('[FallDetection] Request failed:', error);
    return null;
  }
}

/**
 * Check if fall detection model is available via backend health endpoint
 */
export async function checkModelHealth(): Promise<boolean> {
  try {
    const response = await fetch('/api/v1/health');
    if (!response.ok) return false;
    const data = await response.json();
    // Backend is healthy — unified runtime manages model availability
    return data.status === 'healthy' || data.status === 'ok';
  } catch {
    return false;
  }
}

/**
 * Fall Detection Manager
 * Manages continuous frame extraction and inference
 */
export class FallDetectionManager {
  private video: HTMLVideoElement | null = null;
  private canvas: HTMLCanvasElement;
  private config: FallDetectionConfig;
  private intervalId: number | null = null;
  private isProcessing = false;
  private onResult: ((result: FallDetectionResult) => void) | null = null;

  constructor(config: Partial<FallDetectionConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    // Create offscreen canvas for frame extraction
    this.canvas = document.createElement('canvas');
  }

  /**
   * Start fall detection on video element
   */
  start(
    video: HTMLVideoElement,
    onResult: (result: FallDetectionResult) => void
  ): void {
    this.video = video;
    this.onResult = onResult;

    if (!this.config.enabled) {
      console.log('[FallDetection] Detection disabled');
      return;
    }

    const intervalMs = 1000 / this.config.fps;
    console.log(`[FallDetection] Starting detection at ${this.config.fps} FPS (${intervalMs}ms interval)`);

    this.intervalId = window.setInterval(() => {
      this.processFrame();
    }, intervalMs);
  }

  /**
   * Stop fall detection
   */
  stop(): void {
    if (this.intervalId !== null) {
      window.clearInterval(this.intervalId);
      this.intervalId = null;
    }
    this.video = null;
    this.onResult = null;
    this.isProcessing = false;
    console.log('[FallDetection] Detection stopped');
  }

  /**
   * Process a single frame
   */
  private async processFrame(): Promise<void> {
    // Skip if already processing or video not ready
    if (this.isProcessing || !this.video || !this.onResult) {
      return;
    }

    // Skip if video is paused or not playing
    if (this.video.paused || this.video.ended || this.video.readyState < 2) {
      return;
    }

    this.isProcessing = true;

    try {
      // Extract frame
      const frameBlob = await extractFrameFromVideo(this.video, this.canvas);
      if (!frameBlob) {
        return;
      }

      // Send to model with video dimensions for coordinate scaling
      const result = await detectFall(
        frameBlob,
        this.video.videoWidth,
        this.video.videoHeight
      );
      if (result && this.onResult) {
        this.onResult(result);
      }
    } catch (error) {
      console.error('[FallDetection] Frame processing error:', error);
    } finally {
      this.isProcessing = false;
    }
  }

  /**
   * Update configuration
   */
  setConfig(config: Partial<FallDetectionConfig>): void {
    const wasRunning = this.intervalId !== null;
    const video = this.video;
    const onResult = this.onResult;

    if (wasRunning) {
      this.stop();
    }

    this.config = { ...this.config, ...config };

    if (wasRunning && video && onResult) {
      this.start(video, onResult);
    }
  }
}

// Model outputs coordinates in 640x640 space (matching POC).
// Kept in sync with LiveVideoPlayer's expectation.
const MODEL_SIZE = 640;

/**
 * Check if a detection represents a fallen person based on pose.
 * Uses keypoint positions to determine if the person is horizontal/fallen.
 */
export function isPersonFallen(detection: Detection): boolean {
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
    if (verticalDiff < 50) {
      return true;
    }
  }

  // Alternative check: if ankles are at same level as hips/shoulders
  if (ankleY !== null && hipY !== null) {
    const ankleHipDiff = Math.abs(ankleY - hipY);
    if (ankleHipDiff < 80) {
      return true;
    }
  }

  return false;
}

/**
 * Draw fall-detection overlays (bounding boxes + skeletons) on a canvas.
 * Each detection is colored based on its own fall state.
 *
 * Extracted from LiveVideoPlayer so the bookmark-monitoring view can
 * render the exact same overlay without duplication. Behavior is
 * identical to the prior in-file implementation.
 */
export function drawFallDetections(
  ctx: CanvasRenderingContext2D,
  detections: Detection[],
  canvasWidth: number,
  canvasHeight: number,
): void {
  const scaleX = canvasWidth / MODEL_SIZE;
  const scaleY = canvasHeight / MODEL_SIZE;

  detections.forEach((detection, idx) => {
    const [x1, y1, x2, y2] = detection.bbox;
    const isFallen = isPersonFallen(detection);

    const sx1 = x1 * scaleX;
    const sy1 = y1 * scaleY;
    const sx2 = x2 * scaleX;
    const sy2 = y2 * scaleY;

    ctx.strokeStyle = isFallen ? '#ef4444' : '#22c55e';
    ctx.lineWidth = 3;
    ctx.strokeRect(sx1, sy1, sx2 - sx1, sy2 - sy1);

    const label = isFallen ? `Person ${idx + 1} - FALL` : `Person ${idx + 1}`;
    ctx.font = 'bold 14px sans-serif';
    const textWidth = ctx.measureText(label).width;
    ctx.fillStyle = isFallen ? '#ef4444' : '#22c55e';
    ctx.fillRect(sx1, sy1 - 22, textWidth + 10, 22);

    ctx.fillStyle = '#ffffff';
    ctx.fillText(label, sx1 + 5, sy1 - 6);

    if (detection.keypoints && detection.keypoints.length >= 17) {
      const keypoints = detection.keypoints;

      ctx.strokeStyle = isFallen ? '#fca5a5' : '#86efac';
      ctx.lineWidth = 2;

      SKELETON_CONNECTIONS.forEach(([i, j]) => {
        const kp1 = keypoints[i];
        const kp2 = keypoints[j];
        if (kp1.confidence > 0.3 && kp2.confidence > 0.3) {
          ctx.beginPath();
          ctx.moveTo(kp1.x * scaleX, kp1.y * scaleY);
          ctx.lineTo(kp2.x * scaleX, kp2.y * scaleY);
          ctx.stroke();
        }
      });

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
