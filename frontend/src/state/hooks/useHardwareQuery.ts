import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../queryKeys';
import { POLLING_INTERVALS } from '../pollingIntervals';
import { fetchHardware } from '../api';
import type { HardwareResponse } from '../api';

/**
 * Hardware Query Hook
 *
 * Fetches hardware metrics with 5s polling for real-time monitoring.
 *
 * Features:
 * - Auto-refresh every 5 seconds
 * - Pauses polling when tab is inactive
 * - Never fails - endpoint always returns partial data
 * - Stale data shown while refetching
 */
export function useHardwareQuery() {
  return useQuery({
    queryKey: queryKeys.hardware,
    queryFn: fetchHardware,
    refetchInterval: POLLING_INTERVALS.HARDWARE,
    refetchIntervalInBackground: false, // Pause on tab inactive
    staleTime: POLLING_INTERVALS.HARDWARE / 2, // Consider stale after 2.5s
  });
}

/**
 * Derive overall capacity status from hardware response
 *
 * | Headroom     | Status   | Meaning                          |
 * |--------------|----------|----------------------------------|
 * | >= 50%       | healthy  | Plenty of capacity available     |
 * | 20-50%       | warning  | Approaching capacity limits      |
 * | < 20%        | critical | Near capacity limit              |
 */
export type CapacityStatus = 'healthy' | 'warning' | 'critical';

export function deriveCapacityStatus(
  data: HardwareResponse | undefined,
  isError: boolean
): CapacityStatus {
  if (isError || !data) {
    return 'critical';
  }

  const headroom = data.capacity.headroom_percent;
  if (headroom >= 50) return 'healthy';
  if (headroom >= 20) return 'warning';
  return 'critical';
}

/**
 * Get display text for capacity status
 */
export function getCapacityStatusDisplay(status: CapacityStatus): string {
  switch (status) {
    case 'healthy':
      return 'Healthy';
    case 'warning':
      return 'Near Limit';
    case 'critical':
      return 'At Capacity';
  }
}
