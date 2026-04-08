import { useMemo, useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  useViolationsQuery,
  useDevicesQuery,
  useModelsStatusQuery,
  getCameraStatus,
  getDetectionStatus,
  isAnyModelHealthy,
  type Device,
} from '../../state';
import { getGridSize, type GridSize } from '../../utils/cameraGridPreferences';
import './TopStatusBar.css';

/**
 * Top Status Bar (Enhanced Overview Header)
 *
 * Displays detailed summary cards and camera grid in a prominent header section.
 * Each metric card shows the value prominently with a descriptive label and optional link.
 * Camera grid shows status tiles for quick camera overview.
 */
export function TopStatusBar() {
  // Fetch violations for open count (summary card)
  const {
    data: violationsData,
    isLoading: isViolationsLoading,
    isError: isViolationsError,
  } = useViolationsQuery({ status: 'open' });

  // Fetch devices for camera count and grid
  const {
    data: devicesData,
    isLoading: isDevicesLoading,
    isError: isDevicesError,
    refetch: refetchDevices,
  } = useDevicesQuery();

  // Fetch models for model health
  const {
    data: modelsData,
    isLoading: isModelsLoading,
    isError: isModelsError,
  } = useModelsStatusQuery();

  // Derive open violations count
  const openViolationsCount = useMemo(() => {
    if (!violationsData?.items) return null;
    return violationsData.total;
  }, [violationsData]);

  // Derive camera counts
  const cameraCounts = useMemo(() => {
    if (!devicesData?.items) return { live: null, total: null };
    const total = devicesData.items.length;
    const live = devicesData.items.filter(
      (d) => d.is_active && d.streaming.active
    ).length;
    return { live, total };
  }, [devicesData]);

  // Derive model counts
  const modelCounts = useMemo(() => {
    if (!modelsData?.models) return { healthy: null, total: null };
    const total = modelsData.models.length;
    const healthy = modelsData.models.filter(
      (m) => m.health === 'healthy' && m.status === 'active'
    ).length;
    return { healthy, total };
  }, [modelsData]);

  // Check if any model is healthy for camera grid
  const isModelHealthy = useMemo(() => {
    if (!modelsData?.models) return true;
    return isAnyModelHealthy(modelsData.models);
  }, [modelsData]);

  return (
    <div className="top-status-bar">
      {/* Summary Metric Cards */}
      <div className="top-status-bar__cards">
        <MetricCard
          label="Open Alerts"
          value={openViolationsCount}
          isLoading={isViolationsLoading}
          isError={isViolationsError}
          linkTo="/alerts"
          linkLabel="View All"
          variant="alert"
          icon="!"
        />
        <MetricCard
          label="Cameras Live"
          value={cameraCounts.live}
          secondaryValue={cameraCounts.total}
          isLoading={isDevicesLoading}
          isError={isDevicesError}
          linkTo="/cameras"
          linkLabel="View All"
          icon="◉"
        />
        <MetricCard
          label="Models Active"
          value={modelCounts.healthy}
          secondaryValue={modelCounts.total}
          isLoading={isModelsLoading}
          isError={isModelsError}
          icon="◆"
        />
      </div>

      {/* Camera Grid Panel */}
      <CameraGridPanel
        devices={devicesData?.items ?? []}
        isLoading={isDevicesLoading}
        isError={isDevicesError}
        isModelHealthy={isModelHealthy}
        onRetry={refetchDevices}
      />
    </div>
  );
}

interface MetricCardProps {
  label: string;
  value: number | null;
  secondaryValue?: number | null;
  isLoading: boolean;
  isError: boolean;
  linkTo?: string;
  linkLabel?: string;
  variant?: 'default' | 'alert';
  icon?: string;
}

/**
 * Individual metric card with prominent value display
 */
function MetricCard({
  label,
  value,
  secondaryValue,
  isLoading,
  isError,
  linkTo,
  linkLabel,
  variant = 'default',
  icon,
}: MetricCardProps) {
  const displayValue = useMemo(() => {
    if (isLoading) return '—';
    if (isError || value === null) return '?';
    if (secondaryValue !== undefined && secondaryValue !== null) {
      return `${value} / ${secondaryValue}`;
    }
    return String(value);
  }, [value, secondaryValue, isLoading, isError]);

  const hasAlert = variant === 'alert' && value !== null && value > 0;

  return (
    <div
      className={`top-status-bar__card ${
        hasAlert ? 'top-status-bar__card--alert' : ''
      } ${isLoading ? 'top-status-bar__card--loading' : ''} ${
        isError ? 'top-status-bar__card--error' : ''
      }`}
    >
      {icon && (
        <span className={`top-status-bar__card-icon ${hasAlert ? 'top-status-bar__card-icon--alert' : ''}`}>
          {icon}
        </span>
      )}
      <span className={`top-status-bar__card-value ${hasAlert ? 'top-status-bar__card-value--alert' : ''}`}>
        {displayValue}
      </span>
      <span className="top-status-bar__card-label">{label}</span>
      {linkTo && linkLabel && (
        <Link to={linkTo} className="top-status-bar__card-link">
          {linkLabel} &rarr;
        </Link>
      )}
    </div>
  );
}

interface CameraGridPanelProps {
  devices: Device[];
  isLoading: boolean;
  isError: boolean;
  isModelHealthy: boolean;
  onRetry: () => void;
}

/**
 * Camera Grid Panel for the top status bar
 */
function CameraGridPanel({
  devices,
  isLoading,
  isError,
  isModelHealthy,
  onRetry,
}: CameraGridPanelProps) {
  // Read grid size preference from localStorage (synced with Camera Monitoring page)
  const [gridSize, setGridSizeState] = useState<GridSize>(getGridSize);

  // Listen for storage changes to sync with Camera Monitoring page
  useEffect(() => {
    const handleStorageChange = () => {
      setGridSizeState(getGridSize());
    };

    window.addEventListener('storage', handleStorageChange);
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
  const cameras = devices.slice(0, maxCameras);

  // Dynamic grid style based on preference
  const gridStyle = {
    gridTemplateColumns: `repeat(${gridSize}, 1fr)`,
  };

  // Loading state
  if (isLoading && devices.length === 0) {
    return (
      <div className="top-status-bar__camera-grid">
        <div className="top-status-bar__camera-grid-header">
          <span className="top-status-bar__camera-grid-title">Camera Grid</span>
        </div>
        <div className="top-status-bar__camera-grid-tiles" style={gridStyle}>
          {Array.from({ length: maxCameras }).map((_, i) => (
            <div key={i} className="top-status-bar__camera-tile top-status-bar__camera-tile--skeleton">
              <span className="top-status-bar__skeleton-bar" />
              <span className="top-status-bar__skeleton-bar top-status-bar__skeleton-bar--short" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Error state
  if (isError && devices.length === 0) {
    return (
      <div className="top-status-bar__camera-grid top-status-bar__camera-grid--error">
        <div className="top-status-bar__camera-grid-header">
          <span className="top-status-bar__camera-grid-title">Camera Grid</span>
        </div>
        <div className="top-status-bar__camera-grid-error">
          <p>Couldn't load cameras.</p>
          <button
            type="button"
            className="top-status-bar__camera-grid-retry"
            onClick={() => onRetry()}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // Empty state
  if (cameras.length === 0) {
    return (
      <div className="top-status-bar__camera-grid">
        <div className="top-status-bar__camera-grid-header">
          <span className="top-status-bar__camera-grid-title">Camera Grid</span>
        </div>
        <div className="top-status-bar__camera-grid-empty">
          <p>No cameras configured</p>
          <p className="top-status-bar__camera-grid-empty-hint">
            Cameras will appear here when added.
          </p>
        </div>
      </div>
    );
  }

  // Normal state with cameras
  return (
    <div className="top-status-bar__camera-grid">
      <div className="top-status-bar__camera-grid-header">
        <span className="top-status-bar__camera-grid-title">Camera Grid</span>
        <Link to="/cameras" className="top-status-bar__camera-grid-link">
          View All &rarr;
        </Link>
      </div>
      <div className="top-status-bar__camera-grid-tiles" style={gridStyle}>
        {cameras.map((device) => (
          <CameraTile
            key={device.id}
            device={device}
            isModelHealthy={isModelHealthy}
          />
        ))}
      </div>
    </div>
  );
}

interface CameraTileProps {
  device: Device;
  isModelHealthy: boolean;
}

/**
 * Single camera tile in the top bar panel
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
      className={`top-status-bar__camera-tile ${isLive ? '' : 'top-status-bar__camera-tile--offline'}`}
    >
      <div className="top-status-bar__camera-tile-header">
        <span className={`top-status-bar__camera-status ${isLive ? 'top-status-bar__camera-status--live' : 'top-status-bar__camera-status--offline'}`}>
          {statusIndicator}
        </span>
        <span className="top-status-bar__camera-name">{device.name}</span>
      </div>
      <div className="top-status-bar__camera-tile-body">
        <span className="top-status-bar__camera-status-label">{statusLabel}</span>
        <span className={`top-status-bar__camera-detection top-status-bar__camera-detection--${detectionStatus}`}>
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
