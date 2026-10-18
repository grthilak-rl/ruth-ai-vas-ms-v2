/**
 * Viewing pane persistence: position-keyed slots survive layout changes,
 * legacy reading-order data migrates, and broken storage never throws.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  type CellAssignments,
  assignCell,
  getCellAssignments,
  getPaneLayout,
  isPaneLayoutStorageKey,
  setCellAssignments,
  setPaneLayout,
} from '../viewingPanePreferences';
import { visibleCellKeys } from '../viewingPaneLayout';

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
  clear() {
    this.data.clear();
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

/** What a layout actually shows: visible key -> camera. */
function visible(cells: CellAssignments, rows: number, cols: number) {
  return Object.fromEntries(
    visibleCellKeys({ rows, cols })
      .filter((k) => cells[k])
      .map((k) => [k, cells[k]])
  );
}

describe('slot preservation', () => {
  // A full 3 x 4 wall: camera "c<r><c>" at (r, c).
  const full34: CellAssignments = Object.fromEntries(
    visibleCellKeys({ rows: 3, cols: 4 }).map((k) => [k, `c${k.replace(',', '')}`])
  );

  it('shrinking keeps the remaining positions exactly (drops a column, nothing moves)', () => {
    expect(visible(full34, 3, 3)).toEqual({
      '0,0': 'c00', '0,1': 'c01', '0,2': 'c02',
      '1,0': 'c10', '1,1': 'c11', '1,2': 'c12',
      '2,0': 'c20', '2,1': 'c21', '2,2': 'c22',
    });
    expect(visible(full34, 2, 2)).toEqual({ '0,0': 'c00', '0,1': 'c01', '1,0': 'c10', '1,1': 'c11' });
  });

  it('presets use position too: 4x4 -> 2x2 keeps the top-left block', () => {
    const full44: CellAssignments = Object.fromEntries(
      visibleCellKeys({ rows: 4, cols: 4 }).map((k) => [k, `c${k.replace(',', '')}`])
    );
    expect(Object.values(visible(full44, 2, 2))).toEqual(['c00', 'c01', 'c10', 'c11']);
  });

  it('growing adds empty slots and leaves existing ones in place', () => {
    const small: CellAssignments = { '0,0': 'a', '1,1': 'b' };
    const shown = visible(small, 3, 4);
    expect(shown).toEqual({ '0,0': 'a', '1,1': 'b' });
    expect(visibleCellKeys({ rows: 3, cols: 4 }).filter((k) => !shown[k])).toHaveLength(10);
  });

  it('switching 3x4 -> 2x2 -> 3x4 through storage restores every camera', () => {
    setPaneLayout({ rows: 3, cols: 4 });
    setCellAssignments(full34);

    setPaneLayout({ rows: 2, cols: 2 });
    expect(getCellAssignments()).toEqual(full34);

    setPaneLayout({ rows: 3, cols: 4 });
    expect(getPaneLayout()).toEqual({ rows: 3, cols: 4 });
    expect(visible(getCellAssignments(), 3, 4)).toEqual(full34);
  });
});

describe('assignCell', () => {
  it('assigns and clears', () => {
    const a = assignCell({}, '0,1', 'cam');
    expect(a).toEqual({ '0,1': 'cam' });
    expect(assignCell(a, '0,1', null)).toEqual({});
  });

  it('moves a camera rather than duplicating it, including out of a hidden slot', () => {
    // (2,3) is hidden in a 2x2 layout; assigning the camera visibly moves it.
    const cells = { '2,3': 'cam', '0,0': 'other' };
    expect(assignCell(cells, '1,1', 'cam')).toEqual({ '0,0': 'other', '1,1': 'cam' });
  });

  it('does not mutate its input', () => {
    const cells = { '0,0': 'a' };
    assignCell(cells, '0,1', 'a');
    expect(cells).toEqual({ '0,0': 'a' });
  });
});

describe('layout persistence', () => {
  it('defaults to the 2x2 preset', () => {
    expect(getPaneLayout()).toEqual({ rows: 2, cols: 2 });
  });

  it('round-trips a custom layout', () => {
    setPaneLayout({ rows: 3, cols: 4 });
    expect(getPaneLayout()).toEqual({ rows: 3, cols: 4 });
  });

  it('falls back to the legacy preset key, then to the default on garbage', () => {
    storage.setItem('ruth-ai-viewing-pane-grid-size', '4');
    expect(getPaneLayout()).toEqual({ rows: 4, cols: 4 });

    storage.setItem('ruth-ai-viewing-pane-layout', '{"rows":9,"cols":1}');
    expect(getPaneLayout()).toEqual({ rows: 4, cols: 4 });

    storage.setItem('ruth-ai-viewing-pane-grid-size', '7');
    storage.setItem('ruth-ai-viewing-pane-layout', 'not json');
    expect(getPaneLayout()).toEqual({ rows: 2, cols: 2 });
  });
});

describe('cross-window sync', () => {
  it('reacts to layout keys (and storage.clear) but not to cell or unrelated keys', () => {
    expect(isPaneLayoutStorageKey('ruth-ai-viewing-pane-layout')).toBe(true);
    expect(isPaneLayoutStorageKey('ruth-ai-viewing-pane-grid-size')).toBe(true);
    expect(isPaneLayoutStorageKey(null)).toBe(true);
    expect(isPaneLayoutStorageKey('ruth-ai-viewing-pane-cells')).toBe(false);
    expect(isPaneLayoutStorageKey('ruth-ai-camera-grid-size')).toBe(false);
  });

  it('a layout written by one window is what the other reads back', () => {
    setPaneLayout({ rows: 2, cols: 5 });
    expect(getPaneLayout()).toEqual({ rows: 2, cols: 5 });
  });
});

describe('legacy migration', () => {
  it('maps reading-order indices on an N x N preset to positions', () => {
    storage.setItem('ruth-ai-viewing-pane-grid-size', '3');
    storage.setItem('ruth-ai-viewing-pane-tiles', JSON.stringify({ 0: 'a', 4: 'b', 8: 'c', 5: 'd' }));
    expect(getCellAssignments()).toEqual({ '0,0': 'a', '1,1': 'b', '2,2': 'c', '1,2': 'd' });
  });

  it('drops leftovers that land outside 5x5 and junk entries', () => {
    storage.setItem('ruth-ai-viewing-pane-grid-size', '2');
    storage.setItem(
      'ruth-ai-viewing-pane-tiles',
      JSON.stringify({ 1: 'a', 9: 'b', 12: 'gone', x: 'junk', 2: '' })
    );
    expect(getCellAssignments()).toEqual({ '0,1': 'a', '4,1': 'b' });
  });

  it('prefers the new key once written', () => {
    storage.setItem('ruth-ai-viewing-pane-tiles', JSON.stringify({ 0: 'old' }));
    setCellAssignments({ '1,0': 'new' });
    expect(getCellAssignments()).toEqual({ '1,0': 'new' });
  });

  it('sanitises hand-edited cell data', () => {
    storage.setItem(
      'ruth-ai-viewing-pane-cells',
      JSON.stringify({ '0,0': 'ok', '9,9': 'out', '1': 'bad', '0,1': 5, '0,2': '' })
    );
    expect(getCellAssignments()).toEqual({ '0,0': 'ok' });
  });
});

describe('storage that throws', () => {
  beforeEach(() => {
    const boom = () => {
      throw new Error('SecurityError');
    };
    vi.stubGlobal('localStorage', { getItem: boom, setItem: boom, removeItem: boom });
  });

  it('reads degrade to defaults and writes are swallowed', () => {
    expect(getPaneLayout()).toEqual({ rows: 2, cols: 2 });
    expect(getCellAssignments()).toEqual({});
    expect(() => setPaneLayout({ rows: 3, cols: 4 })).not.toThrow();
    expect(() => setCellAssignments({ '0,0': 'a' })).not.toThrow();
  });
});
