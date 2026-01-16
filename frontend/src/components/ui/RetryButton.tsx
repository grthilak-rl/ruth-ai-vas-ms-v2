import './RetryButton.css';

interface RetryButtonProps {
  /** Click handler */
  onClick: () => void;
  /** Whether retry is in progress */
  isRetrying?: boolean;
  /** Button label (default: "Retry") */
  label?: string;
  /** Size variant */
  size?: 'small' | 'medium';
}

/**
 * Retry Button Component (E9)
 *
 * Unified retry button for all error states.
 *
 * Per F3 Constraints:
 * - Available wherever recovery is possible
 * - Does NOT reset navigation or scroll position
 * - Shows brief loading state during retry
 *
 * Per F3 Flow 3.1:
 * - "User can retry" - Same button, same action
 *
 * HARD RULES (E9):
 * - Retry buttons exist wherever recovery is possible
 * - Retry does NOT require page refresh
 * - Disabled during retry to prevent double-clicks
 */
export function RetryButton({
  onClick,
  isRetrying = false,
  label = 'Retry',
  size = 'medium',
}: RetryButtonProps) {
  return (
    <button
      type="button"
      className={`retry-button retry-button--${size}`}
      onClick={onClick}
      disabled={isRetrying}
      aria-busy={isRetrying}
    >
      {isRetrying ? (
        <>
          <span className="retry-button__spinner" aria-hidden="true" />
          <span className="retry-button__label">Retrying...</span>
        </>
      ) : (
        <span className="retry-button__label">{label}</span>
      )}
    </button>
  );
}
