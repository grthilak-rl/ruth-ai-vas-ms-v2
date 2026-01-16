import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useViolationsQuery, getConfidenceLabel } from '../../state';
import type { Violation } from '../../state';
import './RecentViolations.css';

/** Maximum violations to display */
const MAX_VIOLATIONS = 5;

/**
 * Recent Violations Section (F4 §4.1)
 *
 * Displays the most recent N violations on the Overview dashboard.
 *
 * Per F4:
 * - Shows last 5 violations
 * - Each row: Type, Camera, Confidence (categorical), Time ago
 * - Clicking navigates to Violation Detail
 * - Read-only (no actions)
 *
 * Per F6 §7.1:
 * - MUST NOT assume backend order
 * - Explicit frontend sorting by timestamp (newest first)
 *
 * States:
 * - Loading: Skeleton rows
 * - Empty: "No recent violations"
 * - Error: Error message with retry
 */
export function RecentViolations() {
  const {
    data,
    isLoading,
    isError,
    refetch,
  } = useViolationsQuery({
    sort_by: 'timestamp',
    sort_order: 'desc',
    limit: MAX_VIOLATIONS,
  });

  // Explicit frontend sorting (F6 §7.1)
  const sortedViolations = useMemo(() => {
    if (!data?.items) return [];
    return [...data.items]
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
      .slice(0, MAX_VIOLATIONS);
  }, [data?.items]);

  // Loading state
  if (isLoading) {
    return (
      <section className="recent-violations">
        <div className="recent-violations__header">
          <h2 className="recent-violations__title">Recent Violations</h2>
        </div>
        <div className="recent-violations__list">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="recent-violations__row recent-violations__row--skeleton">
              <span className="recent-violations__skeleton-bar" />
              <span className="recent-violations__skeleton-bar" />
              <span className="recent-violations__skeleton-bar" />
              <span className="recent-violations__skeleton-bar" />
            </div>
          ))}
        </div>
      </section>
    );
  }

  // Error state
  if (isError) {
    return (
      <section className="recent-violations">
        <div className="recent-violations__header">
          <h2 className="recent-violations__title">Recent Violations</h2>
        </div>
        <div className="recent-violations__error">
          <p>Couldn't load recent violations.</p>
          <button
            type="button"
            className="recent-violations__retry"
            onClick={() => refetch()}
          >
            Retry
          </button>
        </div>
      </section>
    );
  }

  // Empty state
  if (sortedViolations.length === 0) {
    return (
      <section className="recent-violations">
        <div className="recent-violations__header">
          <h2 className="recent-violations__title">Recent Violations</h2>
        </div>
        <div className="recent-violations__empty">
          <p>No recent violations</p>
          <p className="recent-violations__empty-hint">
            New detections will appear here automatically.
          </p>
        </div>
      </section>
    );
  }

  // Normal state
  return (
    <section className="recent-violations">
      <div className="recent-violations__header">
        <h2 className="recent-violations__title">Recent Violations</h2>
        <Link to="/alerts" className="recent-violations__view-all">
          View All &rarr;
        </Link>
      </div>
      <div className="recent-violations__list">
        {sortedViolations.map((violation) => (
          <ViolationRow key={violation.id} violation={violation} />
        ))}
      </div>
    </section>
  );
}

interface ViolationRowProps {
  violation: Violation;
}

/**
 * Single violation row (read-only)
 */
function ViolationRow({ violation }: ViolationRowProps) {
  const confidenceLabel = getConfidenceLabel(violation.confidence);
  const timeAgo = formatTimeAgo(violation.timestamp);
  const typeLabel = formatViolationType(violation.type);

  return (
    <Link
      to={`/alerts/${violation.id}`}
      className="recent-violations__row"
    >
      <span className="recent-violations__type">
        <span className="recent-violations__indicator" aria-hidden="true">●</span>
        {typeLabel}
      </span>
      <span className="recent-violations__camera">{violation.camera_name}</span>
      <span className={`recent-violations__confidence recent-violations__confidence--${confidenceLabel.toLowerCase()}`}>
        {confidenceLabel}
      </span>
      <span className="recent-violations__time">{timeAgo}</span>
    </Link>
  );
}

/**
 * Format violation type for display
 */
function formatViolationType(type: string): string {
  switch (type) {
    case 'fall_detected':
      return 'Fall Detected';
    case 'ppe_violation':
      return 'PPE Missing';
    case 'unauthorized_access':
      return 'Unauthorized Entry';
    default:
      // Convert snake_case to Title Case
      return type
        .split('_')
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
  }
}

/**
 * Format timestamp as relative time
 */
function formatTimeAgo(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSecs = Math.floor(diffMs / 1000);

    if (diffSecs < 60) return 'Just now';
    if (diffSecs < 3600) return `${Math.floor(diffSecs / 60)}m ago`;
    if (diffSecs < 86400) return `${Math.floor(diffSecs / 3600)}h ago`;
    return `${Math.floor(diffSecs / 86400)}d ago`;
  } catch {
    return 'Unknown';
  }
}
