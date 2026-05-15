import {
  getStalenessLevel as apiGetStalenessLevel,
  getStalenessMessage as apiGetStalenessMessage,
  formatCount as apiFormatCount,
  formatRatio as apiFormatRatio,
} from '../api';
import type { AnalyticsSummaryResponse, StalenessLevel } from '../api';

// NOTE: useAnalyticsQuery (the React Query hook) was removed in
// perf/polling-and-bulk-fetch — it had zero callers. AnalyticsPage
// has its own bespoke setInterval calling getAnalyticsSummary; a
// follow-up should migrate it to a hook so we get dedup + retry.

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
