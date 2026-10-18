/**
 * Viewing Pane Layout — pure grid maths
 *
 * A layout is rows x columns, each 1..5. The 1/4/9/16 presets are simply the
 * square layouts 1x1..4x4; everything else (3x4, 2x5, 5x5, ...) is "custom".
 *
 * Slots are addressed by grid position ("row,col"), not by reading-order
 * index. That is what makes "shrink keeps the slots that remain" literally
 * true in both directions: dropping a column removes that column and nothing
 * else moves, the way deleting a column from a Word table does. A reading-
 * order index would shuffle cameras between rows whenever the column count
 * changed.
 */

export interface PaneLayout {
  rows: number;
  cols: number;
}

export const MAX_PANE_ROWS = 5;
export const MAX_PANE_COLS = 5;

/** The aspect every camera feed is laid out at. */
export const FEED_ASPECT = 16 / 9;

/** Tiles per side for the square presets. 1x1, 2x2, 3x3, 4x4 => 1, 4, 9, 16 tiles. */
export type PaneGridSize = 1 | 2 | 3 | 4;

export const PANE_GRID_SIZES: PaneGridSize[] = [1, 2, 3, 4];

export function getPaneTileCount(size: PaneGridSize): number {
  return size * size;
}

export function isValidLayout(value: unknown): value is PaneLayout {
  if (!value || typeof value !== 'object') return false;
  const { rows, cols } = value as Record<string, unknown>;
  return (
    Number.isInteger(rows) &&
    Number.isInteger(cols) &&
    (rows as number) >= 1 &&
    (rows as number) <= MAX_PANE_ROWS &&
    (cols as number) >= 1 &&
    (cols as number) <= MAX_PANE_COLS
  );
}

/** The preset a layout corresponds to, or null for a custom layout. */
export function presetSizeOf(layout: PaneLayout): PaneGridSize | null {
  if (layout.rows !== layout.cols) return null;
  return PANE_GRID_SIZES.includes(layout.rows as PaneGridSize)
    ? (layout.rows as PaneGridSize)
    : null;
}

export function layoutsEqual(a: PaneLayout, b: PaneLayout): boolean {
  return a.rows === b.rows && a.cols === b.cols;
}

export function cellKey(row: number, col: number): string {
  return `${row},${col}`;
}

/** Parse a "row,col" key; null for anything malformed or outside the 5x5 maximum. */
export function parseCellKey(key: string): { row: number; col: number } | null {
  const match = /^(\d+),(\d+)$/.exec(key);
  if (!match) return null;
  const row = Number(match[1]);
  const col = Number(match[2]);
  if (row >= MAX_PANE_ROWS || col >= MAX_PANE_COLS) return null;
  return { row, col };
}

/** Cell keys visible in a layout, in reading order (the order tiles render in). */
export function visibleCellKeys(layout: PaneLayout): string[] {
  const keys: string[] = [];
  for (let row = 0; row < layout.rows; row++) {
    for (let col = 0; col < layout.cols; col++) keys.push(cellKey(row, col));
  }
  return keys;
}

/**
 * The largest box at `aspect` that fits inside a tile — where the video and
 * its detection canvas live. Mirrors the CSS rule in ViewingPane.css
 * (width: min(100cqw, 100cqh * 16/9)), kept here so the maths is testable.
 */
export function containedBox(
  tileWidth: number,
  tileHeight: number,
  aspect: number = FEED_ASPECT
): { width: number; height: number } {
  const width = Math.min(tileWidth, tileHeight * aspect);
  return { width, height: width / aspect };
}

/**
 * Smallest layout that holds `count` cameras, or null when there is nothing
 * to fit.
 *
 * "Smallest" is judged by what the wall actually shows: the layout that gives
 * each camera the biggest picture wins, then the one with the fewest cells,
 * then (on a landscape screen) more columns, or on a portrait one more rows.
 * Fewest cells alone would pick 1 x 5 for five cameras: five 16:9 feeds
 * letterboxed into tall strips at a fraction of the size 2 x 3 gives them.
 *
 * On 16:9: 12 => 3x4 (3x4, 4x3 and 4x4 all give the same picture; 3x4 has
 * the fewest cells and more columns), 5 => 2x3, 7 => 3x3. Counts above 25
 * are capped at 5x5.
 */
export function fitLayout(count: number, viewportAspect: number = FEED_ASPECT): PaneLayout | null {
  if (!Number.isFinite(count) || count <= 0) return null;
  const needed = Math.min(Math.ceil(count), MAX_PANE_ROWS * MAX_PANE_COLS);
  const preferCols = viewportAspect >= 1;
  const EPS = 1e-9;

  let best: PaneLayout | null = null;
  let bestPicture = -Infinity;

  for (let rows = 1; rows <= MAX_PANE_ROWS; rows++) {
    for (let cols = 1; cols <= MAX_PANE_COLS; cols++) {
      if (rows * cols < needed) continue;
      // Picture width in a viewport of height 1; height follows at 16:9.
      const picture = containedBox(viewportAspect / cols, 1 / rows).width;

      let better: boolean;
      if (!best || picture > bestPicture + EPS) better = true;
      else if (picture < bestPicture - EPS) better = false;
      else if (rows * cols !== best.rows * best.cols) better = rows * cols < best.rows * best.cols;
      else better = preferCols ? cols > best.cols : rows > best.rows;

      if (better) {
        best = { rows, cols };
        bestPicture = picture;
      }
    }
  }
  return best;
}
