import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../queryKeys';
import { POLLING_INTERVALS } from '../pollingIntervals';
import {
  fetchAnalyticsSummary,
  getStalenessLevel as apiGetStalenessLevel,
  getStalenessMessage as apiGetStalenessMessage,
  formatCount as apiFormatCount,
  formatRatio as apiFormatRatio,
} from '../api';
import type { AnalyticsSummaryResponse, StalenessLevel } from '../api';

/**
 * Analytics Summary Query Hook
 *
 * Fetches analytics summary with 60s polling (F6 §11.1).
 *
 * Uses the centralized API client - no direct fetch calls.
 */
export function useAnalyticsQuery() {
  return useQuery({
    queryKey: queryKeys.analytics.summary,
    queryFn: fetchAnalyticsSummary,
    refetchInterval: POLLING_INTERVALS.ANALYTICS,
    refetchIntervalInBackground: false,
  });
}

/**
 * Calculate staleness level from generated_at timestamp (F6 §6.3)
 *
 * Re-exported from API module for convenience.
 */
export function getStalenessLevel(generatedAt: string): StalenessLevel {
  return apiGetStalenessLevel(generatedAt);
}

/**
 * Get staleness warning message (if needed)
 *
 * Re-exported from API module for convenience.
 */
export function getStalenessMessage(
  generatedAt: string,
  level: StalenessLevel
): string | null {
  return apiGetStalenessMessage(generatedAt, level);
}

/**
 * Format count for display (F6 §6.2)
 *
 * Re-exported from API module for convenience.
 */
export function formatCount(count: number | undefined): string {
  return apiFormatCount(count);
}

/**
 * Format ratio for display (F6 §6.2)
 *
 * HARD RULE: MUST NOT perform arithmetic on counts from different API calls.
 *
 * Re-exported from API module for convenience.
 */
export function formatRatio(
  active: number | undefined,
  total: number | undefined
): string {
  return apiFormatRatio(active, total);
}

// Re-export types for consumers
export type { AnalyticsSummaryResponse, StalenessLevel };
