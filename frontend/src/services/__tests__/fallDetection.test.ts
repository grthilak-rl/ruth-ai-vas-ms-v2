/**
 * fall_pose (model store) replacing the built-in fall_detection on the
 * client-side fall path (bookmark monitoring): which model is asked, and
 * that a store pose result is drawn exactly like a built-in one.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DetectionEntry } from '../../state/api/detections.api';
import { fanOutDetections } from '../../components/video/detectionFanOut';
import { storeOverlaysFrom } from '../storeOverlay';
import {
  FALL_MODEL_ID,
  LEGACY_FALL_MODEL_ID,
  detectFall,
  fallDetectionsInModelSpace,
  isFallModel,
  isPersonFallen,
} from '../fallDetection';

const kp = (x: number, y: number, confidence = 0.9) => ({ x, y, confidence });

/** A person lying flat on a 1280x720 frame (frame pixels). */
const lyingFramePx = Array.from({ length: 17 }, (_, i) => kp(200 + 20 * i, 400));

const STORE_POSE_RESULT = {
  violation_detected: true,
  violation_type: 'fall_detected',
  severity: 'critical',
  confidence: 0.8,
  detection_count: 2,
  // only the person a rule fired on
  detections: [{ bbox: [180, 380, 560, 420], confidence: 0.6, score: 0.8, label: 'fall_detected' }],
  // every person, frame pixels, with keypoints
  objects: [
    { bbox: [180, 380, 560, 420], confidence: 0.6, class_name: 'person', violation: true, keypoints: lyingFramePx },
    { bbox: [900, 100, 960, 600], confidence: 0.9, class_name: 'person', violation: false, keypoints: [] },
  ],
  metadata: { source: 'store', task: 'pose', model_id: 'fall_pose', display_name: 'Fall Detection', frame_shape: [720, 1280, 3] },
};

describe('fall model ids', () => {
  it('fall_pose is the fall model; the built-in still counts while it is kept', () => {
    expect(FALL_MODEL_ID).toBe('fall_pose');
    expect(isFallModel('fall_pose')).toBe(true);
    expect(isFallModel(LEGACY_FALL_MODEL_ID)).toBe(true);
    expect(isFallModel('ppe_detection')).toBe(false);
    expect(isFallModel(null)).toBe(false);
  });
});

describe('fallDetectionsInModelSpace', () => {
  it('maps every store pose person from frame pixels to the 640x640 space', () => {
    const dets = fallDetectionsInModelSpace(STORE_POSE_RESULT);
    expect(dets).toHaveLength(2); // all persons, not just the firing one
    expect(dets[0].bbox).toEqual([90, (380 * 640) / 720, 280, (420 * 640) / 720]);
    expect(dets[0].keypoints[0]).toEqual({ x: 100, y: (400 * 640) / 720, confidence: 0.9 });
    expect(dets[0].confidence).toBe(0.6);
    expect(dets[1].keypoints).toEqual([]);
  });

  it('colours the mapped person exactly as the built-in overlay would', () => {
    const [lying] = fallDetectionsInModelSpace(STORE_POSE_RESULT);
    expect(isPersonFallen(lying)).toBe(true);
  });

  it('passes a built-in result (already 640 space) through untouched', () => {
    const builtin = {
      violation_detected: false,
      detections: [{ bbox: [1, 2, 3, 4], confidence: 0.5, keypoints: [kp(1, 2)] }],
    };
    expect(fallDetectionsInModelSpace(builtin)).toBe(builtin.detections);
    expect(fallDetectionsInModelSpace({})).toEqual([]);
  });
});

describe('detectFall', () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubBrowser(response: unknown) {
    class FakeReader {
      result: string | null = null;
      error = null;
      onloadend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      readAsDataURL() {
        this.result = 'data:image/jpeg;base64,QUJD';
        this.onloadend?.();
      }
    }
    vi.stubGlobal('FileReader', FakeReader);
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => response });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('asks fall_pose by default and returns persons in model space', async () => {
    const fetchMock = stubBrowser(STORE_POSE_RESULT);
    const out = await detectFall(new Blob(['x']), 1280, 720);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ model_id: 'fall_pose', frame: 'QUJD' });
    expect(out?.model).toBe('fall_pose');
    expect(out?.violation_detected).toBe(true);
    expect(out?.confidence).toBe(0.8);
    expect(out?.detections).toHaveLength(2);
  });

  it('can still ask the built-in model (rollback window)', async () => {
    const fetchMock = stubBrowser({ violation_detected: false, detections: [] });
    await detectFall(new Blob(['x']), 1280, 720, LEGACY_FALL_MODEL_ID);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).model_id).toBe('fall_detection');
  });
});

describe('live overlay for fall_pose', () => {
  const entry = {
    model_id: 'fall_pose',
    model_version: '1.0.0',
    result: STORE_POSE_RESULT,
    frame_width: 1280,
    frame_height: 720,
    age_ms: 100,
  } as unknown as DetectionEntry;

  it('is drawn by the generic store overlay, in frame pixels', () => {
    const overlays = storeOverlaysFrom([entry], ['fall_pose']);
    expect(overlays).toHaveLength(1);
    expect(overlays[0].displayName).toBe('Fall Detection');
    expect(overlays[0].objects.map((o) => o.violation)).toEqual([true, false]);
  });

  it('never reaches the built-in fall drawer, which assumes 640x640 boxes', () => {
    expect(fanOutDetections([entry]).fallDetection).toBeNull();
  });
});
