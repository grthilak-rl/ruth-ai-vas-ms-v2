import { useState, useRef, useEffect } from 'react';
import type { Device } from '../../state';
import type { GridSize } from '../../utils/cameraGridPreferences';
import { getMaxCameras } from '../../utils/cameraGridPreferences';
import './CameraSelectorDropdown.css';

/**
 * CameraSelectorDropdown Component
 *
 * Multi-select dropdown for choosing cameras to display in the grid.
 * Per F7 §4.2.2:
 * - Checkboxes for multi-select
 * - Shows camera name, status, and active AI models
 * - Maximum selection enforced based on current grid size
 * - Changes apply on "Apply" or when clicking outside
 * - Offline cameras can be selected (shows offline state in grid)
 */

interface CameraSelectorDropdownProps {
  cameras: Device[];
  selectedCameraIds: string[];
  gridSize: GridSize;
  onSelectionChange: (cameraIds: string[]) => void;
}

export function CameraSelectorDropdown({
  cameras,
  selectedCameraIds,
  gridSize,
  onSelectionChange,
}: CameraSelectorDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [tempSelection, setTempSelection] = useState<string[]>(selectedCameraIds);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const maxCameras = getMaxCameras(gridSize);

  // Update temp selection when props change
  useEffect(() => {
    setTempSelection(selectedCameraIds);
  }, [selectedCameraIds]);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        handleClose();
      }
    }

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
      };
    }
  }, [isOpen, tempSelection]);

  const handleToggleCamera = (cameraId: string) => {
    setTempSelection((prev) => {
      if (prev.includes(cameraId)) {
        // Remove camera
        return prev.filter((id) => id !== cameraId);
      } else {
        // Add camera (if under max)
        if (prev.length < maxCameras) {
          return [...prev, cameraId];
        }
        return prev;
      }
    });
  };

  const handleApply = () => {
    onSelectionChange(tempSelection);
    setIsOpen(false);
  };

  const handleClose = () => {
    // Apply changes on close
    if (JSON.stringify(tempSelection) !== JSON.stringify(selectedCameraIds)) {
      onSelectionChange(tempSelection);
    }
    setIsOpen(false);
  };

  const handleClearAll = () => {
    setTempSelection([]);
  };

  const getCameraStatus = (camera: Device): string => {
    return camera.is_active ? 'Live' : 'Offline';
  };

  const getCameraStatusIndicator = (camera: Device): string => {
    return camera.is_active ? '●' : '○';
  };

  return (
    <div className="camera-selector-dropdown" ref={dropdownRef}>
      <button
        type="button"
        className="camera-selector-dropdown__trigger"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-haspopup="true"
      >
        Camera Selector ▼
      </button>

      {isOpen && (
        <div className="camera-selector-dropdown__panel" role="dialog" aria-label="Select cameras">
          <div className="camera-selector-dropdown__header">
            <h3 className="camera-selector-dropdown__title">Camera Selector</h3>
            <button
              type="button"
              className="camera-selector-dropdown__close"
              onClick={() => setIsOpen(false)}
              aria-label="Close"
            >
              ✕
            </button>
          </div>

          <div className="camera-selector-dropdown__content">
            <div className="camera-selector-dropdown__section-title">
              AVAILABLE CAMERAS ({cameras.length})
            </div>

            <div className="camera-selector-dropdown__list">
              {cameras.map((camera) => {
                const isSelected = tempSelection.includes(camera.id);
                const isDisabled = !isSelected && tempSelection.length >= maxCameras;

                return (
                  <label
                    key={camera.id}
                    className={`camera-selector-dropdown__item ${
                      isDisabled ? 'camera-selector-dropdown__item--disabled' : ''
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => handleToggleCamera(camera.id)}
                      disabled={isDisabled}
                      className="camera-selector-dropdown__checkbox"
                    />
                    <span className="camera-selector-dropdown__item-name">{camera.name}</span>
                    <span
                      className={`camera-selector-dropdown__item-status ${
                        camera.is_active
                          ? 'camera-selector-dropdown__item-status--live'
                          : 'camera-selector-dropdown__item-status--offline'
                      }`}
                    >
                      {getCameraStatusIndicator(camera)} {getCameraStatus(camera)}
                    </span>
                  </label>
                );
              })}
            </div>

            <div className="camera-selector-dropdown__footer-info">
              Selected: {tempSelection.length} / {maxCameras} (max for {gridSize}×{gridSize} grid)
            </div>
          </div>

          <div className="camera-selector-dropdown__footer">
            <button
              type="button"
              className="camera-selector-dropdown__button camera-selector-dropdown__button--secondary"
              onClick={handleClearAll}
            >
              Clear All
            </button>
            <button
              type="button"
              className="camera-selector-dropdown__button camera-selector-dropdown__button--primary"
              onClick={handleApply}
            >
              Apply
            </button>
          </div>
        </div>
      )}
    </div>
  );
}