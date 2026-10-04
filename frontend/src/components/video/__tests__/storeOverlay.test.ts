/**
 * Uploaded (model store) model overlay: drawn from result.objects, red for
 * violations; nothing at all for built-in models.
 */

import { describe, expect, it } from 'vitest';
import {
  NO_STORE_OVERLAYS,
  STORE_OBJECT_COLOR,
  STORE_VIOLATION_COLOR,
  drawStoreDetections,
  storeOverlaysFrom,
} from '../../../services/storeOverlay';
import type { DetectionEntry } from '../../../state/api/detections.api';
import { FALL_DETECTIONS, PPE_RAW, recordingContext } from './overlaySupport';

function entry(model_id: string, result: Record<string, unknown>, dims = true): DetectionEntry {
  return {
    model_id,
    model_version: '1.0.0',
    result,
    frame_width: dims ? 1280 : null,
    frame_height: dims ? 720 : null,
    age_ms: 100,
  } as unknown as DetectionEntry;
}

const HARD_HAT = entry('hard_hat', {
  violation_detected: true,
  violation_type: 'missing_hardhat',
  detections: [{ bbox: [400, 60, 450, 120], confidence: 0.83, class_name: 'no-hardhat', label: 'missing_hardhat' }],
  objects: [
    { bbox: [100, 50, 160, 110], confidence: 0.91, class_name: 'hardhat', violation: false },
    { bbox: [400, 10, 450, 70], confidence: 0.834, class_name: 'no-hardhat', violation: true },
  ],
  metadata: { source: 'store', display_name: 'Hard Hat', model_id: 'hard_hat' },
});
const VEST_EMPTY = entry('safety_vest', {
  violation_detected: false,
  objects: [],
  metadata: { source: 'store', display_name: 'Safety Vest' },
});
const FALL = entry('fall_detection', { violation_detected: false, detections: FALL_DETECTIONS });
const PPE = entry('ppe_detection', PPE_RAW as unknown as Record<string, unknown>);

describe('which entries become store overlays', () => {
  it('built-in results never do (same shared empty value)', () => {
    expect(storeOverlaysFrom([FALL, PPE])).toBe(NO_STORE_OVERLAYS);
    expect(storeOverlaysFrom([])).toBe(NO_STORE_OVERLAYS);
    expect(storeOverlaysFrom(undefined)).toBe(NO_STORE_OVERLAYS);
  });

  it('store results do, with their display name and frame size', () => {
    const out = storeOverlaysFrom([FALL, HARD_HAT, PPE, VEST_EMPTY]);
    expect(out.map((o) => [o.modelId, o.displayName, o.frameWidth, o.frameHeight, o.objects.length])).toEqual([
      ['hard_hat', 'Hard Hat', 1280, 720, 2],
      ['safety_vest', 'Safety Vest', 1280, 720, 0],
    ]);
  });

  it('respects enabledModels and skips results without frame size', () => {
    expect(storeOverlaysFrom([HARD_HAT, VEST_EMPTY], ['safety_vest']).map((o) => o.modelId)).toEqual(['safety_vest']);
    expect(storeOverlaysFrom([HARD_HAT], [])).toBe(NO_STORE_OVERLAYS);
    expect(storeOverlaysFrom([entry('hard_hat', HARD_HAT.result as Record<string, unknown>, false)])).toBe(
      NO_STORE_OVERLAYS
    );
  });
});

describe('drawing', () => {
  it('draws nothing when there is nothing to draw', () => {
    const { ctx, calls } = recordingContext();
    drawStoreDetections(ctx, NO_STORE_OVERLAYS, 640, 360);
    drawStoreDetections(ctx, storeOverlaysFrom([VEST_EMPTY]), 640, 360);
    expect(calls).toEqual([]);
  });

  it('box + label per object, red for violations, scaled from frame pixels', () => {
    const { ctx, calls } = recordingContext();
    drawStoreDetections(ctx, storeOverlaysFrom([HARD_HAT]), 640, 360);
    expect(calls).toEqual([
      // hardhat present: blue, label above the box (y 25 >= 18)
      ['set strokeStyle', STORE_OBJECT_COLOR],
      ['set lineWidth', 2],
      ['strokeRect', 50, 25, 30, 30],
      ['set font', 'bold 12px sans-serif'],
      ['measureText', 'Hard Hat · hardhat 91%'],
      ['set fillStyle', STORE_OBJECT_COLOR],
      ['fillRect', 50, 7, 'Hard Hat · hardhat 91%'.length * 7 + 8, 18],
      ['set fillStyle', '#ffffff'],
      ['fillText', 'Hard Hat · hardhat 91%', 54, 20],
      // no-hardhat: red, box top at y 5 < 18 so the label sits inside it
      ['set strokeStyle', STORE_VIOLATION_COLOR],
      ['set lineWidth', 2],
      ['strokeRect', 200, 5, 25, 30],
      ['set font', 'bold 12px sans-serif'],
      ['measureText', 'Hard Hat · no-hardhat 83%'],
      ['set fillStyle', STORE_VIOLATION_COLOR],
      ['fillRect', 200, 5, 'Hard Hat · no-hardhat 83%'.length * 7 + 8, 18],
      ['set fillStyle', '#ffffff'],
      ['fillText', 'Hard Hat · no-hardhat 83%', 204, 18],
    ]);
  });
});
