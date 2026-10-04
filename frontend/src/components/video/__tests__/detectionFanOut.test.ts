/**
 * fanOutDetections: one entry fills its slot exactly as the pre-M2
 * single-result switch in LiveVideoPlayer did; several entries fill several
 * slots; enabledModels filters.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { FallDetectionResult } from '../../../services/fallDetection';
import {
  type PPEDetectionResult,
  type RawUnifiedPPEResponse,
  transformAPIResponse as transformPPEResponse,
} from '../../../services/ppeDetection';
import type { TankDetectionResult } from '../../../services/tankDetection';
import type { ChaneTankResult } from '../../../services/chaneTankMonitor';
import type { DetectionEntry } from '../../../state/api/detections.api';
import { EMPTY_FAN_OUT, fanOutDetections } from '../detectionFanOut';
import { FALL_DETECTIONS, FIXED_NOW, FRAME_HEIGHT, FRAME_WIDTH, PPE_RAW } from './overlaySupport';

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(FIXED_NOW);
});
afterEach(() => {
  vi.useRealTimers();
});

/**
 * The useMemo body of LiveVideoPlayer before M2, copied verbatim (comments
 * trimmed), with `detection` as the parameter.
 */
function legacyFanOut(detection: DetectionEntry | null | undefined) {
  const empty = {
    fallDetection: null as FallDetectionResult | null,
    ppeDetection: null as PPEDetectionResult | null,
    tankDetection: null as TankDetectionResult | null,
    chaneTankDetection: null as ChaneTankResult | null,
  };
  if (!detection?.result) return empty;

  const raw = detection.result as Record<string, unknown>;
  const frameWidth = detection.frame_width ?? undefined;
  const frameHeight = detection.frame_height ?? undefined;

  switch (detection.model_id) {
    case 'fall_detection':
      return {
        ...empty,
        fallDetection: {
          ...(raw as unknown as FallDetectionResult),
          detections: (raw.detections as FallDetectionResult['detections']) ?? [],
          confidence: (raw.confidence as number) ?? 0,
          videoWidth: frameWidth,
          videoHeight: frameHeight,
        },
      };
    case 'ppe_detection':
      return {
        ...empty,
        ppeDetection: transformPPEResponse(
          raw as unknown as RawUnifiedPPEResponse,
          'full',
          frameWidth,
          frameHeight
        ),
      };
    case 'tank_overflow_monitoring':
      return { ...empty, tankDetection: raw as unknown as TankDetectionResult };
    case 'chane_tank_monitor':
      return { ...empty, chaneTankDetection: raw as unknown as ChaneTankResult };
    default:
      return empty;
  }
}

function entry(model_id: string, result: Record<string, unknown> | null, dims = true): DetectionEntry {
  return {
    model_id,
    model_version: '1.0.0',
    result,
    frame_width: dims ? FRAME_WIDTH : null,
    frame_height: dims ? FRAME_HEIGHT : null,
    age_ms: 120,
  } as unknown as DetectionEntry;
}

const FALL = entry('fall_detection', { violation_detected: true, confidence: 0.9, detections: FALL_DETECTIONS });
const FALL_BARE = entry('fall_detection', { violation_detected: false }, false);
const PPE = entry('ppe_detection', PPE_RAW as unknown as Record<string, unknown>);
const PPE_EMPTY = entry('ppe_detection', { violation_detected: false }, false);
const TANK = entry('tank_overflow_monitoring', { level_percent: 72, severity: 'warning', detections: [] });
const CHANE = entry('chane_tank_monitor', { fill_percentage: 40, status: 'ok' });
const GEO = entry('geo_fencing', { detections: [{ bbox: [1, 2, 3, 4] }] });
const NO_RESULT = entry('fall_detection', null);

const SINGLE_CASES: Array<[string, DetectionEntry]> = [
  ['fall', FALL],
  ['fall without detections/confidence/frame dims', FALL_BARE],
  ['ppe', PPE],
  ['ppe with nothing seen and no frame dims', PPE_EMPTY],
  ['tank', TANK],
  ['chane', CHANE],
  ['model without drawing code', GEO],
  ['entry without a result', NO_RESULT],
];

describe('single model: identical to the pre-M2 fan-out', () => {
  it.each(SINGLE_CASES)('%s', (_name, e) => {
    expect(fanOutDetections([e])).toEqual(legacyFanOut(e));
    // and when the page passes the camera's one model as enabledModels
    expect(fanOutDetections([e], [e.model_id])).toEqual(legacyFanOut(e));
  });

  it('no results', () => {
    expect(fanOutDetections([])).toEqual(legacyFanOut(null));
    expect(fanOutDetections(undefined)).toEqual(legacyFanOut(undefined));
    expect(fanOutDetections(null)).toBe(EMPTY_FAN_OUT);
  });
});

describe('several models', () => {
  it('fills one slot per model, each as it would be alone', () => {
    const out = fanOutDetections([FALL, PPE, TANK, CHANE, GEO]);
    expect(out).toEqual({
      fallDetection: legacyFanOut(FALL).fallDetection,
      ppeDetection: legacyFanOut(PPE).ppeDetection,
      tankDetection: legacyFanOut(TANK).tankDetection,
      chaneTankDetection: legacyFanOut(CHANE).chaneTankDetection,
    });
  });

  it('order of entries does not matter', () => {
    expect(fanOutDetections([PPE, FALL])).toEqual(fanOutDetections([FALL, PPE]));
  });

  it('an entry without a result leaves the other slots alone', () => {
    const out = fanOutDetections([PPE, entry('fall_detection', null)]);
    expect(out.fallDetection).toBeNull();
    expect(out.ppeDetection).toEqual(legacyFanOut(PPE).ppeDetection);
  });
});

describe('enabledModels', () => {
  it('drops models the camera is not running', () => {
    const out = fanOutDetections([FALL, PPE, TANK], ['ppe_detection']);
    expect(out).toEqual({ ...EMPTY_FAN_OUT, ppeDetection: legacyFanOut(PPE).ppeDetection });
  });

  it('an empty list draws nothing', () => {
    expect(fanOutDetections([FALL, PPE], [])).toEqual(EMPTY_FAN_OUT);
  });

  it('omitted or null draws everything returned (fullscreen, camera detail)', () => {
    const all = fanOutDetections([FALL, PPE]);
    expect(fanOutDetections([FALL, PPE], null)).toEqual(all);
    expect(all.fallDetection).not.toBeNull();
    expect(all.ppeDetection).not.toBeNull();
  });

  it('never mutates the shared empty result', () => {
    fanOutDetections([FALL]);
    expect(EMPTY_FAN_OUT).toEqual({
      fallDetection: null,
      ppeDetection: null,
      tankDetection: null,
      chaneTankDetection: null,
    });
    expect(Object.isFrozen(EMPTY_FAN_OUT)).toBe(true);
  });
});
