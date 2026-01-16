import './EmptyState.css';

interface EmptyStateProps {
  /** Primary message - what's empty */
  title: string;
  /** Optional explanation or guidance */
  message?: string;
  /** Size variant */
  size?: 'small' | 'medium' | 'large';
  /** Whether this is inline or full section */
  variant?: 'inline' | 'section';
}

/**
 * Empty State Component (E9)
 *
 * Unified empty state display for all screens.
 *
 * Per F3/F4 Constraints:
 * - Truthful (states what's missing, not why)
 * - Actionable (hints at what might happen next)
 * - Non-alarming (empty is normal, not an error)
 *
 * Examples from F4:
 * - "No active violations" + "New detections will appear here automatically."
 * - "No cameras configured" + "Contact your admin to add cameras."
 *
 * HARD RULES (E9):
 * - Empty is a valid state, not a failure
 * - Never show "0 results" without context
 * - Always indicate if data will appear automatically
 */
export function EmptyState({
  title,
  message,
  size = 'medium',
  variant = 'section',
}: EmptyStateProps) {
  return (
    <div className={`empty-state empty-state--${size} empty-state--${variant}`}>
      <p className="empty-state__title">{title}</p>
      {message && <p className="empty-state__message">{message}</p>}
    </div>
  );
}
