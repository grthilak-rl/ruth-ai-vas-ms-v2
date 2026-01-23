import { useMemo, useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  useDevicesQuery,
  useModelsStatusQuery,
  getCameraStatus,
  getDetectionStatus,
  isAnyModelHealthy,
} from '../../state';
import type { Device } from '../../state';
import { getGridSize, type GridSize } from '../../utils/cameraGridPreferences';
import './CameraGrid.css';

/**
 * Camera Grid Section (F4 §4.1)
 *
 * Displays a grid of camera status tiles on the Overview dashboard.
 *
 * Per F4:
 * - Grid layout matches the Camera Monitoring page preference
 * - Each tile shows: Camera name, Live/Offline status, Detection Active/Paused
 * - Clicking navigates to Camera Detail
 * - No video playback (just status)
 *
 * Per F6:
 * - Camera status from devices query
 * - Detection status derived from device + model health
 *
 * States:
 * - Loading: Skeleton tiles
 * - Empty: "No cameras configured"
 * - Error: Error message with retry
 */
export function CameraGrid() {
  // Read grid size preference from localStorage (synced with Camera Monitoring page)
  const [gridSize, setGridSizeState] = useState<GridSize>(getGridSize);

  // Listen for storage changes to sync with Camera Monitoring page
  useEffect(() => {
    const handleStorageChange = () => {
      setGridSizeState(getGridSize());
    };

    // Listen for storage events from other tabs
    window.addEventListener('storage', handleStorageChange);

    // Also check on focus (for same-tab changes)
    const handleFocus = () => {
      setGridSizeState(getGridSize());
    };
    window.addEventListener('focus', handleFocus);

    return () => {
      window.removeEventListener('storage', handleStorageChange);
      window.removeEventListener('focus', handleFocus);
    };
  }, []);

  const maxCameras = gridSize * gridSize;

  const {
    data: devicesData,
    isLoading: isDevicesLoading,
    isError: isDevicesError,
    refetch: refetchDevices,
  } = useDevicesQuery();

  const { data: modelsData } = useModelsStatusQuery();

  // Check if any model is healthy
  const isModelHealthy = useMemo(() => {
    if (!modelsData?.models) return true;
    return isAnyModelHealthy(modelsData.models);
  }, [modelsData]);

  // Get cameras based on grid size
  const cameras = useMemo(() => {
    if (!devicesData?.items) return [];
    return devicesData.items.slice(0, maxCameras);
  }, [devicesData, maxCameras]);

  // Dynamic grid style based on preference
  const gridStyle = {
    gridTemplateColumns: `repeat(${gridSize}, 1fr)`,
  };

  // Loading state
  if (isDevicesLoading) {
    return (
      <section className="camera-grid">
        <div className="camera-grid__header">
          <h2 className="camera-grid__title">Camera Grid</h2>
        </div>
        <div className="camera-grid__tiles" style={gridStyle}>
          {Array.from({ length: maxCameras }).map((_, i) => (
            <div key={i} className="camera-grid__tile camera-grid__tile--skeleton">
              <div className="camera-grid__skeleton-content">
                <span className="camera-grid__skeleton-bar camera-grid__skeleton-bar--name" />
                <span className="camera-grid__skeleton-bar camera-grid__skeleton-bar--status" />
              </div>
            </div>
          ))}
        </div>
      </section>
    );
  }

  // Error state
  if (isDevicesError) {
    return (
      <section className="camera-grid">
        <div className="camera-grid__header">
          <h2 className="camera-grid__title">Camera Grid</h2>
        </div>
        <div className="camera-grid__error">
          <p>Couldn't load cameras.</p>
          <button
            type="button"
            className="camera-grid__retry"
            onClick={() => refetchDevices()}
          >
            Retry
          </button>
        </div>
      </section>
    );
  }

  // Empty state
  if (cameras.length === 0) {
    return (
      <section className="camera-grid">
        <div className="camera-grid__header">
          <h2 className="camera-grid__title">Camera Grid</h2>
        </div>
        <div className="camera-grid__empty">
          <p>No cameras configured</p>
          <p className="camera-grid__empty-hint">
            Cameras will appear here when added to the system.
          </p>
        </div>
      </section>
    );
  }

  // Normal state
  return (
    <section className="camera-grid">
      <div className="camera-grid__header">
        <h2 className="camera-grid__title">Camera Grid</h2>
        <Link to="/cameras" className="camera-grid__view-all">
          View All &rarr;
        </Link>
      </div>
      <div className="camera-grid__tiles" style={gridStyle}>
        {cameras.map((device) => (
          <CameraTile
            key={device.id}
            device={device}
            isModelHealthy={isModelHealthy}
          />
        ))}
      </div>
    </section>
  );
}

interface CameraTileProps {
  device: Device;
  isModelHealthy: boolean;
}

/**
 * Single camera tile
 */
function CameraTile({ device, isModelHealthy }: CameraTileProps) {
  const cameraStatus = getCameraStatus(device);
  const detectionStatus = getDetectionStatus(device, isModelHealthy);

  const isLive = cameraStatus === 'live';
  const statusIndicator = isLive ? '●' : '○';
  const statusLabel = isLive ? 'Live' : 'Offline';

  const detectionLabel = getDetectionLabel(detectionStatus);

  return (
    <Link
      to={`/cameras/${device.id}`}
      className={`camera-grid__tile ${isLive ? '' : 'camera-grid__tile--offline'}`}
    >
      <div className="camera-grid__tile-header">
        <span className={`camera-grid__status-indicator ${isLive ? 'camera-grid__status-indicator--live' : 'camera-grid__status-indicator--offline'}`}>
          {statusIndicator}
        </span>
        <span className="camera-grid__camera-name">{device.name}</span>
      </div>
      <div className="camera-grid__tile-body">
        <span className="camera-grid__status-label">{statusLabel}</span>
        <span className={`camera-grid__detection-label camera-grid__detection-label--${detectionStatus}`}>
          {detectionLabel}
        </span>
      </div>
    </Link>
  );
}

/**
 * Get human-readable detection label
 */
function getDetectionLabel(status: string): string {
  switch (status) {
    case 'active':
      return 'Detection Active';
    case 'paused':
      return 'Detection Paused';
    case 'disabled':
      return 'Detection Disabled';
    case 'unavailable':
      return 'Detection Unavailable';
    default:
      return 'Detection Unknown';
  }
}
