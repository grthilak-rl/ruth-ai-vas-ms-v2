import { GRID_SIZES } from '../../utils/cameraGridPreferences';
import { type PaneLayout, FEED_ASPECT } from '../../utils/viewingPaneLayout';
import { GridLayoutPicker } from '../viewing-pane/GridLayoutPicker';
import './CameraGridSelector.css';

/**
 * CameraGridSelector Component
 *
 * Displays grid layout selector buttons (1×1 through 5×5), then a "Custom ▾"
 * rows × columns picker for anything else (3 × 4, 2 × 5, ...).
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
  layout: PaneLayout;
  onLayoutChange: (layout: PaneLayout) => void;
  /** Cameras on the grid, shown or parked — what Fit must hold. */
  fitCount: number;
  onFit: (layout: PaneLayout) => void;
}

export function CameraGridSelector({
  layout,
  onLayoutChange,
  fitCount,
  onFit,
}: CameraGridSelectorProps) {
  const currentSize = layout.rows === layout.cols ? layout.rows : null;

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
            onClick={() => onLayoutChange({ rows: size, cols: size })}
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
        {/* 5×5 is a preset here, unlike on the wall, so "custom" means any
            non-square layout. Fit assumes the feeds' 16:9 rather than this
            window's aspect, which shifts with browser chrome and panels. */}
        <GridLayoutPicker
          layout={layout}
          isCustom={currentSize === null}
          fitCount={fitCount}
          onSelect={onLayoutChange}
          onFit={onFit}
          viewportAspect={FEED_ASPECT}
          variant="light"
          align="start"
          triggerClassName="camera-grid-selector__button"
          triggerActiveClassName="camera-grid-selector__button--active"
        />
      </div>
    </div>
  );
}
