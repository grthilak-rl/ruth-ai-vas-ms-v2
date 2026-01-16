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
 * Auto-select cameras based on grid size
 * If no cameras are selected or grid size changed, auto-select the first N cameras
 */
export function autoSelectCameras(
  availableCameraIds: string[],
  currentGridSize: GridSize,
  currentSelectedIds: string[]
): string[] {
  const maxCameras = getMaxCameras(currentGridSize);

  // If we have selected cameras and they fit, keep them
  if (currentSelectedIds.length > 0 && currentSelectedIds.length <= maxCameras) {
    // Filter out any that are no longer available
    const validIds = currentSelectedIds.filter((id) => availableCameraIds.includes(id));
    if (validIds.length > 0) {
      return validIds;
    }
  }

  // Otherwise, auto-select first N available cameras
  return availableCameraIds.slice(0, maxCameras);
}