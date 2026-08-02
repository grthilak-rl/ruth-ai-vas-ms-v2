/**
 * Detections API
 *
 * Reads the backend inference loop's latest detection result for a camera.
 *
 * The backend is the single source of detections: it runs inference on frames
 * tapped from VAS's existing decode pipeline, so browsers render results
 * rather than computing their own. This module is the read side of that.
 *
 * Source: GET /api/v1/devices/{device_id}/detections/latest
 */

import { apiGet } from './client';
import { ApiError } from './errors';

/**
 * Base path for device-scoped endpoints.
 *
 * buildApiUrl() only prepends the origin, so the /api/v1 prefix has to be part
 * of the path here — exactly as devices.api.ts, models.api.ts and
 * violations.api.ts all do. Omitting it does not fail loudly: nginx serves the
 * SPA's index.html for any unmatched route, so the request returns 200 with
 * 393 bytes of HTML and the caller silently parses no detections.
 */
const DEVICES_PATH = '/api/v1/devices';

/**
 * A single fall_detection box.
 *
 * Coordinates are in the model's 640x640 space (the model resizes every frame
 * to 640x640 and reports against that), NOT frame pixels. This is why
 * drawFallDetections scales by MODEL_SIZE rather than by frame dimensions.
 */
export interface DetectionBox {
  bbox: [number, number, number, number];
  confidence: number;
  keypoints?: Array<{ x: number; y: number; confidence: number }>;
}

/**
 * Raw model output, passed through from the AI runtime unchanged.
 *
 * Shape is identical to what /api/v1/ai/inference returns, because the
 * backend loop calls that same runtime with the same models — which is why
 * the existing overlay renderers consume this without modification.
 */
export interface DetectionResult {
  violation_detected: boolean;
  violation_type: string | null;
  severity?: string;
  confidence: number;
  detections: DetectionBox[];
  detection_count: number;
  // Model-specific extras (tank level, chane fill, PPE person records, ...)
  [key: string]: unknown;
}

export interface LatestDetectionResponse {
  device_id: string;
  model_id: string;
  model_version: string | null;
  result: DetectionResult;
  /**
   * Geometry of the frame the model actually saw. Bounding boxes are only
   * meaningful against this, so it must travel with the result — PPE reports
   * in frame pixels and needs it to map onto a tile of any size.
   */
  frame_width: number | null;
  frame_height: number | null;
  /** How stale this result is, in milliseconds. */
  age_ms: number;
}

/**
 * Fetch the newest detection result for a device.
 *
 * Returns null when there is nothing to draw. A 404 is the ordinary case —
 * a camera with no model enabled, or one whose session hasn't produced its
 * first result yet — so it is deliberately not surfaced as an error; the
 * caller renders no overlay and moves on.
 */
export async function fetchLatestDetections(
  deviceId: string
): Promise<LatestDetectionResponse | null> {
  try {
    return await apiGet<LatestDetectionResponse>(
      `${DEVICES_PATH}/${deviceId}/detections/latest`
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}
