import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../queryKeys';
import { POLLING_INTERVALS } from '../pollingIntervals';
import { fetchHealthWithFallback } from '../api';
import type { HealthResponse } from '../api';

/**
 * Global status derived from health response (F6 §4.2)
 */
export type GlobalStatus = 'healthy' | 'degraded' | 'offline';

/**
 * Health Query Hook
 *
 * Fetches system health with 30s polling (F6 §11.1).
 *
 * Uses the centralized API client - no direct fetch calls.
 */
export function useHealthQuery() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: fetchHealthWithFallback,
    refetchInterval: POLLING_INTERVALS.HEALTH,
    refetchIntervalInBackground: false, // Pause on tab inactive
  });
}

/**
 * Derive global status from health response (F6 §4.2)
 *
 * This is the ONLY place global status is derived.
 * Frontend MUST NOT infer health from other signals.
 *
 * | Backend State                              | Frontend Display |
 * |--------------------------------------------|------------------|
 * | status = "healthy"                         | "healthy"        |
 * | status = "unhealthy" + component unhealthy | "degraded"       |
 * | API call fails                             | "offline"        |
 */
export function deriveGlobalStatus(
  data: HealthResponse | undefined,
  isError: boolean
): GlobalStatus {
  if (isError || !data) {
    return 'offline';
  }

  if (data.status === 'unhealthy') {
    return 'degraded';
  }

  return 'healthy';
}

/**
 * Get display text for global status (F6 §4.2)
 */
export function getGlobalStatusDisplay(status: GlobalStatus): string {
  switch (status) {
    case 'healthy':
      return 'All Systems OK';
    case 'degraded':
      return 'Degraded';
    case 'offline':
      return 'Offline';
  }
}
