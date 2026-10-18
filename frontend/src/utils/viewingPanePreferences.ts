/**
 * Viewing Pane Preferences
 *
 * localStorage persistence for the wall display:
 * - layout (rows x columns; the 1 / 4 / 9 / 16 presets are the square ones)
 * - which camera occupies which grid position
 *
 * This is a fixed physical display. It is expected to come back from a power
 * cut showing exactly what it showed before, with nobody present to re-assign
 * tiles, so both live in localStorage rather than component state.
 *
 * Kept separate from cameraGridPreferences: the monitoring grid's selection is
 * "which cameras am I working with", while this is "what is bolted to the wall
 * in position 7". Changing one must not disturb the other.
 */

import {
  type CellAssignments,
  type PaneLayout,
  cellKey,
  isValidLayout,
  parseCellKey,
  PANE_GRID_SIZES,
  type PaneGridSize,
  sanitizeCellAssignments,
} from './viewingPaneLayout';

export {
  type CellAssignments,
  type PaneGridSize,
  type PaneLayout,
  PANE_GRID_SIZES,
  assignCell,
  getPaneTileCount,
  presetSizeOf,
} from './viewingPaneLayout';

const STORAGE_KEY_PANE_LAYOUT = 'ruth-ai-viewing-pane-layout';
const STORAGE_KEY_PANE_CELLS = 'ruth-ai-viewing-pane-cells';

// Pre-layout keys: a single preset size, and tiles keyed by reading-order
// index. Read only to carry an existing wall over unchanged.
const LEGACY_KEY_PANE_GRID_SIZE = 'ruth-ai-viewing-pane-grid-size';
const LEGACY_KEY_PANE_TILES = 'ruth-ai-viewing-pane-tiles';

const DEFAULT_PANE_GRID_SIZE: PaneGridSize = 2;

function readLegacyGridSize(): PaneGridSize {
  try {
    const saved = localStorage.getItem(LEGACY_KEY_PANE_GRID_SIZE);
    if (saved) {
      const parsed = parseInt(saved, 10);
      if (PANE_GRID_SIZES.includes(parsed as PaneGridSize)) return parsed as PaneGridSize;
    }
  } catch (error) {
    console.warn('[ViewingPane] Failed to read legacy grid size:', error);
  }
  return DEFAULT_PANE_GRID_SIZE;
}

export function getPaneLayout(): PaneLayout {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_PANE_LAYOUT);
    if (saved) {
      const parsed: unknown = JSON.parse(saved);
      if (isValidLayout(parsed)) return { rows: parsed.rows, cols: parsed.cols };
    }
  } catch (error) {
    console.warn('[ViewingPane] Failed to read layout:', error);
  }
  const size = readLegacyGridSize();
  return { rows: size, cols: size };
}

/**
 * Whether a `storage` event may have changed the layout. The wall usually
 * runs in a second window opened from Camera Monitoring, so this is how a
 * layout picked in one window reaches the other. A null key means storage
 * was cleared; the legacy key counts because getPaneLayout falls back to it.
 */
export function isPaneLayoutStorageKey(key: string | null): boolean {
  return key === null || key === STORAGE_KEY_PANE_LAYOUT || key === LEGACY_KEY_PANE_GRID_SIZE;
}

export function setPaneLayout(layout: PaneLayout): void {
  try {
    localStorage.setItem(
      STORAGE_KEY_PANE_LAYOUT,
      JSON.stringify({ rows: layout.rows, cols: layout.cols })
    );
  } catch (error) {
    console.warn('[ViewingPane] Failed to save layout:', error);
  }
}

/**
 * Carry a pre-layout wall over: reading-order index i on an N x N preset is
 * position (i / N, i % N). Indices beyond N x N were hidden leftovers from a
 * larger preset whose width is no longer known; any that fall outside the
 * 5x5 maximum are dropped.
 */
function readLegacyCells(): CellAssignments {
  try {
    const saved = localStorage.getItem(LEGACY_KEY_PANE_TILES);
    if (!saved) return {};
    const parsed: unknown = JSON.parse(saved);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};

    const size = readLegacyGridSize();
    const cells: CellAssignments = {};
    for (const [key, value] of Object.entries(parsed)) {
      const index = Number(key);
      if (!Number.isInteger(index) || index < 0 || typeof value !== 'string' || !value) continue;
      const k = cellKey(Math.floor(index / size), index % size);
      if (parseCellKey(k)) cells[k] = value;
    }
    return cells;
  } catch (error) {
    console.warn('[ViewingPane] Failed to read legacy tile assignments:', error);
    return {};
  }
}

export function getCellAssignments(): CellAssignments {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_PANE_CELLS);
    if (saved !== null) return sanitizeCellAssignments(JSON.parse(saved));
  } catch (error) {
    console.warn('[ViewingPane] Failed to read cell assignments:', error);
    return {};
  }
  return readLegacyCells();
}

export function setCellAssignments(cells: CellAssignments): void {
  try {
    localStorage.setItem(STORAGE_KEY_PANE_CELLS, JSON.stringify(cells));
  } catch (error) {
    console.warn('[ViewingPane] Failed to save cell assignments:', error);
  }
}
