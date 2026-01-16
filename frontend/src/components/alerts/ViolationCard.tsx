import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import type { Violation } from '../../state/api';
import { getConfidenceCategory, getConfidenceDisplay } from '../../state';
import { ConfidenceBadge } from './ConfidenceBadge';
import { StatusBadge } from './StatusBadge';
import { SnapshotThumbnail } from './SnapshotThumbnail';
import './ViolationCard.css';

/**
 * Format relative time (F6 §12.1)
 *
 * | Source Format | Display Format |
 * |---------------|----------------|
 * | ISO 8601 < 24h | "2m ago", "1h ago" |
 * | ISO 8601 > 24h | "Jan 13, 10:30 AM" |
 */
function formatRelativeTime(isoTimestamp: string): string {
  const date = new Date(isoTimestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMinutes = Math.floor(diffMs / 60000);

  if (diffMinutes < 1) return 'Just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;

  // > 24h: show date + time
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

interface ViolationCardProps {
  violation: Violation;
  onAcknowledge: (id: string) => void;
  onDismiss: (id: string) => void;
  /** Whether an action is in progress for this card */
  isActionPending?: boolean;
  /** Which action is pending */
  pendingAction?: 'acknowledge' | 'dismiss' | null;
  /** Error message for this card's action */
  actionError?: string | null;
}

/**
 * Violation Card Component (F4-aligned)
 *
 * Displays a single violation in the Alerts List.
 *
 * Per F4 wireframe:
 * - Camera name prominently displayed
 * - Confidence badge (High/Medium/Low, never numbers)
 * - Snapshot thumbnail (placeholder if unavailable)
 * - Status badge (New/Reviewed)
 * - Actions: View Details, Mark Reviewed, Dismiss
 *
 * Per F5 §A1:
 * - Each action completes independently
 * - No blocking between cards
 *
 * HARD RULES:
 * - F6 §3.2: MUST NOT display raw confidence numbers
 * - F3 Flow 3: Dismiss requires confirmation (handled by parent)
 */
// Default evidence object when backend doesn't provide one
const DEFAULT_EVIDENCE = {
  snapshot_id: null,
  snapshot_url: null,
  snapshot_status: 'pending' as const,
  bookmark_id: null,
  bookmark_url: null,
  bookmark_status: 'pending' as const,
};

export function ViolationCard({
  violation,
  onAcknowledge,
  onDismiss,
  isActionPending = false,
  pendingAction = null,
  actionError = null,
}: ViolationCardProps) {
  const confidenceCategory = getConfidenceCategory(violation.confidence);
  const confidenceLabel = getConfidenceDisplay(violation.confidence);

  // Use default evidence if not provided by backend
  const evidence = violation.evidence ?? DEFAULT_EVIDENCE;

  const handleAcknowledge = useCallback(() => {
    if (!isActionPending) {
      onAcknowledge(violation.id);
    }
  }, [isActionPending, onAcknowledge, violation.id]);

  const handleDismiss = useCallback(() => {
    if (!isActionPending) {
      onDismiss(violation.id);
    }
  }, [isActionPending, onDismiss, violation.id]);

  // Determine if acknowledge button should be visible
  // Per F6 §3.3: only show for 'open' status
  const canAcknowledge = violation.status === 'open';

  // Dismiss is available for both 'open' and 'reviewed'
  const canDismiss = violation.status === 'open' || violation.status === 'reviewed';

  return (
    <article
      className={`violation-card violation-card--${confidenceCategory}`}
      aria-label={`Violation on ${violation.camera_name}, ${confidenceLabel} confidence`}
    >
      {/* Thumbnail */}
      <div className="violation-card__thumbnail">
        <SnapshotThumbnail
          snapshotUrl={evidence.snapshot_url}
          snapshotStatus={evidence.snapshot_status}
          alt={`Detection snapshot from ${violation.camera_name}`}
        />
      </div>

      {/* Content */}
      <div className="violation-card__content">
        <div className="violation-card__header">
          <h3 className="violation-card__camera">{violation.camera_name}</h3>
          <div className="violation-card__badges">
            <ConfidenceBadge category={confidenceCategory} label={confidenceLabel} />
            <StatusBadge status={violation.status} />
          </div>
        </div>

        <div className="violation-card__meta">
          <span className="violation-card__time">{formatRelativeTime(violation.timestamp)}</span>
          <span className="violation-card__type">Fall Detection</span>
        </div>

        {/* Error display (inline, per F5 §B3) */}
        {actionError && (
          <div className="violation-card__error" role="alert">
            {actionError}
          </div>
        )}

        {/* Actions */}
        <div className="violation-card__actions">
          <Link
            to={`/alerts/${violation.id}`}
            className="violation-card__action violation-card__action--view"
          >
            View Details
          </Link>

          {canAcknowledge && (
            <button
              type="button"
              className="violation-card__action violation-card__action--acknowledge"
              onClick={handleAcknowledge}
              disabled={isActionPending}
              aria-busy={pendingAction === 'acknowledge'}
            >
              {pendingAction === 'acknowledge' ? 'Saving...' : 'Mark Reviewed'}
            </button>
          )}

          {canDismiss && (
            <button
              type="button"
              className="violation-card__action violation-card__action--dismiss"
              onClick={handleDismiss}
              disabled={isActionPending}
              aria-busy={pendingAction === 'dismiss'}
            >
              {pendingAction === 'dismiss' ? 'Saving...' : 'Dismiss'}
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
