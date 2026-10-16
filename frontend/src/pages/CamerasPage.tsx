import { useCallback, useState } from 'react';
import { CameraMonitoringDashboard } from '../components/cameras/CameraMonitoringDashboard';
import { useDevicesQuery } from '../state';
import {
  getShowDisabledCameras,
  setShowDisabledCameras,
} from '../utils/cameraGridPreferences';

/**
 * Cameras Page (F2 Path: /cameras)
 *
 * Consolidated camera monitoring dashboard (per F7).
 * Replaces the old two-page architecture (camera list + camera detail).
 *
 * Features:
 * - Configurable grid layouts (1×1 through 5×5)
 * - Camera selector dropdown for multi-select
 * - Per-camera AI model toggles
 * - Live video feeds with detection overlays
 * - Fullscreen mode opens in new tab
 * - "Show disabled cameras" toggle, off by default
 *
 * States per F7 §8:
 * - Loading: Skeleton loaders
 * - Empty: "No cameras configured" message
 * - Error: Friendly message + retry
 */
export function CamerasPage() {
  // Cameras an operator retired in VAS are hidden unless asked for. This
  // page owns the choice because it owns the query; every other view in the
  // product gets the filtered list unconditionally. Persisted per browser so
  // an operator who needs to see a decommissioned unit does not have to
  // re-tick it on every visit.
  const [showDisabled, setShowDisabled] = useState(getShowDisabledCameras);

  const { data: devicesData, isLoading, isError, refetch } = useDevicesQuery({
    includeDisabled: showDisabled,
  });

  const handleShowDisabledChange = useCallback((show: boolean) => {
    setShowDisabled(show);
    setShowDisabledCameras(show);
  }, []);

  return (
    <div className="page-container">
      <CameraMonitoringDashboard
        cameras={devicesData?.items || []}
        isLoading={isLoading}
        isError={isError}
        onRetry={() => refetch()}
        showDisabled={showDisabled}
        onShowDisabledChange={handleShowDisabledChange}
      />
    </div>
  );
}
