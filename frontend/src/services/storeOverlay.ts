/**
 * Live overlay for uploaded (model store) models.
 *
 * Store models run a generic plugin whose results carry every detection in
 * `result.objects` (frame pixels) and `result.metadata.source === 'store'`.
 * This draws them as a box plus "<model> · <class> <confidence>" label: red
 * for detections a violation rule fired on, blue otherwise.
 *
 * Built-in models never produce store overlays, and with none to draw no
 * canvas call is made, so built-in rendering is untouched.
 */

import type { DetectionEntry } from '../state/api/detections.api';

export interface StoreObject {
  bbox: [number, number, number, number];
  confidence: number;
  class_name: string;
  violation?: boolean;
}

export interface StoreOverlay {
  modelId: string;
  displayName: string;
  frameWidth: number;
  frameHeight: number;
  objects: StoreObject[];
}

export const STORE_VIOLATION_COLOR = '#ef4444';
export const STORE_OBJECT_COLOR = '#38bdf8';
const LABEL_HEIGHT = 18;

/** Shared empty result, so callers memoising on it see a stable reference. */
export const NO_STORE_OVERLAYS: readonly StoreOverlay[] = Object.freeze([]);

/**
 * Store-model entries of a /detections response, as overlays.
 *
 * @param enabledModels same meaning as for fanOutDetections: when given,
 *                      only these models are drawn
 */
export function storeOverlaysFrom(
  entries: readonly DetectionEntry[] | null | undefined,
  enabledModels?: readonly string[] | null
): readonly StoreOverlay[] {
  if (!entries || entries.length === 0) return NO_STORE_OVERLAYS;
  const out: StoreOverlay[] = [];
  for (const entry of entries) {
    if (enabledModels && !enabledModels.includes(entry.model_id)) continue;
    const result = entry.result as Record<string, unknown> | null | undefined;
    const metadata = result?.metadata as Record<string, unknown> | undefined;
    if (!result || metadata?.source !== 'store' || !Array.isArray(result.objects)) continue;
    if (!entry.frame_width || !entry.frame_height) continue; // boxes are meaningless without them
    out.push({
      modelId: entry.model_id,
      displayName: typeof metadata.display_name === 'string' ? metadata.display_name : entry.model_id,
      frameWidth: entry.frame_width,
      frameHeight: entry.frame_height,
      objects: result.objects as StoreObject[],
    });
  }
  return out.length ? out : NO_STORE_OVERLAYS;
}

export function drawStoreDetections(
  ctx: CanvasRenderingContext2D,
  overlays: readonly StoreOverlay[],
  canvasWidth: number,
  canvasHeight: number
): void {
  for (const overlay of overlays) {
    const sx = canvasWidth / overlay.frameWidth;
    const sy = canvasHeight / overlay.frameHeight;
    for (const obj of overlay.objects) {
      if (!Array.isArray(obj.bbox) || obj.bbox.length !== 4) continue;
      const [x1, y1, x2, y2] = obj.bbox;
      const bx = x1 * sx;
      const by = y1 * sy;
      const bw = (x2 - x1) * sx;
      const bh = (y2 - y1) * sy;
      const color = obj.violation ? STORE_VIOLATION_COLOR : STORE_OBJECT_COLOR;

      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.strokeRect(bx, by, bw, bh);

      const label = `${overlay.displayName} · ${obj.class_name} ${Math.round(obj.confidence * 100)}%`;
      ctx.font = 'bold 12px sans-serif';
      const textWidth = ctx.measureText(label).width;
      // Above the box, or just inside its top edge when there is no room.
      const labelTop = by >= LABEL_HEIGHT ? by - LABEL_HEIGHT : by;
      ctx.fillStyle = color;
      ctx.fillRect(bx, labelTop, textWidth + 8, LABEL_HEIGHT);
      ctx.fillStyle = '#ffffff';
      ctx.fillText(label, bx + 4, labelTop + 13);
    }
  }
}
