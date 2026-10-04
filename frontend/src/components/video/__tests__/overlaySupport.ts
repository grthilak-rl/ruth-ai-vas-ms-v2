/**
 * Test support: a canvas context that records every property set and method
 * call, and fixed fixtures for the fall / PPE renderers.
 *
 * The recorded call log is the renderer's complete observable output, so two
 * logs being equal means two renders are pixel-for-pixel the same drawing.
 */

import type { RawUnifiedPPEResponse } from '../../../services/ppeDetection';

export type CanvasCall = [string, ...unknown[]];

/** measureText width: deterministic stand-in for real font metrics. */
const CHAR_WIDTH = 7;

export function recordingContext(): { ctx: CanvasRenderingContext2D; calls: CanvasCall[] } {
  const calls: CanvasCall[] = [];
  const state: Record<string, unknown> = {};
  const ctx = new Proxy(state, {
    get(target, prop) {
      if (prop === 'measureText') {
        return (text: string) => {
          calls.push(['measureText', text]);
          return { width: text.length * CHAR_WIDTH };
        };
      }
      if (typeof prop === 'string' && prop in target) return target[prop];
      return (...args: unknown[]) => {
        calls.push([String(prop), ...args]);
      };
    },
    set(target, prop, value) {
      calls.push([`set ${String(prop)}`, value]);
      target[String(prop)] = value;
      return true;
    },
  });
  return { ctx: ctx as unknown as CanvasRenderingContext2D, calls };
}

export const CANVAS_WIDTH = 640;
export const CANVAS_HEIGHT = 360;
export const FRAME_WIDTH = 1280;
export const FRAME_HEIGHT = 720;

function skeleton(cx: number, top: number, horizontal: boolean) {
  // 17 COCO keypoints; a "horizontal" person lies along x (a fall).
  return Array.from({ length: 17 }, (_, i) => ({
    x: horizontal ? cx - 160 + i * 20 : cx + ((i % 2) * 20 - 10),
    y: horizontal ? top + 20 + (i % 3) * 4 : top + i * 25,
    confidence: 0.9,
  }));
}

/** Two fall_detection persons (640x640 model space): one upright, one fallen. */
export const FALL_DETECTIONS = [
  { bbox: [100, 80, 180, 500] as [number, number, number, number], confidence: 0.92, keypoints: skeleton(140, 90, false) },
  { bbox: [300, 380, 620, 460] as [number, number, number, number], confidence: 0.88, keypoints: skeleton(460, 380, true) },
];

/** A raw unified-runtime PPE response (frame pixels): person, hardhat present, vest missing. */
export const PPE_RAW: RawUnifiedPPEResponse = {
  violation_detected: true,
  violation_type: 'missing_vest',
  severity: 'critical',
  confidence: 0.81,
  persons_detected: 1,
  violations: ['vest'],
  ppe_present: ['hardhat'],
  detections: [
    { item: 'person', status: 'present', confidence: 0.9, bbox: [400, 100, 700, 700], class_id: 0, class_name: 'person', model_source: 'person' },
    { item: 'hardhat', status: 'present', confidence: 0.77, bbox: [480, 100, 600, 180], class_id: 0, class_name: 'hardhat', model_source: 'hardhat' },
    { item: 'vest', status: 'missing', confidence: 0.71, bbox: [430, 250, 680, 480], class_id: 0, class_name: 'no-vest', model_source: 'no_vest' },
  ],
  metadata: { model_name: 'ppe_detector', model_version: '1.0.0', mode: 'full' },
};

/** Pinned so transformAPIResponse's timestamp is reproducible. */
export const FIXED_NOW = new Date('2026-10-04T12:00:00Z');
