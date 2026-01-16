import { CameraMonitoringDashboard } from '../components/cameras/CameraMonitoringDashboard';
import { useDevicesQuery } from '../state';

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
 *
 * States per F7 §8:
 * - Loading: Skeleton loaders
 * - Empty: "No cameras configured" message
 * - Error: Friendly message + retry
 */
export function CamerasPage() {
  const { data: devicesData, isLoading, isError, refetch } = useDevicesQuery();

  return (
    <div className="page-container">
      <CameraMonitoringDashboard
        cameras={devicesData?.items || []}
        isLoading={isLoading}
        isError={isError}
        onRetry={() => refetch()}
      />
    </div>
  );
}
