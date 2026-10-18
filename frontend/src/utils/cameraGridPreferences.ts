/**
 * Camera Grid Preferences Utility
 *
 * Manages localStorage persistence for:
 * - Grid layout (rows x columns; the 1x1..5x5 presets are the square ones)
 * - Which camera occupies which grid position
 * - Selected cameras (derived: the cameras the layout shows, reading order)
 * - Whether to show cameras disabled in VAS (off by default)
 *
 * Per F7 specification:
 * - Grid layout persists across sessions (localStorage)
 * - Selected cameras persist across sessions (localStorage)
 * - AI model toggles are session-scoped (not persisted)
 *
 * A separate setting from the Viewing Pane's layout: this is the operator's
 * working grid, that is the wall. The grid maths (layouts, Fit, position-keyed
 * slots) is shared via viewingPaneLayout.ts.
 */

import {
  type CellAssignments,
  type PaneLayout,
  applySelection,
  isValidLayout,
  sanitizeCellAssignments,
} from './viewingPaneLayout';

/** Tiles per side for the square presets. */
export type GridSize = 1 | 2 | 3 | 4 | 5;

export const GRID_SIZES: GridSize[] = [1, 2, 3, 4, 5];

const STORAGE_KEY_GRID_LAYOUT = 'ruth-ai-camera-grid-layout';
const STORAGE_KEY_GRID_CELLS = 'ruth-ai-camera-grid-cells';
const STORAGE_KEY_SELECTED_CAMERAS = 'ruth-ai-selected-cameras';
const STORAGE_KEY_SHOW_DISABLED = 'ruth-ai-show-disabled-cameras';
// Pre-layout key: a single square size. Read only to carry a grid over.
const LEGACY_KEY_GRID_SIZE = 'ruth-ai-camera-grid-size';
const DEFAULT_GRID_SIZE: GridSize = 2; // 2x2 grid as default per F7

/**
 * Whether camera lists should include cameras disabled in VAS.
 *
 * Defaults to false: a disabled camera is one an operator deliberately
 * retired (a finished campaign, a unit physically removed), and leaving
 * them in the grid makes the live cameras harder to find. Opt-in rather
 * than opt-out, and remembered per browser so nobody has to re-hide them
 * every morning.
 */
export function getShowDisabledCameras(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY_SHOW_DISABLED) === 'true';
  } catch (error) {
    console.warn('[GridPreferences] Failed to read show-disabled:', error);
    return false;
  }
}

export function setShowDisabledCameras(show: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY_SHOW_DISABLED, String(show));
  } catch (error) {
    console.warn('[GridPreferences] Failed to save show-disabled:', error);
  }
}

function readLegacyGridSize(): GridSize {
  try {
    const saved = localStorage.getItem(LEGACY_KEY_GRID_SIZE);
    if (saved) {
      const parsed = parseInt(saved, 10);
      if (parsed >= 1 && parsed <= 5) return parsed as GridSize;
    }
  } catch (error) {
    console.warn('[GridPreferences] Failed to read legacy grid size:', error);
  }
  return DEFAULT_GRID_SIZE;
}

/** The saved grid layout; falls back to the pre-layout square size, then 2x2. */
export function getGridLayout(): PaneLayout {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_GRID_LAYOUT);
    if (saved) {
      const parsed: unknown = JSON.parse(saved);
      if (isValidLayout(parsed)) return { rows: parsed.rows, cols: parsed.cols };
    }
  } catch (error) {
    console.warn('[GridPreferences] Failed to read grid layout:', error);
  }
  const size = readLegacyGridSize();
  return { rows: size, cols: size };
}

export function setGridLayout(layout: PaneLayout): void {
  try {
    localStorage.setItem(
      STORAGE_KEY_GRID_LAYOUT,
      JSON.stringify({ rows: layout.rows, cols: layout.cols })
    );
  } catch (error) {
    console.warn('[GridPreferences] Failed to save grid layout:', error);
  }
}

/**
 * Which camera is at which grid position, or null when no positions have been
 * saved yet (first run, or a browser from before positions existed). The
 * dashboard seeds those from the camera list — see seedGridCells — because
 * the order the old grid showed cameras in depends on that list.
 */
export function getGridCells(): CellAssignments | null {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_GRID_CELLS);
    if (saved !== null) return sanitizeCellAssignments(JSON.parse(saved));
  } catch (error) {
    console.warn('[GridPreferences] Failed to read grid cells:', error);
  }
  return null;
}

export function setGridCells(cells: CellAssignments): void {
  try {
    localStorage.setItem(STORAGE_KEY_GRID_CELLS, JSON.stringify(cells));
  } catch (error) {
    console.warn('[GridPreferences] Failed to save grid cells:', error);
  }
}

/**
 * Get the saved selected camera IDs
 */
export function getSelectedCameraIds(): string[] {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_SELECTED_CAMERAS);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed)) {
        return parsed.filter((id) => typeof id === 'string');
      }
    }
  } catch (error) {
    console.warn('[GridPreferences] Failed to read selected cameras:', error);
  }
  return [];
}

/**
 * Save selected camera IDs
 */
export function setSelectedCameraIds(ids: string[]): void {
  try {
    localStorage.setItem(STORAGE_KEY_SELECTED_CAMERAS, JSON.stringify(ids));
  } catch (error) {
    console.warn('[GridPreferences] Failed to save selected cameras:', error);
  }
}

/**
 * First positions for a grid with none saved.
 *
 * Reproduces what the grid showed before positions existed: the selected
 * cameras in camera-list order, reading order across the layout. Selected
 * cameras missing from the list right now (stream down, VAS restarting, a
 * sync mid-flight) are kept after them rather than dropped — a saved
 * selection is operator intent and is never pruned on availability; such a
 * tile renders empty and fills again when the camera returns. With no
 * selection at all (first run), the first cameras in the list are used.
 */
export function seedGridCells(
  layout: PaneLayout,
  cameraIds: string[],
  selectedIds: string[]
): CellAssignments {
  const ordered =
    selectedIds.length > 0
      ? [
          ...cameraIds.filter((id) => selectedIds.includes(id)),
          ...selectedIds.filter((id) => !cameraIds.includes(id)),
        ]
      : cameraIds;
  return applySelection({}, layout, ordered);
}
