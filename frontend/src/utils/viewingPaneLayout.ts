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

// ============================================================================
// Position-keyed slot assignments
// ============================================================================
// Shared by the wall and the Camera Monitoring grid: both keep cameras by grid
// position and never trim on a layout change, so shrinking and growing back
// restores every camera to where it was.

/** "row,col" -> camera id. Sparse: gaps are empty tiles. */
export type CellAssignments = Record<string, string>;

/**
 * Rebuild rather than trust: a hand-edited or half-written value should
 * degrade to "some tiles empty", never to a crash on a display nobody is
 * watching.
 */
export function sanitizeCellAssignments(parsed: unknown): CellAssignments {
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
  const cells: CellAssignments = {};
  for (const [key, value] of Object.entries(parsed)) {
    if (parseCellKey(key) && typeof value === 'string' && value) cells[key] = value;
  }
  return cells;
}

/**
 * Assign a camera to a grid position, or clear it when cameraId is null.
 *
 * A camera may occupy only one position: assigning one that is already placed
 * moves it rather than duplicating it — including out of a position the
 * current layout hides. Two tiles of the same feed would mean two WebRTC
 * consumers decoding identical video for no benefit.
 */
export function assignCell(
  cells: CellAssignments,
  key: string,
  cameraId: string | null
): CellAssignments {
  const next: CellAssignments = { ...cells };

  if (cameraId) {
    for (const [k, value] of Object.entries(next)) {
      if (value === cameraId) delete next[k];
    }
    next[key] = cameraId;
  } else {
    delete next[key];
  }

  return next;
}

/** Cameras a layout shows, in reading order. */
export function visibleCameraIds(cells: CellAssignments, layout: PaneLayout): string[] {
  const ids: string[] = [];
  for (const key of visibleCellKeys(layout)) {
    if (cells[key]) ids.push(cells[key]);
  }
  return ids;
}

/**
 * Make the visible cameras match a list picked elsewhere (a checkbox list
 * rather than per-tile pickers).
 *
 * Visible cameras that are still wanted stay exactly where they are; ones no
 * longer wanted leave their tile empty; newly wanted ones fill the first free
 * visible tiles in list order (moved out of a hidden position if they were
 * parked in one). Anything beyond the free tiles is not placed. Hidden
 * positions are otherwise left alone, so they still come back on grow.
 */
export function applySelection(
  cells: CellAssignments,
  layout: PaneLayout,
  cameraIds: string[]
): CellAssignments {
  const keys = visibleCellKeys(layout);
  const wanted = new Set(cameraIds);
  let next: CellAssignments = { ...cells };

  for (const key of keys) {
    if (next[key] && !wanted.has(next[key])) delete next[key];
  }

  const onScreen = new Set(keys.map((key) => next[key]).filter(Boolean));
  const free = keys.filter((key) => !next[key]);
  for (const id of cameraIds) {
    if (onScreen.has(id)) continue;
    const key = free.shift();
    if (!key) break;
    next = assignCell(next, key, id);
    onScreen.add(id);
  }
  return next;
}

/**
 * Bring cameras parked outside a layout into its free tiles, in the reading
 * order of where they were. Visible cameras do not move. Used by Fit, whose
 * promise is that every camera ends up on screen.
 */
export function packIntoLayout(cells: CellAssignments, layout: PaneLayout): CellAssignments {
  const keys = visibleCellKeys(layout);
  const visible = new Set(keys);
  const free = keys.filter((key) => !cells[key]);

  const hidden = Object.keys(cells)
    .filter((key) => !visible.has(key))
    .map((key) => ({ key, pos: parseCellKey(key)! }))
    .sort((a, b) => a.pos.row - b.pos.row || a.pos.col - b.pos.col);

  let next: CellAssignments = { ...cells };
  for (const { key } of hidden) {
    const target = free.shift();
    if (!target) break;
    next = assignCell(next, target, cells[key]);
  }
  return next;
}
