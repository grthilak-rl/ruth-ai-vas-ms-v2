/**
 * Analytics API
 *
 * READ-ONLY API for analytics summary (F6 §6).
 *
 * Source Endpoint: GET /api/v1/analytics/summary
 *
 * HARD RULES:
 * - F6 §6.2: MUST NOT perform arithmetic on counts from different API calls
 * - F6 §6.3: MUST check staleness of generated_at timestamp
 */

import { apiGet } from './client';
import type { AnalyticsSummaryResponse } from './types';
import { isAnalyticsSummaryResponse, assertResponse } from './validators';

/** API path for analytics */
const ANALYTICS_PATH = '/api/v1/analytics/summary';

/**
 * Fetch analytics summary
 *
 * Returns aggregated metrics for display.
 *
 * IMPORTANT (F6 §6.3): Always check staleness of generated_at.
 */
export async function fetchAnalyticsSummary(): Promise<AnalyticsSummaryResponse> {
  const response = await apiGet<unknown>(ANALYTICS_PATH);
  return assertResponse(response, isAnalyticsSummaryResponse, 'AnalyticsSummaryResponse');
}

// ============================================================================
// Staleness Helpers (F6 §6.3)
// ============================================================================

/**
 * Staleness thresholds in milliseconds
 */
export const STALENESS_THRESHOLDS = {
  /** Data considered fresh */
  FRESH: 60 * 1000, // 60 seconds

  /** Data considered stale but usable */
  STALE: 300 * 1000, // 5 minutes
} as const;

/**
 * Staleness level (F6 §6.3)
 *
 * | generated_at Age | UI Behavior                              |
 * |------------------|------------------------------------------|
 * | < 60 seconds     | Display normally                         |
 * | 60–300 seconds   | Display with "Last updated: X ago"       |
 * | > 300 seconds    | Display with "Data may be outdated"      |
 */
export type StalenessLevel = 'fresh' | 'stale' | 'very_stale';

/**
 * Calculate staleness level from generated_at timestamp
 */
export function getStalenessLevel(generatedAt: string): StalenessLevel {
  const generatedTime = new Date(generatedAt).getTime();
  const now = Date.now();
  const age = now - generatedTime;

  if (age < STALENESS_THRESHOLDS.FRESH) {
    return 'fresh';
  }
  if (age < STALENESS_THRESHOLDS.STALE) {
    return 'stale';
  }
  return 'very_stale';
}

/**
 * Get staleness warning message (if needed)
 */
export function getStalenessMessage(
  generatedAt: string,
  level: StalenessLevel
): string | null {
  if (level === 'fresh') {
    return null;
  }

  const generatedTime = new Date(generatedAt).getTime();
  const now = Date.now();
  const ageSeconds = Math.floor((now - generatedTime) / 1000);

  if (level === 'stale') {
    return `Last updated: ${formatTimeAgo(ageSeconds)}`;
  }

  return 'Data may be outdated';
}

/**
 * Format seconds as human-readable time ago
 */
function formatTimeAgo(seconds: number): string {
  if (seconds < 60) {
    return `${seconds}s ago`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m ago`;
  }
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

// ============================================================================
// Count Display Helpers (F6 §6.2)
// ============================================================================

/**
 * Format count for display (F6 §6.2)
 *
 * | Metric           | Display Format | Example |
 * |------------------|----------------|---------|
 * | Open violations  | Integer        | "12"    |
 * | Total violations | Integer        | "47"    |
 */
export function formatCount(count: number | undefined): string {
  if (count === undefined) {
    return '—';
  }
  return String(count);
}

/**
 * Format ratio for display (F6 §6.2)
 *
 * | Metric          | Display Format | Example   |
 * |-----------------|----------------|-----------|
 * | Cameras active  | "X / Y" format | "8 / 10"  |
 * | Models active   | "X / Y" format | "2 / 3"   |
 *
 * HARD RULE: MUST NOT perform arithmetic on counts from different API calls.
 * Only use this with values from the SAME response.
 */
export function formatRatio(
  active: number | undefined,
  total: number | undefined
): string {
  if (active === undefined || total === undefined) {
    return '— / —';
  }
  return `${active} / ${total}`;
}

// ============================================================================
// Re-exports for consumers
// ============================================================================

export type { AnalyticsSummaryResponse, AnalyticsTotals } from './types';
