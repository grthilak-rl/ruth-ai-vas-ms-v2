import { useMemo } from 'react';
import { useParams } from 'react-router-dom';
import {
  useDeviceQuery,
  useModelsStatusQuery,
  useViolationsQuery,
  getCameraStatus,
  getDetectionStatus,
  isAnyModelHealthy,
} from '../state';
import {
  CameraDetailView,
  CameraDetailSkeleton,
  CameraNotFound,
} from '../components/cameras';

/**
 * Camera Detail/View Page (F2 Path: /cameras/:id)
 *
 * Live video player with detection status and recent violations.
 *
 * Per F4 §7.3:
 * - Live video feed
 * - Detection status messaging
 * - Today's violations for this camera
 *
 * Per E7 Task Spec:
 * - Video continues working when AI is paused/unavailable
 * - Clear detection status (non-alarming)
 * - Recent violations (read-only, non-blocking)
 * - Split functionality: video and AI are independent
 *
 * States (F4):
 * - Loading: Skeleton placeholder
 * - Error/Not Found: CameraNotFound
 * - Success: CameraDetailView
 */
export function CameraDetailPage() {
  const { id } = useParams<{ id: string }>();

  // Fetch device data
  const {
    data: device,
    isLoading: isDeviceLoading,
    isError: isDeviceError,
  } = useDeviceQuery(id ?? '');

  // Fetch model status for detection status
  const { data: modelsData } = useModelsStatusQuery();

  // Fetch violations for this camera (today only)
  // Note: Query runs even without id, but will filter correctly
  const {
    data: violationsData,
    isLoading: isViolationsLoading,
  } = useViolationsQuery(
    id ? { camera_id: id, sort_by: 'timestamp', sort_order: 'desc' } : undefined
  );

  // Determine model health
  const isModelHealthy = useMemo(() => {
    if (!modelsData?.models) return true;
    return isAnyModelHealthy(modelsData.models);
  }, [modelsData]);

  // Loading state
  if (isDeviceLoading) {
    return <CameraDetailSkeleton />;
  }

  // Error or not found state
  if (isDeviceError || !device) {
    return <CameraNotFound />;
  }

  // Derive status
  const cameraStatus = getCameraStatus(device);
  const detectionStatus = getDetectionStatus(device, isModelHealthy);

  return (
    <CameraDetailView
      device={device}
      cameraStatus={cameraStatus}
      detectionStatus={detectionStatus}
      violations={violationsData?.items}
      violationsLoading={isViolationsLoading}
    />
  );
}
