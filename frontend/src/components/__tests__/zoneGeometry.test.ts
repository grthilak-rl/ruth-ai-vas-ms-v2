import { describe, expect, it } from 'vitest';

import {
  buildZone,
  isAxisAlignedRectangle,
  modeFor,
  normalizePoints,
  readInitialConfig,
  zonePointsInImage,
  zonePointsOnCanvas,
  zonesForModels,
} from '../zoneGeometry';
import type { ZoneConfig } from '../../types/geofencing';

const RECT = [
  { x: 100, y: 200 }, { x: 900, y: 200 }, { x: 900, y: 700 }, { x: 100, y: 700 },
];

describe('normalised zones', () => {
  it('normalises to fractions of the image and back to the same pixels', () => {
    const pts = [{ x: 0, y: 0 }, { x: 1919, y: 0 }, { x: 1234, y: 1079 }, { x: 7, y: 543 }];
    for (const [w, h] of [[1920, 1080], [2688, 1520], [1280, 720]]) {
      const scaled = pts.map((p) => ({ x: Math.round((p.x / 1920) * w), y: Math.round((p.y / 1080) * h) }));
      const zone: ZoneConfig = {
        id: 'z', name: 'Z', type: 'restricted', coords: 'normalized',
        points: normalizePoints(scaled, w, h),
      };
      expect(zonePointsInImage(zone, w, h)).toEqual(scaled);
      for (const [x, y] of zone.points) {
        expect(x).toBeGreaterThanOrEqual(0);
        expect(x).toBeLessThanOrEqual(1);
        expect(y).toBeGreaterThanOrEqual(0);
        expect(y).toBeLessThanOrEqual(1);
      }
    }
  });

  it('places a zone drawn on a 1920x1080 snapshot at the same spot on 2688x1520 frames', () => {
    const zone = buildZone(RECT, 'Z', 'restricted', { width: 1920, height: 1080 })!;
    const onBigFrame = zonePointsInImage(zone, 2688, 1520);
    expect(onBigFrame[0]).toEqual({ x: Math.round((100 / 1920) * 2688), y: Math.round((200 / 1080) * 1520) });
  });

  it('pixel zones (the built-in format) are passed through', () => {
    const zone: ZoneConfig = { id: 'z', name: 'Z', type: 'restricted', points: [[10, 20], [30, 40], [50, 60]] };
    expect(zonePointsInImage(zone, 1920, 1080)).toEqual([{ x: 10, y: 20 }, { x: 30, y: 40 }, { x: 50, y: 60 }]);
  });
});

describe('zonePointsOnCanvas', () => {
  it('scales a normalised zone straight to the canvas', () => {
    const zone: ZoneConfig = { id: 'z', name: 'Z', type: 'restricted', coords: 'normalized',
      points: [[0.5, 0.25], [1, 1], [0, 1]] };
    expect(zonePointsOnCanvas(zone, 1920, 1080, 400, 300)[0]).toEqual({ x: 200, y: 75 });
  });

  it('scales a pixel zone relative to the video size, as before', () => {
    const zone: ZoneConfig = { id: 'z', name: 'Z', type: 'restricted', points: [[960, 540], [0, 0], [1920, 0]] };
    expect(zonePointsOnCanvas(zone, 1920, 1080, 400, 300)[0]).toEqual({ x: 200, y: 150 });
  });
});

describe('the editor', () => {
  it('saves store-model zones normalised and built-in zones in pixels', () => {
    expect(buildZone(RECT, 'Gate', 'allowed', { width: 1000, height: 1000 })).toEqual({
      id: 'zone_1', name: 'Gate', type: 'allowed', coords: 'normalized',
      points: [[0.1, 0.2], [0.9, 0.2], [0.9, 0.7], [0.1, 0.7]],
    });
    expect(buildZone(RECT, 'Gate', 'restricted')).toEqual({
      id: 'zone_1', name: 'Gate', type: 'restricted',
      points: [[100, 200], [900, 200], [900, 700], [100, 700]],
    });
  });

  it('refuses to save a normalised zone before the image size is known', () => {
    expect(buildZone(RECT, 'Gate', 'restricted', null)).toBeNull();
  });

  it('reopens a rectangle in rectangle mode and any other shape in manual mode (BL-6)', () => {
    expect(isAxisAlignedRectangle(RECT)).toBe(true);
    expect(modeFor(RECT)).toBe('rectangle');
    const skewed = [{ x: 100, y: 200 }, { x: 900, y: 210 }, { x: 900, y: 700 }, { x: 100, y: 700 }];
    expect(modeFor(skewed)).toBe('manual');
    expect(modeFor([])).toBe('rectangle');
    // Same corners, wrong order: not what the rectangle tool saves.
    expect(isAxisAlignedRectangle([RECT[0], RECT[3], RECT[2], RECT[1]])).toBe(false);
  });

  it('reads a saved normalised zone as pending until the image size is known', () => {
    const zone = buildZone(RECT, 'Gate', 'allowed', { width: 1920, height: 1080 })!;
    const init = readInitialConfig({ zones: [zone] });
    expect(init.corners).toEqual([]);
    expect(init.pendingZone).toEqual(zone);
    expect(init.zoneName).toBe('Gate');
    expect(init.zoneType).toBe('allowed');
    expect(zonePointsInImage(init.pendingZone!, 1920, 1080)).toEqual(RECT);
  });

  it('reads saved pixel zones and tank corners straight into corners', () => {
    expect(readInitialConfig({ zones: [buildZone(RECT, 'G', 'restricted')!] }).corners).toEqual(RECT);
    const tank = readInitialConfig({ tank_corners: [[1, 2], [3, 4], [5, 6], [7, 8]], capacity_liters: 500 });
    expect(tank.corners).toHaveLength(4);
    expect(tank.capacityLiters).toBe(500);
    expect(readInitialConfig(undefined).corners).toEqual([]);
  });
});

describe('zonesForModels', () => {
  it('collects the zones of every running model, whatever its id', () => {
    const a = buildZone(RECT, 'A', 'restricted', { width: 1920, height: 1080 })!;
    const b = buildZone(RECT, 'B', 'restricted')!;
    const configs = { geofence: { zones: [a] }, geo_fencing: { zones: [b] }, hard_hat: {} };
    expect(zonesForModels(configs, ['geofence', 'hard_hat'])).toEqual([a]);
    expect(zonesForModels(configs, ['geofence', 'geo_fencing'])).toEqual([a, b]);
    expect(zonesForModels(configs, [])).toEqual([]);
  });

  it('skips zones with fewer than 3 points', () => {
    const bad = { id: 'z', name: 'Z', type: 'restricted', points: [[1, 2], [3, 4]] };
    expect(zonesForModels({ m: { zones: [bad] } }, ['m'])).toEqual([]);
  });
});
