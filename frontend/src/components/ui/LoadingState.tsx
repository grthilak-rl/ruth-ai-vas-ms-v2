import './LoadingState.css';

interface LoadingStateProps {
  /** Optional loading message */
  message?: string;
  /** Size variant */
  size?: 'small' | 'medium' | 'large';
  /** Whether this is inline or full section */
  variant?: 'inline' | 'section';
}

/**
 * Loading State Component (E9)
 *
 * Unified loading indicator for all screens.
 *
 * Per F3/F4 Constraints:
 * - Non-blocking (per-section, not full-screen)
 * - Brief or absent for fast loads
 * - No percentage progress (creates anxiety per F3 Flow 6)
 *
 * HARD RULES (E9):
 * - Never block full-screen with spinner
 * - Loading states should be per-section where possible
 * - Keep loading messages neutral ("Loading..." not "Please wait...")
 */
export function LoadingState({
  message,
  size = 'medium',
  variant = 'section',
}: LoadingStateProps) {
  return (
    <div
      className={`loading-state loading-state--${size} loading-state--${variant}`}
      role="status"
      aria-live="polite"
    >
      <div className="loading-state__spinner" aria-hidden="true" />
      {message && <p className="loading-state__message">{message}</p>}
    </div>
  );
}
