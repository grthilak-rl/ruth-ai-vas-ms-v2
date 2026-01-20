/**
 * Tank Overflow Detection Service
 * Extracts frames from video element and sends to tank overflow model (client-side)
 */

export interface TankDetection {
  surface_y: number;
  bbox: [number, number, number, number];
  confidence: number;
}

export interface TankDetectionResult {
  violation_detected: boolean;
  violation_type: 'tank_overflow_warning' | 'tank_critical_high' | 'tank_critical_low' | null;
  severity: 'critical' | 'high' | 'medium' | 'low';
  confidence: number;
  level_percent: number;
  level_liters: number;
  capacity_liters: number;
  detections: TankDetection[];
  metadata: {
    inference_time_ms: number;
    model_name: string;
    model_version: string;
    alert_threshold: number;
    status: string;
    timestamp: string;
  };
}

interface TankDetectionConfig {
  fps?: number; // Frames per second to process
  tankCorners?: number[][]; // Tank region corners
  capacityLiters?: number; // Tank capacity
  alertThreshold?: number; // Alert threshold percentage
}

export class TankDetectionManager {
  private video: HTMLVideoElement | null = null;
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private intervalId: ReturnType<typeof setInterval> | null = null;
  private onResult: ((result: TankDetectionResult) => void) | null = null;
  private config: TankDetectionConfig;
  private isRunning = false;

  constructor(config: TankDetectionConfig = {}) {
    this.config = {
      fps: config.fps || 1, // Default 1 FPS for tank monitoring
      tankCorners: config.tankCorners,
      capacityLiters: config.capacityLiters || 1000, // Default 1000 liters
      alertThreshold: config.alertThreshold || 90,
    };

    // Create offscreen canvas for frame extraction
    this.canvas = document.createElement('canvas');
    this.ctx = this.canvas.getContext('2d')!;
  }

  /**
   * Start tank detection
   */
  start(video: HTMLVideoElement, onResult: (result: TankDetectionResult) => void): void {
    if (this.isRunning) {
      console.warn('[TankDetection] Already running');
      return;
    }

    this.video = video;
    this.onResult = onResult;
    this.isRunning = true;

    const interval = 1000 / this.config.fps!;
    console.log(`[TankDetection] Starting at ${this.config.fps} FPS (${interval}ms interval)`);

    this.intervalId = setInterval(() => {
      this.processFrame();
    }, interval);
  }

  /**
   * Stop tank detection
   */
  stop(): void {
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
    this.isRunning = false;
    this.video = null;
    this.onResult = null;
    console.log('[TankDetection] Stopped');
  }

  /**
   * Update configuration (e.g., when tank corners change)
   */
  updateConfig(config: Partial<TankDetectionConfig>): void {
    this.config = { ...this.config, ...config };
  }

  /**
   * Process a single frame
   */
  private async processFrame(): Promise<void> {
    console.log('[TankDetection] processFrame called', {
      hasVideo: !!this.video,
      hasOnResult: !!this.onResult,
      isRunning: this.isRunning,
      videoReadyState: this.video?.readyState,
      videoWidth: this.video?.videoWidth,
      videoHeight: this.video?.videoHeight,
    });

    if (!this.video || !this.onResult || !this.isRunning) {
      console.warn('[TankDetection] Skipping frame - missing requirements');
      return;
    }

    try {
      // Extract frame from video
      console.log('[TankDetection] Extracting frame...');
      const frame = this.extractFrame();
      if (!frame) {
        console.warn('[TankDetection] Frame extraction returned null');
        return;
      }
      console.log('[TankDetection] Frame extracted, size:', frame.length, 'bytes');

      // Send to unified AI runtime
      console.log('[TankDetection] Sending to runtime...');
      const result = await this.sendToRuntime(frame);
      console.log('[TankDetection] Runtime response:', result);

      if (result && this.onResult) {
        console.log('[TankDetection] Calling onResult callback with level:', result.level_percent);
        this.onResult(result);
      } else {
        console.warn('[TankDetection] No result or no callback', { result, hasCallback: !!this.onResult });
      }
    } catch (error) {
      console.error('[TankDetection] Frame processing error:', error);
    }
  }

  /**
   * Extract frame from video element
   */
  private extractFrame(): string | null {
    if (!this.video || this.video.readyState < 2) {
      return null;
    }

    try {
      // Set canvas size to video dimensions
      this.canvas.width = this.video.videoWidth;
      this.canvas.height = this.video.videoHeight;

      // Draw video frame to canvas
      this.ctx.drawImage(this.video, 0, 0);

      // Convert to base64 JPEG
      return this.canvas.toDataURL('image/jpeg', 0.8).split(',')[1];
    } catch (error) {
      console.error('[TankDetection] Frame extraction error:', error);
      return null;
    }
  }

  /**
   * Send frame to unified AI runtime
   */
  private async sendToRuntime(frameBase64: string): Promise<TankDetectionResult | null> {
    const requestBody = {
      model_id: 'tank_overflow_monitoring',
      version: '1.0.0',
      frame: frameBase64,
      config: {
        tank_corners: this.config.tankCorners,
        capacity_liters: this.config.capacityLiters,
        alert_threshold: this.config.alertThreshold,
      },
    };

    console.log('[TankDetection] API Request:', {
      url: '/api/v1/ai/inference',
      model_id: requestBody.model_id,
      frameSize: frameBase64.length,
      config: requestBody.config,
    });

    try {
      const response = await fetch('/api/v1/ai/inference', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
      });

      console.log('[TankDetection] API Response status:', response.status, response.statusText);

      if (!response.ok) {
        const errorText = await response.text();
        console.error('[TankDetection] API Error response:', errorText);
        throw new Error(`AI Runtime error: ${response.status} ${response.statusText}`);
      }

      const data = await response.json();
      console.log('[TankDetection] API Response data:', data);
      return data;
    } catch (error) {
      console.error('[TankDetection] Runtime request error:', error);
      return null;
    }
  }
}

/**
 * Draw tank overflow detection overlays on canvas
 */
export function drawTankDetections(
  ctx: CanvasRenderingContext2D,
  result: TankDetectionResult,
  canvasWidth: number,
  canvasHeight: number,
  tankCorners?: number[][]
): void {
  if (!result) return;

  // Get first detection if available (may be empty for edge-detection approach)
  const detection = result.detections?.[0];

  // Draw tank region if corners provided
  if (tankCorners && tankCorners.length === 4) {
    const scaleX = canvasWidth / 640; // Assuming 640x640 model space
    const scaleY = canvasHeight / 640;

    ctx.strokeStyle = '#22c55e'; // Green for tank boundary
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(tankCorners[0][0] * scaleX, tankCorners[0][1] * scaleY);
    for (let i = 1; i < tankCorners.length; i++) {
      ctx.lineTo(tankCorners[i][0] * scaleX, tankCorners[i][1] * scaleY);
    }
    ctx.closePath();
    ctx.stroke();
  }

  // Draw liquid surface line (if detection with bbox available)
  if (detection && detection.surface_y !== undefined && detection.bbox) {
    const [x1, y1, x2] = detection.bbox;
    const scaleX = canvasWidth / 640;
    const scaleY = canvasHeight / 640;

    const surfaceY = (y1 + detection.surface_y) * scaleY;
    const lineX1 = x1 * scaleX;
    const lineX2 = x2 * scaleX;

    // Color based on level
    let lineColor = '#22c55e'; // Green
    if (result.level_percent >= 95) {
      lineColor = '#ef4444'; // Red
    } else if (result.level_percent >= 90) {
      lineColor = '#f59e0b'; // Orange
    } else if (result.level_percent >= 75) {
      lineColor = '#eab308'; // Yellow
    }

    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(lineX1, surfaceY);
    ctx.lineTo(lineX2, surfaceY);
    ctx.stroke();

    // Draw label
    ctx.fillStyle = lineColor;
    ctx.font = 'bold 14px sans-serif';
    const label = `${result.level_percent.toFixed(1)}%`;
    const textWidth = ctx.measureText(label).width;
    ctx.fillRect(lineX1, surfaceY - 25, textWidth + 10, 20);
    ctx.fillStyle = '#ffffff';
    ctx.fillText(label, lineX1 + 5, surfaceY - 10);
  }

  // Draw info panel
  const level = result.level_percent;
  const capacity = result.capacity_liters || 1000;
  const volume = result.level_liters ?? (level / 100 * capacity);
  const status = result.metadata?.status || 'NORMAL';

  // Determine color based on severity
  let panelColor = '#22c55e'; // Green
  if (result.severity === 'critical') {
    panelColor = '#ef4444'; // Red
  } else if (result.severity === 'high') {
    panelColor = '#f59e0b'; // Orange
  } else if (result.severity === 'medium') {
    panelColor = '#eab308'; // Yellow
  }

  // Info box background
  const boxX = canvasWidth - 260;
  const boxY = 10;
  ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
  ctx.fillRect(boxX, boxY, 250, 110);
  ctx.strokeStyle = panelColor;
  ctx.lineWidth = 2;
  ctx.strokeRect(boxX, boxY, 250, 110);

  // Text
  ctx.fillStyle = panelColor;
  ctx.font = 'bold 16px sans-serif';
  ctx.fillText(`Tank Level: ${level.toFixed(1)}%`, boxX + 10, boxY + 25);

  ctx.fillStyle = '#ffffff';
  ctx.font = '14px sans-serif';
  ctx.fillText(`Volume: ${volume.toFixed(0)}L / ${capacity.toFixed(0)}L`, boxX + 10, boxY + 50);
  ctx.fillText(`Status: ${status}`, boxX + 10, boxY + 75);
  ctx.fillText(`Confidence: ${(result.confidence * 100).toFixed(0)}%`, boxX + 10, boxY + 100);
}
