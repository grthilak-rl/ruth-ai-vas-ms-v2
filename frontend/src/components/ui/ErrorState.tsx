import { RetryButton } from './RetryButton';
import './ErrorState.css';

interface ErrorStateProps {
  /** Primary message displayed to user (F3: blame-free, human-readable) */
  message: string;
  /** Optional hint for additional context */
  hint?: string;
  /** Optional retry handler. If provided, retry button is shown. */
  onRetry?: () => void;
  /** Whether retry is in progress */
  isRetrying?: boolean;
  /** Size variant */
  size?: 'small' | 'medium' | 'large';
  /** Whether this is inline (within a component) or full (standalone section) */
  variant?: 'inline' | 'section';
}

/**
 * Error State Component (E9)
 *
 * Unified error display for all screens.
 *
 * Per F3 Constraints:
 * - Blame-free language (no "you broke it" messaging)
 * - Human-readable (no error codes, stack traces, or API details)
 * - Recovery-oriented (retry button where applicable)
 *
 * Per F3 Flow 3.1 - Error Messaging:
 * - "Couldn't save. Please try again."
 * - "Having trouble saving. Your work is not lost."
 *
 * HARD RULES (E9):
 * - No silent failures
 * - No console-only errors
 * - No generic "Something broke" without recovery
 * - Every error state has a next action
 */
export function ErrorState({
  message,
  hint,
  onRetry,
  isRetrying = false,
  size = 'medium',
  variant = 'section',
}: ErrorStateProps) {
  return (
    <div
      className={`error-state error-state--${size} error-state--${variant}`}
      role="alert"
      aria-live="polite"
    >
      <div className="error-state__content">
        <p className="error-state__message">{message}</p>
        {hint && <p className="error-state__hint">{hint}</p>}
      </div>
      {onRetry && (
        <RetryButton
          onClick={onRetry}
          isRetrying={isRetrying}
          size={size === 'large' ? 'medium' : 'small'}
        />
      )}
    </div>
  );
}
