// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { detectWithStoreModel, storeOverlayFromResult } from '../storeDetection';

const STORE_RESULT = {
  violation_detected: true,
  violation_type: 'zone_intrusion',
  objects: [{ bbox: [10, 20, 110, 220], confidence: 0.91, class_name: 'person', violation: true }],
  metadata: { source: 'store', display_name: 'Geo-Fencing', frame_shape: [1080, 1920, 3] },
};

describe('storeOverlayFromResult', () => {
  it('turns a store result into an overlay in frame pixels', () => {
    expect(storeOverlayFromResult('geofence', STORE_RESULT)).toEqual({
      modelId: 'geofence',
      displayName: 'Geo-Fencing',
      frameWidth: 1920,
      frameHeight: 1080,
      objects: STORE_RESULT.objects,
    });
  });

  it('ignores results that are not store results, or have no frame size', () => {
    expect(storeOverlayFromResult('ppe_detection', { detections: [], metadata: {} })).toBeNull();
    expect(storeOverlayFromResult('hard_hat', { ...STORE_RESULT, metadata: { source: 'store' } })).toBeNull();
    expect(storeOverlayFromResult('hard_hat', null)).toBeNull();
  });

  it('falls back to the model id when there is no display name', () => {
    const r = { ...STORE_RESULT, metadata: { source: 'store', frame_shape: [720, 1280, 3] } };
    expect(storeOverlayFromResult('hard_hat', r)?.displayName).toBe('hard_hat');
  });
});

describe('detectWithStoreModel', () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubFetch(body: unknown, ok = true) {
    const fetchMock = vi.fn(async () => ({ ok, status: ok ? 200 : 500, statusText: '', json: async () => body }));
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('sends the model id and its zones, and returns the overlay', async () => {
    const fetchMock = stubFetch(STORE_RESULT);
    const zones = [{ id: 'zone_1', name: 'Z', type: 'restricted', coords: 'normalized' as const,
      points: [[0, 0.5], [1, 0.5], [1, 1], [0, 1]] }];
    const out = await detectWithStoreModel(new Blob(['x'], { type: 'image/jpeg' }), 'geofence', { zones });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/v1/ai/inference');
    const body = JSON.parse(init.body as string);
    expect(body.model_id).toBe('geofence');
    expect(body.config).toEqual({ zones });
    expect(typeof body.frame).toBe('string');
    expect(out?.violationType).toBe('zone_intrusion');
    expect(out?.overlay?.objects).toHaveLength(1);
  });

  it('sends no config for a model without one (PPE)', async () => {
    const fetchMock = stubFetch({ ...STORE_RESULT, violation_detected: false, violation_type: null });
    const out = await detectWithStoreModel(new Blob(['x']), 'hard_hat', null);
    const body = JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string);
    expect('config' in body).toBe(false);
    expect(out?.violationDetected).toBe(false);
  });

  it('returns null on an API error', async () => {
    stubFetch({}, false);
    expect(await detectWithStoreModel(new Blob(['x']), 'hard_hat', null)).toBeNull();
  });
});
