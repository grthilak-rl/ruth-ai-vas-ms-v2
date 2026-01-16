import { useStaleness, type StalenessLevel } from './useStaleness';
import './StalenessIndicator.css';

interface StalenessIndicatorProps {
  /** ISO 8601 timestamp or Date object */
  timestamp: string | Date | null | undefined;
  /** Size variant */
  size?: 'small' | 'medium';
  /** Whether to always show (even when fresh) */
  showWhenFresh?: boolean;
}

/**
 * Staleness Indicator Component (E9 / F6 §6.3)
 *
 * Visual indicator for data freshness.
 *
 * Per F6 §6.3 Staleness Contract:
 * - < 60 seconds: Display normally (no indicator by default)
 * - 60-300 seconds: "Last updated X ago"
 * - > 300 seconds: "Data may be outdated" warning
 *
 * HARD RULES (E9):
 * - Staleness is visible, not inferred
 * - Cached data is clearly labeled when stale
 */
export function StalenessIndicator({
  timestamp,
  size = 'small',
  showWhenFresh = false,
}: StalenessIndicatorProps) {
  const { level, message, relativeTime } = useStaleness(timestamp);

  // Don't show if fresh and not explicitly requested
  if (level === 'fresh' && !showWhenFresh) {
    return null;
  }

  // For fresh data when showWhenFresh is true
  if (level === 'fresh') {
    return (
      <span
        className={`staleness-indicator staleness-indicator--${size} staleness-indicator--fresh`}
        aria-label={`Data updated ${relativeTime}`}
      >
        Updated {relativeTime}
      </span>
    );
  }

  return (
    <span
      className={`staleness-indicator staleness-indicator--${size} staleness-indicator--${level}`}
      role={level === 'outdated' ? 'alert' : 'status'}
      aria-live="polite"
    >
      {message}
    </span>
  );
}

// Re-export for convenience
export type { StalenessLevel };
