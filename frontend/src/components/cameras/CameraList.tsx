import { useMemo } from 'react';
import {
  useDevicesQuery,
  useModelsStatusQuery,
  getCameraStatus,
  getDetectionStatus,
  isAnyModelHealthy,
} from '../../state';
import type { Device } from '../../state';
import { CameraCard } from './CameraCard';
import { CameraListSkeleton } from './CameraListSkeleton';
import './CameraList.css';

interface CameraListProps {
  /** Optional map of camera ID to today's violation count */
  violationCounts?: Record<string, number>;
}

/**
 * Camera List Component (F4 §7)
 *
 * Grid view of all cameras with status indicators.
 *
 * Per F4:
 * - Loading: Skeleton placeholders
 * - Empty: "No cameras configured" message
 * - Error: Friendly message + retry
 *
 * Per E7 Task Spec:
 * - Display all cameras with Live/Offline indicator
 * - Detection status: Active/Paused/Disabled
 * - Status updates via polling (F6-compliant)
 * - List remains usable during partial failures
 *
 * HARD RULES:
 * - No stream IDs or internal identifiers
 * - No inference metrics
 * - Split functionality: video and AI are independent
 */
export function CameraList({ violationCounts = {} }: CameraListProps) {
  const {
    data: devicesData,
    isLoading: isDevicesLoading,
    isError: isDevicesError,
    refetch: refetchDevices,
  } = useDevicesQuery();

  const { data: modelsData } = useModelsStatusQuery();

  // Determine if any AI model is healthy
  const isModelHealthy = useMemo(() => {
    if (!modelsData?.models) return true; // Assume healthy if unknown
    return isAnyModelHealthy(modelsData.models);
  }, [modelsData]);

  // Count cameras by status
  const statusCounts = useMemo(() => {
    if (!devicesData?.items) return { active: 0, offline: 0, total: 0 };

    let active = 0;
    let offline = 0;

    devicesData.items.forEach((device) => {
      const status = getCameraStatus(device);
      if (status === 'live') {
        active++;
      } else {
        offline++;
      }
    });

    return { active, offline, total: devicesData.items.length };
  }, [devicesData]);

  // Loading state
  if (isDevicesLoading) {
    return <CameraListSkeleton />;
  }

  // Error state
  if (isDevicesError) {
    return (
      <div className="camera-list__error" role="alert">
        <p className="camera-list__error-message">
          Couldn't load cameras. Please try again.
        </p>
        <button
          type="button"
          className="camera-list__error-retry"
          onClick={() => refetchDevices()}
        >
          Retry
        </button>
      </div>
    );
  }

  // Empty state
  if (!devicesData?.items || devicesData.items.length === 0) {
    return (
      <div className="camera-list__empty">
        <p className="camera-list__empty-title">No cameras configured</p>
        <p className="camera-list__empty-message">
          Contact your admin to add cameras to the system.
        </p>
      </div>
    );
  }

  return (
    <div className="camera-list">
      {/* Header with counts */}
      <div className="camera-list__header">
        <h2 className="camera-list__title">
          Cameras ({statusCounts.active} Active, {statusCounts.offline} Offline)
        </h2>
      </div>

      {/* Grid */}
      <div className="camera-list__grid">
        {devicesData.items.map((device: Device) => {
          const cameraStatus = getCameraStatus(device);
          const detectionStatus = getDetectionStatus(device, isModelHealthy);
          const violationCount = violationCounts[device.id];

          return (
            <CameraCard
              key={device.id}
              device={device}
              cameraStatus={cameraStatus}
              detectionStatus={detectionStatus}
              violationCount={violationCount}
            />
          );
        })}
      </div>
    </div>
  );
}
