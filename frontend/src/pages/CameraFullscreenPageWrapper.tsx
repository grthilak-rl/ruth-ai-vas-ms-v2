import { useParams } from 'react-router-dom';
import { useDeviceQuery } from '../state';
import { CameraFullscreenPage } from './CameraFullscreenPage';

/**
 * CameraFullscreenPageWrapper
 *
 * Data-fetching wrapper for the fullscreen camera view.
 * Fetches device data and passes it to the presentation component.
 */
export function CameraFullscreenPageWrapper() {
  const { id } = useParams<{ id: string }>();

  const {
    data: device,
    isLoading,
    isError,
    refetch,
  } = useDeviceQuery(id ?? '');

  return (
    <CameraFullscreenPage
      device={device}
      isLoading={isLoading}
      isError={isError}
      onRetry={() => refetch()}
    />
  );
}