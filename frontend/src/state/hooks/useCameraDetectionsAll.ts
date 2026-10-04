import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../queryKeys';
import { POLLING_INTERVALS } from '../pollingIntervals';
import { fetchDetectionsAll } from '../api/detections.api';
import type { DetectionEntry } from '../api/detections.api';

/**
 * Newest result of every model running on a camera (multi-model sessions).
 *
 * Same sharing and cadence as useCameraDetections: keyed by device, so every
 * tile showing one camera shares ONE request every POLLING_INTERVALS.DETECTIONS,
 * and polling stops with the last consumer or a backgrounded tab. One request
 * per camera per interval, as before; only the response carries one entry
 * per model.
 */
export function useCameraDetectionsAll(
  deviceId: string | undefined,
  enabled: boolean = true
) {
  const query = useQuery<DetectionEntry[]>({
    queryKey: queryKeys.devices.detectionsAll(deviceId ?? ''),
    queryFn: () => fetchDetectionsAll(deviceId as string),
    enabled: Boolean(deviceId) && enabled,
    refetchInterval: POLLING_INTERVALS.DETECTIONS,
    refetchIntervalInBackground: false,
    staleTime: 0,
    gcTime: 5000,
    retry: false,
  });

  return {
    detections: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
  };
}
