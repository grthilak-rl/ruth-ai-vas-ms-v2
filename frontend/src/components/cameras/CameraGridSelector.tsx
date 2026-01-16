import type { GridSize } from '../../utils/cameraGridPreferences';
import './CameraGridSelector.css';

/**
 * CameraGridSelector Component
 *
 * Displays grid layout selector buttons (1×1 through 5×5).
 * Per F7 §4.2.1:
 * - Toggle buttons for grid size selection
 * - Current selection highlighted
 * - Clicking instantly reflows the grid
 * - Persists in localStorage per user
 *
 * Use Cases per F7:
 * - 1×1: Single camera focus / detailed investigation
 * - 2×2: Default operational view (4 cameras)
 * - 3×3: Medium-scale monitoring (9 cameras)
 * - 4×4: Large facility coverage (16 cameras)
 * - 5×5: Maximum density monitoring (25 cameras)
 */

interface CameraGridSelectorProps {
  currentSize: GridSize;
  onSizeChange: (size: GridSize) => void;
}

const GRID_SIZES: GridSize[] = [1, 2, 3, 4, 5];

export function CameraGridSelector({ currentSize, onSizeChange }: CameraGridSelectorProps) {
  return (
    <div className="camera-grid-selector">
      <span className="camera-grid-selector__label">Grid Layout:</span>
      <div className="camera-grid-selector__buttons" role="group" aria-label="Grid layout size">
        {GRID_SIZES.map((size) => (
          <button
            key={size}
            type="button"
            className={`camera-grid-selector__button ${
              size === currentSize ? 'camera-grid-selector__button--active' : ''
            }`}
            onClick={() => onSizeChange(size)}
            aria-label={`${size} by ${size} grid`}
            aria-pressed={size === currentSize}
          >
            {size}×{size}
            {size === currentSize && (
              <span className="camera-grid-selector__active-indicator" aria-hidden="true">
                {' '}
                ◉
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}