/**
 * Single-model render scenarios, recorded as canvas call logs.
 *
 * The drawers are passed in rather than imported so the same scenarios can be
 * run against the pre-M2 renderers to produce overlayDraw.golden.ts, and
 * against the current renderers to compare with it.
 */

import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
  FALL_DETECTIONS,
  FRAME_HEIGHT,
  FRAME_WIDTH,
  PPE_RAW,
  recordingContext,
  type CanvasCall,
} from './overlaySupport';

/* eslint-disable @typescript-eslint/no-explicit-any -- drawers from two code versions */
export interface Renderers {
  drawFallDetections: (ctx: CanvasRenderingContext2D, detections: any, w: number, h: number) => void;
  drawPPEDetections: (
    ctx: CanvasRenderingContext2D,
    detections: any,
    w: number,
    h: number,
    videoWidth?: number,
    videoHeight?: number
  ) => void;
  transformAPIResponse: (raw: any, mode: 'full', videoWidth?: number, videoHeight?: number) => any;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

export interface ScenarioOutput {
  calls: Record<string, CanvasCall[]>;
  ppeTransform: unknown;
}

export function runScenarios(r: Renderers): ScenarioOutput {
  const calls: Record<string, CanvasCall[]> = {};
  const record = (name: string, draw: (ctx: CanvasRenderingContext2D) => void) => {
    const rec = recordingContext();
    draw(rec.ctx);
    calls[name] = rec.calls;
  };

  const ppe = r.transformAPIResponse(PPE_RAW, 'full', FRAME_WIDTH, FRAME_HEIGHT);

  // Exactly the call shapes LiveVideoPlayer makes for one model.
  record('fall', (ctx) => r.drawFallDetections(ctx, FALL_DETECTIONS, CANVAS_WIDTH, CANVAS_HEIGHT));
  record('ppe', (ctx) =>
    r.drawPPEDetections(ctx, ppe.detections, CANVAS_WIDTH, CANVAS_HEIGHT, ppe.videoWidth, ppe.videoHeight)
  );
  record('ppe_unscaled', (ctx) => r.drawPPEDetections(ctx, ppe.detections, CANVAS_WIDTH, CANVAS_HEIGHT));

  return { calls, ppeTransform: ppe };
}
