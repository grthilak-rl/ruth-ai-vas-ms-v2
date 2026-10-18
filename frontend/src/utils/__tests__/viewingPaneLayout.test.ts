/**
 * Viewing pane grid maths: Fit, tile aspect, letterbox box, cell keys.
 */

import { describe, expect, it } from 'vitest';
import {
  FEED_ASPECT,
  cellKey,
  containedBox,
  fitLayout,
  isValidLayout,
  parseCellKey,
  presetSizeOf,
  visibleCellKeys,
} from '../viewingPaneLayout';

describe('fitLayout', () => {
  it('returns null when there is nothing to fit', () => {
    expect(fitLayout(0)).toBeNull();
    expect(fitLayout(-3)).toBeNull();
    expect(fitLayout(Number.NaN)).toBeNull();
  });

  it.each([
    [1, 1, 1],
    [2, 1, 2],
    [3, 2, 2],
    [4, 2, 2],
    [5, 2, 3],
    [6, 2, 3],
    [7, 3, 3],
    [9, 3, 3],
    [10, 3, 4],
    [12, 3, 4],
    [13, 4, 4],
    [16, 4, 4],
    [20, 4, 5],
    [25, 5, 5],
  ])('%i cameras on 16:9 -> %i x %i', (count, rows, cols) => {
    expect(fitLayout(count, 16 / 9)).toEqual({ rows, cols });
  });

  it('caps at 5 x 5', () => {
    expect(fitLayout(40)).toEqual({ rows: 5, cols: 5 });
  });

  it('always holds the cameras, and no other layout that does gives a bigger picture', () => {
    const picture = (r: number, c: number) => containedBox(16 / 9 / c, 1 / r).width;
    for (let n = 1; n <= 25; n++) {
      const fit = fitLayout(n)!;
      expect(fit.rows * fit.cols).toBeGreaterThanOrEqual(n);
      for (let r = 1; r <= 5; r++) {
        for (let c = 1; c <= 5; c++) {
          if (r * c >= n) expect(picture(fit.rows, fit.cols)).toBeGreaterThanOrEqual(picture(r, c) - 1e-9);
        }
      }
    }
  });

  it('breaks picture-size ties by fewest cells (12 -> 3x4, not 4x4)', () => {
    const fit = fitLayout(12)!;
    expect(fit.rows * fit.cols).toBe(12);
  });

  it('prefers more rows on a portrait screen', () => {
    expect(fitLayout(12, 9 / 16)).toEqual({ rows: 4, cols: 3 });
  });
});

describe('containedBox (the 16:9 box inside a tile)', () => {
  it('square layouts on 16:9 fill their tile exactly; 3 x 4 tiles are 4:3', () => {
    for (const n of [1, 2, 3, 4, 5]) {
      const box = containedBox(1920 / n, 1080 / n);
      expect(box.width).toBeCloseTo(1920 / n, 9);
      expect(box.height).toBeCloseTo(1080 / n, 9);
    }
    expect(1920 / 4 / (1080 / 3)).toBeCloseTo(4 / 3, 10);
  });

  it('letterboxes top/bottom in a narrow tile, left/right in a wide one, never distorting', () => {
    // 3 x 4 on 1920x1080: 480 x 360 tiles
    const narrow = containedBox(480, 360);
    expect(narrow).toEqual({ width: 480, height: 270 });

    // 2 x 5 rotated: a wide tile
    const wide = containedBox(800, 300);
    expect(wide.height).toBe(300);
    expect(wide.width).toBeCloseTo(300 * FEED_ASPECT, 10);

    for (const box of [narrow, wide, containedBox(640, 360)]) {
      expect(box.width / box.height).toBeCloseTo(FEED_ASPECT, 10);
    }
  });

  it('fills a 16:9 tile exactly (presets: box == tile)', () => {
    expect(containedBox(480, 270)).toEqual({ width: 480, height: 270 });
  });
});

describe('cells and presets', () => {
  it('lists visible cells in reading order', () => {
    expect(visibleCellKeys({ rows: 2, cols: 3 })).toEqual(['0,0', '0,1', '0,2', '1,0', '1,1', '1,2']);
    expect(visibleCellKeys({ rows: 3, cols: 4 })).toHaveLength(12);
  });

  it('round-trips cell keys and rejects garbage or out-of-range keys', () => {
    expect(parseCellKey(cellKey(2, 3))).toEqual({ row: 2, col: 3 });
    expect(parseCellKey('5,0')).toBeNull();
    expect(parseCellKey('0,5')).toBeNull();
    expect(parseCellKey('7')).toBeNull();
    expect(parseCellKey('-1,0')).toBeNull();
    expect(parseCellKey('a,b')).toBeNull();
  });

  it('maps square 1..4 layouts to presets and everything else to custom', () => {
    expect(presetSizeOf({ rows: 3, cols: 3 })).toBe(3);
    expect(presetSizeOf({ rows: 1, cols: 1 })).toBe(1);
    expect(presetSizeOf({ rows: 3, cols: 4 })).toBeNull();
    expect(presetSizeOf({ rows: 5, cols: 5 })).toBeNull();
  });

  it('validates layouts', () => {
    expect(isValidLayout({ rows: 3, cols: 4 })).toBe(true);
    expect(isValidLayout({ rows: 0, cols: 4 })).toBe(false);
    expect(isValidLayout({ rows: 6, cols: 1 })).toBe(false);
    expect(isValidLayout({ rows: 2.5, cols: 2 })).toBe(false);
    expect(isValidLayout({ rows: '3', cols: 4 })).toBe(false);
    expect(isValidLayout(null)).toBe(false);
  });
});
