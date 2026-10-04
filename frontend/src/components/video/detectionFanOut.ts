/**
 * Fan backend detection results out to the per-model shapes the overlay
 * renderers expect.
 *
 * Input is GET /devices/{id}/detections: one entry per model running on the
 * camera. Each entry fills its model's slot exactly as the single-result
 * switch in LiveVideoPlayer used to (same transforms, same defaults), so one
 * model renders exactly as before; several models fill several slots.
 *
 * Models without drawing code (geo person boxes, store models) fill nothing,
 * as before. A generic bbox overlay is deliberately out of scope here.
 */

import type { FallDetectionResult } from '../../services/fallDetection';
import {
  type PPEDetectionResult,
  type RawUnifiedPPEResponse,
  transformAPIResponse as transformPPEResponse,
} from '../../services/ppeDetection';
import type { TankDetectionResult } from '../../services/tankDetection';
import type { ChaneTankResult } from '../../services/chaneTankMonitor';
import type { DetectionEntry } from '../../state/api/detections.api';

export interface FannedOutDetections {
  fallDetection: FallDetectionResult | null;
  ppeDetection: PPEDetectionResult | null;
  tankDetection: TankDetectionResult | null;
  chaneTankDetection: ChaneTankResult | null;
}

export const EMPTY_FAN_OUT: FannedOutDetections = Object.freeze({
  fallDetection: null,
  ppeDetection: null,
  tankDetection: null,
  chaneTankDetection: null,
});

/** Map one entry to its slot. Verbatim from the former single-result switch. */
function slotFor(entry: DetectionEntry): Partial<FannedOutDetections> {
  if (!entry?.result) return {};
  const raw = entry.result as Record<string, unknown>;
  const frameWidth = entry.frame_width ?? undefined;
  const frameHeight = entry.frame_height ?? undefined;

  switch (entry.model_id) {
    case 'fall_detection':
      // Boxes are in the model's 640x640 space; drawFallDetections scales
      // by MODEL_SIZE, so no coordinate work is needed. The defaults mirror
      // what the old client-side path applied before handing results on —
      // the renderer assumes `detections` is always an array.
      return {
        fallDetection: {
          ...(raw as unknown as FallDetectionResult),
          detections: (raw.detections as FallDetectionResult['detections']) ?? [],
          confidence: (raw.confidence as number) ?? 0,
          videoWidth: frameWidth,
          videoHeight: frameHeight,
        },
      };
    case 'ppe_detection':
      // MUST go through the same transform the browser-side path used: the
      // runtime returns flat {item, status, bbox} rows, and drawPPEDetections
      // destructures per-person records. PPE reports in frame pixels, so the
      // backend's frame geometry travels with it.
      return {
        ppeDetection: transformPPEResponse(
          raw as unknown as RawUnifiedPPEResponse,
          'full',
          frameWidth,
          frameHeight
        ),
      };
    case 'tank_overflow_monitoring':
      return { tankDetection: raw as unknown as TankDetectionResult };
    case 'chane_tank_monitor':
      return { chaneTankDetection: raw as unknown as ChaneTankResult };
    default:
      return {};
  }
}

/**
 * @param entries        results from GET /devices/{id}/detections
 * @param enabledModels  when given, only these models are drawn (pages that
 *                       know the camera's server-side model list); when
 *                       omitted, everything the backend returns is drawn
 */
export function fanOutDetections(
  entries: readonly DetectionEntry[] | null | undefined,
  enabledModels?: readonly string[] | null
): FannedOutDetections {
  if (!entries || entries.length === 0) return EMPTY_FAN_OUT;
  const out: FannedOutDetections = { ...EMPTY_FAN_OUT };
  for (const entry of entries) {
    if (enabledModels && !enabledModels.includes(entry.model_id)) continue;
    Object.assign(out, slotFor(entry));
  }
  return out;
}
