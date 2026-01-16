import { useMemo } from 'react';

/**
 * Staleness level based on data age (F6 §6.3)
 */
export type StalenessLevel = 'fresh' | 'stale' | 'outdated';

/**
 * Staleness thresholds per F6 §6.3
 */
const STALE_THRESHOLD_MS = 60 * 1000; // 60 seconds
const OUTDATED_THRESHOLD_MS = 300 * 1000; // 300 seconds (5 minutes)

/**
 * Calculate staleness level from timestamp
 *
 * Per F6 §6.3 Staleness Contract:
 * - < 60 seconds: Display normally (fresh)
 * - 60-300 seconds: Display with "Last updated: X ago" (stale)
 * - > 300 seconds: Display with "Data may be outdated" warning (outdated)
 */
export function getStalenessLevel(timestamp: string | Date | null | undefined): StalenessLevel {
  if (!timestamp) {
    return 'outdated'; // Unknown timestamp treated as outdated
  }

  const timestampDate = typeof timestamp === 'string' ? new Date(timestamp) : timestamp;
  const ageMs = Date.now() - timestampDate.getTime();

  if (ageMs < STALE_THRESHOLD_MS) {
    return 'fresh';
  } else if (ageMs < OUTDATED_THRESHOLD_MS) {
    return 'stale';
  } else {
    return 'outdated';
  }
}

/**
 * Format relative time for staleness display
 */
export function formatRelativeTime(timestamp: string | Date | null | undefined): string {
  if (!timestamp) {
    return 'unknown';
  }

  const timestampDate = typeof timestamp === 'string' ? new Date(timestamp) : timestamp;
  const ageMs = Date.now() - timestampDate.getTime();
  const ageSeconds = Math.floor(ageMs / 1000);

  if (ageSeconds < 60) {
    return 'just now';
  } else if (ageSeconds < 3600) {
    const minutes = Math.floor(ageSeconds / 60);
    return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  } else if (ageSeconds < 86400) {
    const hours = Math.floor(ageSeconds / 3600);
    return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  } else {
    const days = Math.floor(ageSeconds / 86400);
    return `${days} day${days === 1 ? '' : 's'} ago`;
  }
}

interface UseStalenessResult {
  /** Current staleness level */
  level: StalenessLevel;
  /** Human-readable relative time */
  relativeTime: string;
  /** Whether data is stale or outdated */
  isStale: boolean;
  /** Whether data is severely outdated */
  isOutdated: boolean;
  /** Display message based on staleness */
  message: string | null;
}

/**
 * Hook for tracking data staleness (F6 §6.3)
 *
 * Per E9: Staleness is visible, not inferred.
 * Cached data is clearly labeled when stale.
 *
 * @param timestamp - ISO 8601 timestamp or Date object
 * @returns Staleness info including level, relative time, and display message
 */
export function useStaleness(timestamp: string | Date | null | undefined): UseStalenessResult {
  return useMemo(() => {
    const level = getStalenessLevel(timestamp);
    const relativeTime = formatRelativeTime(timestamp);
    const isStale = level === 'stale' || level === 'outdated';
    const isOutdated = level === 'outdated';

    let message: string | null = null;
    if (level === 'stale') {
      message = `Last updated ${relativeTime}`;
    } else if (level === 'outdated') {
      message = 'Data may be outdated';
    }

    return {
      level,
      relativeTime,
      isStale,
      isOutdated,
      message,
    };
  }, [timestamp]);
}
