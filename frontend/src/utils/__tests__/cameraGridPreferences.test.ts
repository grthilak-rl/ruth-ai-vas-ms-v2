/**
 * Camera Monitoring grid persistence: a layout separate from the wall's,
 * position-keyed cells, and migration from the square-size + list model.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getGridCells,
  getGridLayout,
  seedGridCells,
  setGridCells,
  setGridLayout,
} from '../cameraGridPreferences';
import { getPaneLayout } from '../viewingPanePreferences';
import { visibleCameraIds } from '../viewingPaneLayout';

class MemoryStorage {
  private data = new Map<string, string>();
  getItem(key: string) {
    return this.data.has(key) ? this.data.get(key)! : null;
  }
  setItem(key: string, value: string) {
    this.data.set(key, String(value));
  }
  removeItem(key: string) {
    this.data.delete(key);
  }
}

let storage: MemoryStorage;

beforeEach(() => {
  storage = new MemoryStorage();
  vi.stubGlobal('localStorage', storage);
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('grid layout', () => {
  it('defaults to 2x2 and round-trips a custom layout', () => {
    expect(getGridLayout()).toEqual({ rows: 2, cols: 2 });
    setGridLayout({ rows: 3, cols: 4 });
    expect(getGridLayout()).toEqual({ rows: 3, cols: 4 });
  });

  it('falls back to the legacy square size (5x5 included), then to 2x2 on garbage', () => {
    storage.setItem('ruth-ai-camera-grid-size', '5');
    expect(getGridLayout()).toEqual({ rows: 5, cols: 5 });
    storage.setItem('ruth-ai-camera-grid-layout', '{"rows":0,"cols":3}');
    expect(getGridLayout()).toEqual({ rows: 5, cols: 5 });
    storage.setItem('ruth-ai-camera-grid-size', '9');
    expect(getGridLayout()).toEqual({ rows: 2, cols: 2 });
  });

  it('is a separate setting from the Viewing Pane layout', () => {
    setGridLayout({ rows: 3, cols: 4 });
    expect(getPaneLayout()).toEqual({ rows: 2, cols: 2 });
  });
});

describe('grid cells', () => {
  it('is null until positions are saved, then round-trips and sanitises', () => {
    expect(getGridCells()).toBeNull();
    setGridCells({ '0,0': 'a', '2,3': 'b' });
    expect(getGridCells()).toEqual({ '0,0': 'a', '2,3': 'b' });
    storage.setItem('ruth-ai-camera-grid-cells', '{"0,0":"a","7,7":"x"}');
    expect(getGridCells()).toEqual({ '0,0': 'a' });
  });

  it('survives storage that throws', () => {
    const boom = () => {
      throw new Error('SecurityError');
    };
    vi.stubGlobal('localStorage', { getItem: boom, setItem: boom });
    expect(getGridLayout()).toEqual({ rows: 2, cols: 2 });
    expect(getGridCells()).toBeNull();
    expect(() => setGridLayout({ rows: 3, cols: 4 })).not.toThrow();
    expect(() => setGridCells({})).not.toThrow();
  });
});

describe('seedGridCells (first run / pre-position migration)', () => {
  const list = ['cam1', 'cam2', 'cam3', 'cam4', 'cam5'];

  it('reproduces the old grid: selected cameras in camera-list order, reading order', () => {
    const cells = seedGridCells({ rows: 2, cols: 2 }, list, ['cam4', 'cam2']);
    expect(cells).toEqual({ '0,0': 'cam2', '0,1': 'cam4' });
  });

  it('keeps selected cameras that are missing from the list right now, after the rest', () => {
    const cells = seedGridCells({ rows: 2, cols: 2 }, list, ['gone', 'cam3']);
    expect(visibleCameraIds(cells, { rows: 2, cols: 2 })).toEqual(['cam3', 'gone']);
  });

  it('seeds the first cameras on first run, capped at the layout', () => {
    const cells = seedGridCells({ rows: 1, cols: 3 }, list, []);
    expect(cells).toEqual({ '0,0': 'cam1', '0,1': 'cam2', '0,2': 'cam3' });
  });
});
