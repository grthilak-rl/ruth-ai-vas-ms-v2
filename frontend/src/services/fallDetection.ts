/**
 * Fall Detection Service
 * Extracts frames from video element and sends to fall detection model
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
 * Send frame to fall detection model API
 */
export async function detectFall(
  frameBlob: Blob,
  videoWidth?: number,
  videoHeight?: number
): Promise<FallDetectionResult | null> {
  try {
    const formData = new FormData();
    formData.append('file', frameBlob, 'frame.jpg');

    const response = await fetch('/fall-detection/detect', {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      console.error('[FallDetection] API error:', response.status, response.statusText);
      return null;
    }

    const result = await response.json();
    return {
      ...result,
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
 * Check if fall detection model is available
 */
export async function checkModelHealth(): Promise<boolean> {
  try {
    const response = await fetch('/fall-detection/health');
    if (!response.ok) return false;
    const data = await response.json();
    return data.status === 'healthy';
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
