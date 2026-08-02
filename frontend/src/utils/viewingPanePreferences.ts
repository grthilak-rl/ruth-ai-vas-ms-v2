/**
 * Viewing Pane Preferences
 *
 * localStorage persistence for the wall display:
 * - tile count (1 / 4 / 9 / 16)
 * - which camera occupies which tile
 *
 * This is a fixed physical display. It is expected to come back from a power
 * cut showing exactly what it showed before, with nobody present to re-assign
 * tiles, so both live in localStorage rather than component state.
 *
 * Kept separate from cameraGridPreferences: the monitoring grid's selection is
 * "which cameras am I working with", while this is "what is bolted to the wall
 * in position 7". Changing one must not disturb the other.
 */

/** Tiles per side. 1x1, 2x2, 3x3, 4x4 => 1, 4, 9, 16 tiles. */
export type PaneGridSize = 1 | 2 | 3 | 4;

export const PANE_GRID_SIZES: PaneGridSize[] = [1, 2, 3, 4];

const STORAGE_KEY_PANE_GRID_SIZE = 'ruth-ai-viewing-pane-grid-size';
const STORAGE_KEY_PANE_TILES = 'ruth-ai-viewing-pane-tiles';

const DEFAULT_PANE_GRID_SIZE: PaneGridSize = 2;

/** Tile index (0-based, row-major) -> camera id. Sparse: gaps are empty tiles. */
export type TileAssignments = Record<number, string>;

export function getPaneTileCount(size: PaneGridSize): number {
  return size * size;
}

export function getPaneGridSize(): PaneGridSize {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_PANE_GRID_SIZE);
    if (saved) {
      const parsed = parseInt(saved, 10);
      if (PANE_GRID_SIZES.includes(parsed as PaneGridSize)) {
        return parsed as PaneGridSize;
      }
    }
  } catch (error) {
    console.warn('[ViewingPane] Failed to read grid size:', error);
  }
  return DEFAULT_PANE_GRID_SIZE;
}

export function setPaneGridSize(size: PaneGridSize): void {
  try {
    localStorage.setItem(STORAGE_KEY_PANE_GRID_SIZE, String(size));
  } catch (error) {
    console.warn('[ViewingPane] Failed to save grid size:', error);
  }
}

export function getTileAssignments(): TileAssignments {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_PANE_TILES);
    if (!saved) return {};

    const parsed = JSON.parse(saved);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};

    // Rebuild rather than trust: a hand-edited or half-written value should
    // degrade to "some tiles empty", never to a crash on a display nobody is
    // watching.
    const assignments: TileAssignments = {};
    for (const [key, value] of Object.entries(parsed)) {
      const index = Number(key);
      if (Number.isInteger(index) && index >= 0 && typeof value === 'string' && value) {
        assignments[index] = value;
      }
    }
    return assignments;
  } catch (error) {
    console.warn('[ViewingPane] Failed to read tile assignments:', error);
    return {};
  }
}

export function setTileAssignments(assignments: TileAssignments): void {
  try {
    localStorage.setItem(STORAGE_KEY_PANE_TILES, JSON.stringify(assignments));
  } catch (error) {
    console.warn('[ViewingPane] Failed to save tile assignments:', error);
  }
}

/**
 * Assign a camera to a tile, or clear the tile when cameraId is null.
 *
 * A camera may occupy only one tile: assigning one that is already placed
 * moves it rather than duplicating it. Two tiles of the same feed would mean
 * two WebRTC consumers decoding identical video for no benefit, and on a wall
 * whose whole purpose is "see everything at once" a duplicate is a blind spot.
 */
export function assignTile(
  assignments: TileAssignments,
  tileIndex: number,
  cameraId: string | null
): TileAssignments {
  const next: TileAssignments = { ...assignments };

  if (cameraId) {
    for (const [key, value] of Object.entries(next)) {
      if (value === cameraId) delete next[Number(key)];
    }
    next[tileIndex] = cameraId;
  } else {
    delete next[tileIndex];
  }

  return next;
}

/**
 * Drop assignments that fall outside the current grid.
 *
 * Only applied when the operator actually shrinks the grid — never on load —
 * so a 4x4 wall that is temporarily viewed at 2x2 does not silently lose the
 * other twelve assignments.
 */
export function trimAssignmentsToGrid(
  assignments: TileAssignments,
  size: PaneGridSize
): TileAssignments {
  const capacity = getPaneTileCount(size);
  const next: TileAssignments = {};
  for (const [key, value] of Object.entries(assignments)) {
    const index = Number(key);
    if (index < capacity) next[index] = value;
  }
  return next;
}
