import { useState, useRef, useEffect } from 'react';
import type { Device } from '../../state';
import { useDeviceSync } from '../../state/hooks/useDeviceSync';
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
 *
 * Device freshness: Ruth's device table is a cache of VAS's. Opening this
 * dropdown triggers a background sync from VAS (throttled, see
 * useDeviceSync) so cameras added in the VAS admin portal show up without a
 * ruth-ai-backend restart. The panel never waits on that sync — it opens
 * with the known list and updates in place when the sync lands.
 */

interface CameraSelectorDropdownProps {
  cameras: Device[];
  selectedCameraIds: string[];
  /** Tiles the grid shows: the most cameras that can be selected. */
  maxCameras: number;
  /** The grid's layout for the footer, e.g. "3×4". */
  layoutLabel: string;
  onSelectionChange: (cameraIds: string[]) => void;
}

import { pruneSelection, isGridFull } from './pruneSelection';

export function CameraSelectorDropdown({
  cameras,
  selectedCameraIds,
  maxCameras,
  layoutLabel,
  onSelectionChange,
}: CameraSelectorDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [tempSelection, setTempSelection] = useState<string[]>(() =>
    pruneSelection(selectedCameraIds, cameras)
  );
  const dropdownRef = useRef<HTMLDivElement>(null);
  const { syncNow, isSyncing, lastSyncFailed } = useDeviceSync();

  // Update temp selection when props change. Pruned against the camera
  // list: an id for a camera that is no longer listed must not hold a
  // grid slot, which is what blocked adding a twelfth camera while a
  // decommissioned one still counted.
  useEffect(() => {
    setTempSelection(pruneSelection(selectedCameraIds, cameras));
  }, [selectedCameraIds, cameras]);

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

  const gridFull = isGridFull(tempSelection, maxCameras);

  const handleToggleOpen = () => {
    if (isOpen) {
      setIsOpen(false);
      return;
    }

    // Open first, sync second: the panel must not wait on VAS. The device
    // list updates in place if the sync turns up anything new. Throttled,
    // so repeated open/close doesn't hammer VAS.
    setIsOpen(true);
    void syncNow();
  };

  const handleRefresh = () => {
    // Manual refresh bypasses the throttle — the operator just added a
    // camera in VAS and is asking for it now.
    void syncNow(true);
  };

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
    // Prune on the way out too, so a stale id cannot be written back even
    // if it was already persisted before this fix.
    onSelectionChange(pruneSelection(tempSelection, cameras));
    setIsOpen(false);
  };

  const handleClose = () => {
    // Apply changes on close
    const pruned = pruneSelection(tempSelection, cameras);
    if (JSON.stringify(pruned) !== JSON.stringify(selectedCameraIds)) {
      onSelectionChange(pruned);
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
        onClick={handleToggleOpen}
        aria-expanded={isOpen}
        aria-haspopup="true"
      >
        Camera Selector ▼
      </button>

      {isOpen && (
        <div className="camera-selector-dropdown__panel" role="dialog" aria-label="Select cameras">
          <div className="camera-selector-dropdown__header">
            <h3 className="camera-selector-dropdown__title">Camera Selector</h3>
            <div className="camera-selector-dropdown__header-actions">
              <button
                type="button"
                className="camera-selector-dropdown__refresh"
                onClick={handleRefresh}
                disabled={isSyncing}
                aria-label="Refresh cameras from VAS"
                title="Refresh cameras from VAS"
              >
                <span
                  className={`camera-selector-dropdown__refresh-icon ${
                    isSyncing ? 'camera-selector-dropdown__refresh-icon--spinning' : ''
                  }`}
                  aria-hidden="true"
                >
                  ⟳
                </span>
                {isSyncing ? 'Refreshing…' : 'Refresh'}
              </button>
              <button
                type="button"
                className="camera-selector-dropdown__close"
                onClick={() => setIsOpen(false)}
                aria-label="Close"
              >
                ✕
              </button>
            </div>
          </div>

          <div className="camera-selector-dropdown__content">
            <div className="camera-selector-dropdown__section-title">
              <span>AVAILABLE CAMERAS ({cameras.length})</span>
              {isSyncing && (
                <span
                  className="camera-selector-dropdown__sync-status"
                  role="status"
                  aria-live="polite"
                >
                  Refreshing…
                </span>
              )}
              {!isSyncing && lastSyncFailed && (
                <span
                  className="camera-selector-dropdown__sync-status camera-selector-dropdown__sync-status--failed"
                  role="status"
                  aria-live="polite"
                  title="Could not reach VAS. Showing the last known camera list."
                >
                  ⚠ Couldn’t refresh
                </span>
              )}
            </div>

            <div className="camera-selector-dropdown__list">
              {cameras.map((camera) => {
                const isSelected = tempSelection.includes(camera.id);
                const isDisabled = !isSelected && gridFull;

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
              Selected: {tempSelection.length} / {maxCameras} (max for {layoutLabel} grid)
              {gridFull && (
                // Say why the remaining checkboxes are dead. Greying them
                // out silently left an operator clicking a box that never
                // ticked, with nothing on screen explaining it.
                <span className="camera-selector-dropdown__grid-full">
                  Grid full: choose a larger layout
                </span>
              )}
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