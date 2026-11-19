/**
 * Bookmark monitoring for uploaded (model store) models: PPE models,
 * geofence, anything the store plugin serves.
 *
 * Samples the <video> like the fall manager, POSTs each frame to
 * /api/v1/ai/inference with the model's config (zones for zone models),
 * which routes store models to the model store runtime. The result is drawn
 * with the live store overlay (drawStoreDetections): every detection in
 * frame pixels, red where a rule fired.
 */

import { blobToBase64, extractFrameFromVideo } from './fallDetection';
import type { StoreObject, StoreOverlay } from './storeOverlay';
import type { ModelConfig } from '../types/geofencing';

/** A store result as an overlay; null for anything that is not one. */
export function storeOverlayFromResult(
  modelId: string,
  result: Record<string, unknown> | null | undefined,
): StoreOverlay | null {
  const metadata = result?.metadata as Record<string, unknown> | undefined;
  if (!result || metadata?.source !== 'store' || !Array.isArray(result.objects)) return null;
  const shape = metadata.frame_shape;
  if (!Array.isArray(shape) || shape.length < 2) return null; // boxes are meaningless without it
  const [height, width] = shape as number[];
  if (!width || !height) return null;
  return {
    modelId,
    displayName: typeof metadata.display_name === 'string' ? metadata.display_name : modelId,
    frameWidth: width,
    frameHeight: height,
    objects: result.objects as StoreObject[],
  };
}

export interface StoreDetectionResult {
  overlay: StoreOverlay | null;
  violationDetected: boolean;
  violationType: string | null;
}

/** One frame through a store model. Null on a failed request. */
export async function detectWithStoreModel(
  frameBlob: Blob,
  modelId: string,
  config: ModelConfig | null,
): Promise<StoreDetectionResult | null> {
  try {
    const response = await fetch('/api/v1/ai/inference', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model_id: modelId,
        frame: await blobToBase64(frameBlob),
        ...(config ? { config } : {}),
      }),
    });
    if (!response.ok) {
      console.error('[StoreDetection] API error:', response.status, response.statusText);
      return null;
    }
    const result = (await response.json()) as Record<string, unknown>;
    return {
      overlay: storeOverlayFromResult(modelId, result),
      violationDetected: result.violation_detected === true,
      violationType: typeof result.violation_type === 'string' ? result.violation_type : null,
    };
  } catch (error) {
    console.error('[StoreDetection] Request failed:', error);
    return null;
  }
}

export class StoreDetectionManager {
  private video: HTMLVideoElement | null = null;
  private readonly canvas: HTMLCanvasElement;
  private intervalId: number | null = null;
  private busy = false;
  private onResult: ((result: StoreDetectionResult) => void) | null = null;
  private readonly modelId: string;
  private readonly config: ModelConfig | null;
  private readonly fps: number;

  constructor(modelId: string, config: ModelConfig | null, fps: number = 1) {
    this.modelId = modelId;
    this.config = config;
    this.fps = fps;
    this.canvas = document.createElement('canvas');
  }

  start(video: HTMLVideoElement, onResult: (result: StoreDetectionResult) => void): void {
    this.video = video;
    this.onResult = onResult;
    this.intervalId = window.setInterval(() => void this.tick(), 1000 / this.fps);
  }

  stop(): void {
    if (this.intervalId !== null) window.clearInterval(this.intervalId);
    this.intervalId = null;
    this.video = null;
    this.onResult = null;
    this.busy = false;
  }

  private async tick(): Promise<void> {
    const video = this.video;
    if (this.busy || !video || !this.onResult) return;
    if (video.paused || video.ended || video.readyState < 2) return;
    this.busy = true;
    try {
      const blob = await extractFrameFromVideo(video, this.canvas);
      if (!blob) return;
      const result = await detectWithStoreModel(blob, this.modelId, this.config);
      if (result && this.onResult) this.onResult(result);
    } finally {
      this.busy = false;
    }
  }
}
