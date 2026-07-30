/**
 * Camera Grid Preferences Utility
 *
 * Manages localStorage persistence for:
 * - Grid size preference (1x1 through 5x5)
 * - Selected cameras for the grid
 *
 * Per F7 specification:
 * - Grid size persists across sessions (localStorage)
 * - Selected cameras persist across sessions (localStorage)
 * - AI model toggles are session-scoped (not persisted)
 */

export type GridSize = 1 | 2 | 3 | 4 | 5;

const STORAGE_KEY_GRID_SIZE = 'ruth-ai-camera-grid-size';
const STORAGE_KEY_SELECTED_CAMERAS = 'ruth-ai-selected-cameras';
const DEFAULT_GRID_SIZE: GridSize = 2; // 2x2 grid as default per F7

/**
 * Get the saved grid size preference
 */
export function getGridSize(): GridSize {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_GRID_SIZE);
    if (saved) {
      const parsed = parseInt(saved, 10);
      if (parsed >= 1 && parsed <= 5) {
        return parsed as GridSize;
      }
    }
  } catch (error) {
    console.warn('[GridPreferences] Failed to read grid size:', error);
  }
  return DEFAULT_GRID_SIZE;
}

/**
 * Save grid size preference
 */
export function setGridSize(size: GridSize): void {
  try {
    localStorage.setItem(STORAGE_KEY_GRID_SIZE, size.toString());
  } catch (error) {
    console.warn('[GridPreferences] Failed to save grid size:', error);
  }
}

/**
 * Get the maximum number of cameras that can fit in the current grid
 */
export function getMaxCameras(gridSize: GridSize): number {
  return gridSize * gridSize;
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
 * Seed the camera selection when the operator hasn't made one yet.
 *
 * A saved selection is operator intent and is NEVER reconciled against the
 * currently-visible camera list. A camera can drop out of that list for
 * reasons that have nothing to do with the operator's choice — its stream is
 * down, VAS restarted (which resets every device's active flag), a sync
 * landed mid-flight — and pruning on that signal silently and permanently
 * forgets the selection, since the pruned result gets written back to
 * localStorage. Cameras that aren't currently available are filtered at
 * render time instead, so they return to the grid when they come back.
 */
export function autoSelectCameras(
  availableCameraIds: string[],
  currentGridSize: GridSize,
  currentSelectedIds: string[]
): string[] {
  const maxCameras = getMaxCameras(currentGridSize);

  // Existing selection: honour it as-is, trimmed only to what the grid holds.
  if (currentSelectedIds.length > 0) {
    return currentSelectedIds.slice(0, maxCameras);
  }

  // First run, or the operator cleared the selection: seed from what's available.
  return availableCameraIds.slice(0, maxCameras);
}