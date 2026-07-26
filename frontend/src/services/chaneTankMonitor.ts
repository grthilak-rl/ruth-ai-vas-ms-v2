/**
 * Chane Tank Monitor Detection Service (client-side)
 *
 * Parallel to tankDetection.ts but for the `chane_tank_monitor` model, which
 * has its OWN output vocabulary (fill_percentage / fill_90_detected /
 * anomaly_flag / blend_mean / roi) rather than tank_overflow_monitoring's
 * violation_detected/severity shape. Extracts frames from a <video> element,
 * POSTs them to the unified AI runtime, and draws the ROI circle + a fill bar
 * + anomaly banner on a canvas.
 */

export interface ChaneTankRoi {
  cx: number;
  cy: number;
  r: number;
  source: 'config' | 'fallback';
}

export interface ChaneTankResult {
  // Brightness-area fill vocabulary (replaces the old motion-blend fields).
  fill_percentage: number; // monotonic, for display
  fill_raw: number; // unclamped mapped value, for analysis
  bright_fraction: number; // raw bright-pixel fraction this frame
  bright_fraction_smoothed: number;
  mean_brightness: number;
  motion_blend: number; // instrumentation only — NOT the fill measure
  confidence: number;
  roi: ChaneTankRoi;
  metadata: Record<string, unknown>;
  // Intrinsic frame size at extraction time, used to scale ROI -> canvas.
  videoWidth?: number;
  videoHeight?: number;
}

interface ChaneTankConfig {
  fps?: number;
  // Optional manual circle ROI. When omitted the model auto-detects/falls back.
  roiCircle?: { cx: number; cy: number; r: number };
  // Tunables forwarded verbatim to the model config so they can be swept from
  // the UI/config WITHOUT a rebuild (brightness_threshold, smoothing_window,
  // fill_calib_min, fill_calib_max, csv_path, …). The model re-locks its
  // session when any of these change.
  extraConfig?: Record<string, unknown>;
}

export class ChaneTankMonitorManager {
  private video: HTMLVideoElement | null = null;
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private intervalId: ReturnType<typeof setInterval> | null = null;
  private onResult: ((result: ChaneTankResult) => void) | null = null;
  private config: ChaneTankConfig;
  private isRunning = false;

  constructor(config: ChaneTankConfig = {}) {
    this.config = {
      fps: config.fps || 1,
      roiCircle: config.roiCircle,
      extraConfig: config.extraConfig,
    };
    this.canvas = document.createElement('canvas');
    this.ctx = this.canvas.getContext('2d')!;
  }

  start(video: HTMLVideoElement, onResult: (result: ChaneTankResult) => void): void {
    if (this.isRunning) return;
    this.video = video;
    this.onResult = onResult;
    this.isRunning = true;
    const interval = 1000 / this.config.fps!;
    this.intervalId = setInterval(() => this.processFrame(), interval);
  }

  stop(): void {
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
    this.isRunning = false;
    this.video = null;
    this.onResult = null;
  }

  updateConfig(config: Partial<ChaneTankConfig>): void {
    this.config = { ...this.config, ...config };
  }

  private async processFrame(): Promise<void> {
    if (!this.video || !this.onResult || !this.isRunning) return;
    if (this.video.readyState < 2) return;
    try {
      const w = this.video.videoWidth;
      const h = this.video.videoHeight;
      const frame = this.extractFrame();
      if (!frame) return;
      // Clip position (seconds). Sent so the model can key off where we are in
      // the video rather than wall-clock elapsed: this survives pause, seek and
      // replay. Used by the timed-ramp demo mode (fill_time_based).
      const clipTime = this.video.currentTime;
      const result = await this.sendToRuntime(frame, clipTime);
      if (result && this.onResult) {
        result.videoWidth = w;
        result.videoHeight = h;
        this.onResult(result);
      }
    } catch (error) {
      console.error('[ChaneTankMonitor] Frame processing error:', error);
    }
  }

  private extractFrame(): string | null {
    if (!this.video || this.video.readyState < 2) return null;
    try {
      this.canvas.width = this.video.videoWidth;
      this.canvas.height = this.video.videoHeight;
      this.ctx.drawImage(this.video, 0, 0);
      return this.canvas.toDataURL('image/jpeg', 0.8).split(',')[1];
    } catch (error) {
      console.error('[ChaneTankMonitor] Frame extraction error:', error);
      return null;
    }
  }

  private async sendToRuntime(
    frameBase64: string,
    clipTime?: number,
  ): Promise<ChaneTankResult | null> {
    const config: Record<string, unknown> = { ...(this.config.extraConfig ?? {}) };
    if (this.config.roiCircle) config.roi_circle = this.config.roiCircle;
    if (clipTime !== undefined) config.clip_time_s = clipTime;

    const requestBody = {
      model_id: 'chane_tank_monitor',
      version: '1.0.0',
      frame: frameBase64,
      config,
    };

    try {
      const response = await fetch('/api/v1/ai/inference', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      });
      if (!response.ok) {
        const errorText = await response.text();
        console.error('[ChaneTankMonitor] API error:', response.status, errorText);
        throw new Error(`AI Runtime error: ${response.status}`);
      }
      return (await response.json()) as ChaneTankResult;
    } catch (error) {
      console.error('[ChaneTankMonitor] Runtime request error:', error);
      return null;
    }
  }
}

/**
 * Draw chane_tank_monitor overlays: the locked ROI circle, a fill bar
 * (monotonic display %), and the brightness signals. ROI coords are in the
 * intrinsic frame space, scaled to the canvas via videoWidth/videoHeight.
 */
export function drawChaneTankMonitor(
  ctx: CanvasRenderingContext2D,
  result: ChaneTankResult,
  canvasWidth: number,
  canvasHeight: number,
): void {
  if (!result) return;

  const fill = result.fill_percentage ?? 0;

  // ROI circle color ramps with fill: green -> yellow -> orange -> cyan(full).
  let color = '#22c55e'; // green
  if (fill >= 90) color = '#06b6d4'; // cyan (near/at full)
  else if (fill >= 60) color = '#f59e0b'; // orange
  else if (fill >= 30) color = '#eab308'; // yellow

  // Scale ROI (frame space) -> canvas.
  const fw = result.videoWidth || canvasWidth;
  const fh = result.videoHeight || canvasHeight;
  const scaleX = canvasWidth / fw;
  const scaleY = canvasHeight / fh;
  const roi = result.roi;

  if (roi && roi.r > 0) {
    const cx = roi.cx * scaleX;
    const cy = roi.cy * scaleY;
    const r = roi.r * ((scaleX + scaleY) / 2);
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  }

  // Info panel + fill bar (top-right).
  const boxX = canvasWidth - 270;
  const boxY = 10;
  const boxW = 260;
  const boxH = 150;
  ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
  ctx.fillRect(boxX, boxY, boxW, boxH);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.strokeRect(boxX, boxY, boxW, boxH);

  ctx.fillStyle = color;
  ctx.font = 'bold 16px sans-serif';
  ctx.fillText(`Fill: ${fill.toFixed(1)}%`, boxX + 10, boxY + 24);

  // Fill bar (display % is 0-100).
  const barX = boxX + 10;
  const barY = boxY + 34;
  const barW = boxW - 20;
  const barH = 16;
  ctx.fillStyle = '#3f3f46';
  ctx.fillRect(barX, barY, barW, barH);
  ctx.fillStyle = color;
  ctx.fillRect(barX, barY, barW * Math.max(0, Math.min(1, fill / 100)), barH);
  ctx.strokeStyle = '#a1a1aa';
  ctx.lineWidth = 1;
  ctx.strokeRect(barX, barY, barW, barH);

  ctx.fillStyle = '#ffffff';
  ctx.font = '13px sans-serif';
  ctx.fillText(
    `raw: ${result.fill_raw.toFixed(1)}%   bright: ${(result.bright_fraction * 100).toFixed(1)}%`,
    boxX + 10,
    boxY + 74,
  );
  ctx.fillText(
    `mean bright: ${result.mean_brightness.toFixed(0)}   motion: ${result.motion_blend.toFixed(3)}`,
    boxX + 10,
    boxY + 96,
  );
  ctx.fillText(`ROI source: ${roi?.source ?? '-'}`, boxX + 10, boxY + 118);
  ctx.fillText(
    `confidence: ${(result.confidence * 100).toFixed(0)}%`,
    boxX + 10,
    boxY + 140,
  );
}
