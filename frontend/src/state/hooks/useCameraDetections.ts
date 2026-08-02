import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../queryKeys';
import { POLLING_INTERVALS } from '../pollingIntervals';
import { fetchLatestDetections } from '../api/detections.api';
import type { LatestDetectionResponse } from '../api/detections.api';

/**
 * Shared per-camera detection source.
 *
 * The backend inference loop is the single producer of detections; players
 * read from it instead of running their own inference. Because the query key
 * is the device id, React Query collapses every consumer of the same camera
 * onto ONE request and ONE cache entry — so a camera shown in four tiles
 * polls once, not four times — and stops polling entirely when the last
 * consumer unmounts. That is the ref-counting requirement, handled by the
 * cache rather than by bookkeeping we would have to maintain ourselves.
 *
 * Pass enabled=false for cameras with no active model so we don't poll for
 * results that cannot exist.
 */
export function useCameraDetections(
  deviceId: string | undefined,
  enabled: boolean = true
) {
  const query = useQuery<LatestDetectionResponse | null>({
    queryKey: queryKeys.devices.detections(deviceId ?? ''),
    queryFn: () => fetchLatestDetections(deviceId as string),
    enabled: Boolean(deviceId) && enabled,
    refetchInterval: POLLING_INTERVALS.DETECTIONS,
    // Overlays are only useful live. Polling a backgrounded tab would burn
    // requests drawing boxes nobody can see.
    refetchIntervalInBackground: false,
    // Every poll is meant to supersede the last — there is no point serving a
    // cached box from two seconds ago while a fresher one is in flight.
    staleTime: 0,
    gcTime: 5000,
    // A missing result is normal (no model enabled yet), and the next poll is
    // 500ms away regardless, so retrying a failure buys nothing.
    retry: false,
  });

  return {
    detection: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error,
  };
}
